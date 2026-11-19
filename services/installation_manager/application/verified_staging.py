"""Opt-in preparation of a pinned release, without applying the Compose project."""

from __future__ import annotations

import errno
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from packaging.version import Version

from ..domain.operation_state import (
    ArtifactKind,
    Checkpoint,
    CheckpointOutcome,
    FailureReason,
    InstanceIdentity,
    InvalidTransition,
    Observation,
    Operation,
    OperationKind,
    OperationStage,
    ReleasePin,
)
from ..domain.release_manifest import (
    REQUIRED_SERVICES,
    FileDescriptor,
    IncomingTransition,
    ReleaseManifest,
    StagingError,
    canonical_json,
    digest_of,
)
from ..infrastructure.catalog_files import read_selected_manifest
from ..infrastructure.offline_host import (
    check_bundle_host,
    check_engine,
    check_offline_extensions,
    import_offline_images,
    read_bundle,
)
from ..infrastructure.operation_store import OperationStore
from ..infrastructure.release_verification import (
    MAX_MANIFEST_BYTES,
    TrustPolicy,
    invalid_package,
    verify_file,
)
from ..infrastructure.staging_artifacts import (
    artifact_directory,
    load_config,
    read_artifact,
    write_artifact,
)
from ..infrastructure.staging_commands import Deadline, RetryPolicy
from ..infrastructure.staging_compose import (
    ObservedRelease,
    check_model,
    compare_project,
    effective_config,
    validate_template,
)
from ..infrastructure.staging_docker import StagingDocker
from ..infrastructure.staging_downloads import ReleaseDownloader
from ..infrastructure.staging_host import (
    FilesystemBudget,
    HostPaths,
    check_filesystems,
    check_platform,
    incompatible,
    require_writable,
    selected_profile,
    storage_budgets,
)


@dataclass(frozen=True)
class StagedRelease:
    operation_id: UUID
    pin: ReleasePin
    platform: str
    compose_path: Path
    bootstrap_path: Path
    profiles: tuple[str, ...]
    images: dict[str, str]
    additions: tuple[str, ...]
    recreate: tuple[str, ...]
    retire: tuple[str, ...]
    schema_target: str
    transition: IncomingTransition | None
    budgets: tuple[FilesystemBudget, ...]
    environment: dict[str, str] = field(repr=False)


@dataclass(frozen=True)
class VerifiedStaging:
    store: OperationStore
    trust: TrustPolicy
    downloader: ReleaseDownloader
    docker: StagingDocker
    paths: HostPaths
    preparer_version: str
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    http_manager: bool = False
    local_ui_image: str | None = None

    def prepare(
        self,
        operation_id: UUID,
        manifest_url: str,
        *,
        observed: ObservedRelease | None = None,
        applied: ReleasePin | None = None,
        bootstrap_image: str | None = None,
    ) -> StagedRelease:
        """Prepare using the saved intent and independently established running state.

        `applied` is the last committed release pointer; `observed` also carries the source
        schema and independently verified running images. Both pins are absent for legacy.
        A first installation can replace the single matching bootstrap manager identified
        by the host executor's independently pinned `bootstrap_image`.
        """
        with self.store.claim(operation_id) as owner:
            operation = self.store.get(operation_id)
            assert operation is not None
            if operation.request.kind not in (OperationKind.INSTALL, OperationKind.UPDATE):
                raise InvalidTransition("Staging currently supports installation and update")
            if operation.stage not in (
                OperationStage.ADMITTED,
                OperationStage.PREPARING,
                OperationStage.PREPARED,
            ):
                raise InvalidTransition("The operation has already entered a later stage")
            stage = operation.stage
            if stage is OperationStage.ADMITTED:
                stage = OperationStage.PREPARING
                owner.checkpoint(Checkpoint(stage))

            def record_failure(error: StagingError) -> None:
                outcome = (
                    CheckpointOutcome.RETRYABLE_ERROR
                    if error.retryable
                    else CheckpointOutcome.BLOCKED
                )
                owner.checkpoint(Checkpoint(stage, outcome, error.reason))

            try:
                prepared = self._prepare(
                    operation, manifest_url, observed, applied, bootstrap_image
                )
            except StagingError as error:
                record_failure(error)
                raise
            except OSError as failure:
                if failure.errno not in {errno.ENOSPC, errno.EDQUOT}:
                    raise
                error = StagingError(
                    FailureReason.DISK_SPACE,
                    "A staging artifact could not be written because its storage is full",
                    "Free space and inodes on the staging filesystem and continue the same operation",
                )
                record_failure(error)
                raise error from None

            source_images = observed.images if observed else {}
            owner.checkpoint(
                Checkpoint(
                    OperationStage.PREPARED,
                    CheckpointOutcome.VERIFIED,
                    observation=Observation(
                        source_digest=applied.manifest_digest if applied else None,
                        target_digest=prepared.pin.manifest_digest,
                        observed_digest=source_images.get("gateway", "").split("@")[-1] or None,
                        source_revision=observed.revision if observed else None,
                        target_revision=prepared.schema_target,
                        observed_revision=observed.revision if observed else None,
                        staging_id=operation.id,
                    ),
                )
            )
            return prepared

    def _prepare(
        self,
        operation: Operation,
        manifest_url: str,
        observed: ObservedRelease | None,
        applied: ReleasePin | None,
        bootstrap_image: str | None,
    ) -> StagedRelease:
        deadline = Deadline(self.retry, self.paths.temporary)
        require_writable(self.paths.temporary, "temporary staging")
        identity = self.store.identity()
        assert identity is not None and identity.instance_id == operation.instance_id
        values = load_config(self.store, operation.request.config_id)
        directory = artifact_directory(self.store, ArtifactKind.STAGING, operation.id)
        pin = operation.request.release
        manifest_path = directory / "manifest.json"
        signed = read_artifact(manifest_path, MAX_MANIFEST_BYTES)
        bundle = None
        if operation.request.bundle_id is not None:
            bundle = read_bundle(self.store, operation.request.bundle_id, self.trust)
            if (
                bundle.pin != pin or bundle.index["kind"] != operation.request.kind.value
                or (signed is not None and signed != bundle.signed)
            ):
                raise invalid_package("The selected offline bundle differs from the saved intent")
            signed = bundle.signed
        if signed is None:
            signed = read_selected_manifest(Path(identity.data_dir), pin)
        if signed is None:
            signed = self.downloader.get(
                manifest_url, MAX_MANIFEST_BYTES, cwd=directory, deadline=deadline
            )
        manifest = self.trust.verify(signed, pin)
        if manifest.channel == "rc" and values.pop("DVT_ALLOW_PRERELEASE", "").lower() != "true":
            raise incompatible(
                "A release candidate requires explicit consent in the saved configuration"
            )
        values.pop("DVT_ALLOW_PRERELEASE", None)
        transition = self._check_release(operation, manifest, observed, applied)
        write_artifact(manifest_path, signed)

        profile, env, profiles = self._profile(operation, identity, manifest, values)
        require_writable(Path(identity.data_dir), "DVT data")
        if observed is not None:
            require_writable(self.paths.backup, "backup")
        info = self.docker.info(deadline)
        platform = check_platform(
            info,
            self.docker.compose_version(deadline),
            self.paths.os_release,
            manifest.environment,
            profile,
        )
        release = manifest.platforms.get(platform)
        if release is None:
            raise incompatible(
                "The verified release does not provide a platform matching this host"
            )

        compose_path, bootstrap_path = directory / "compose.yaml", directory / "bootstrap.sh"
        if bundle is not None:
            check_engine(info)
            check_bundle_host(bundle, self.paths.os_release, profiles, platform)
            for path in (compose_path, bootstrap_path):
                write_artifact(path, bundle.verify_asset(path.name))
        self._asset(compose_path, release.compose, deadline, validate=validate_template)
        self._asset(bootstrap_path, release.bootstrap, deadline)
        full = self.docker.config(compose_path, identity.compose_project, ("*",), env, deadline)
        check_model(full, identity, release, env, active=False)
        current = self.docker.config(
            compose_path, identity.compose_project, profiles, env, deadline
        )
        check_model(current, identity, release, env, active=True)
        local_ui = (
            self.local_ui_image
            if operation.request.kind is OperationKind.INSTALL and bundle is None else None
        )
        if local_ui:
            if not self.docker.local_image(local_ui, platform, deadline, allow_index=True):
                raise invalid_package("The local UI image is unavailable")
            current["services"]["ui"]["image"] = local_ui
        require_bootstrap_manager = (
            operation.request.kind is OperationKind.INSTALL
            and bundle is None
            and bootstrap_image is not None
        )
        plan = compare_project(
            current,
            identity,
            env,
            self.docker,
            observed,
            deadline,
            bootstrap_image=bootstrap_image,
            require_bootstrap_manager=require_bootstrap_manager,
            http_manager=self.http_manager,
        )
        images = {
            img.reference: img
            for name, img in release.images.items()
            if bundle is not None or (
                name in plan.image_references and not (name == "ui" and local_ui)
            )
        }
        if bundle is None:
            self.docker.check_registries(set(images), info)
        else:
            from ..infrastructure.application_host import ApplyError
            from .application_apply import _validate_runtime

            try:
                _validate_runtime(current)
            except ApplyError as error:
                raise StagingError(
                    error.reason, str(error), "Check the signed offline Compose model"
                ) from None
        missing = [
            image
            for ref, image in images.items()
            if not self.docker.local_image(ref, platform, deadline)
        ]
        budgets = storage_budgets(
            info,
            self.paths,
            Path(identity.data_dir),
            directory,
            profile,
            missing,
            manifest.environment.pull_parallelism,
            plan.persistent_paths,
            deadline,
        )
        check_filesystems(budgets)
        if bundle is None:
            for image in missing:
                self.docker.pull(image.reference, platform, deadline)
        else:
            import_offline_images(bundle, self.docker, deadline)
            check_offline_extensions(
                bundle, Path(identity.data_dir) / "extensions", self.docker, deadline,
                platform=platform,
            )

        # A download can consume the safety margin even if its estimate was correct
        # on a quiet host. Keep headroom for the old application and the backup.
        check_filesystems(
            storage_budgets(
                info,
                self.paths,
                Path(identity.data_dir),
                directory,
                profile,
                [],
                manifest.environment.pull_parallelism,
                plan.persistent_paths,
                deadline,
            )
        )
        # Project drift during pulls invalidates the plan before it becomes usable.
        if (
            compare_project(
                current,
                identity,
                env,
                self.docker,
                observed,
                deadline,
                bootstrap_image=bootstrap_image,
                require_bootstrap_manager=require_bootstrap_manager,
                http_manager=self.http_manager,
            )
            != plan
        ):
            raise incompatible("The running Compose project changed while preparing the release")

        write_artifact(
            directory / "plan.json",
            canonical_json(
                {
                    "format_version": 1,
                    "release_id": pin.release_id,
                    "manifest_digest": pin.manifest_digest,
                    "platform": platform,
                    "config_id": str(operation.request.config_id),
                    "profiles": profiles,
                    "services": plan.image_references,
                    "model_digest": digest_of(canonical_json(current)),
                    "trust": self.trust.as_document(),
                    "add": plan.additions,
                    "recreate": plan.recreate,
                    "retire": plan.retire,
                    "applied_release_id": applied.release_id if applied else None,
                    "applied_manifest_digest": applied.manifest_digest if applied else None,
                    "observed_version": observed.version if observed else None,
                    "observed_revision": observed.revision if observed else None,
                    "observed_images": plan.source_images,
                    "target_revision": manifest.database_schema.target_revision,
                    "transition": transition.model_dump(mode="json") if transition else None,
                }
            ),
        )
        return StagedRelease(
            operation.id,
            pin,
            platform,
            compose_path,
            bootstrap_path,
            profiles,
            plan.image_references,
            plan.additions,
            plan.recreate,
            plan.retire,
            manifest.database_schema.target_revision,
            transition,
            tuple(budgets),
            env,
        )

    def _check_release(
        self,
        operation: Operation,
        manifest: ReleaseManifest,
        observed: ObservedRelease | None,
        applied: ReleasePin | None,
    ) -> IncomingTransition | None:
        if Version(self.preparer_version) < Version(
            manifest.compatibility.minimum_preparer_version
        ):
            raise incompatible("The current preparer is too old for this release")
        schema = manifest.database_schema
        if operation.request.kind is OperationKind.INSTALL:
            if not schema.initial_install or observed is not None or applied is not None:
                raise incompatible(
                    "The candidate is not an initial installation on an empty project"
                )
            return None
        if (
            observed is None
            or applied != observed.pin
            or not (REQUIRED_SERVICES - {"migrate"}) <= observed.images.keys()
        ):
            raise incompatible("The applied and independently observed source release do not agree")
        if Version(manifest.version) < Version(observed.version):
            raise incompatible("Selecting an earlier release requires a verified recovery plan")
        for route in schema.from_releases:
            if (
                Version(route.version) == Version(observed.version)
                and route.revision == observed.revision
            ):
                return route
        raise incompatible(
            "No signed transition matches the actual source version and database revision"
        )

    @staticmethod
    def _profile(
        operation: Operation,
        identity: InstanceIdentity,
        manifest: ReleaseManifest,
        values: dict[str, str],
    ):
        env, profiles = effective_config(values, identity, operation.request, manifest.version)
        return selected_profile(manifest.environment, profiles), env, profiles

    def _asset(
        self,
        path: Path,
        descriptor: FileDescriptor,
        deadline: Deadline,
        *,
        validate: Callable[[bytes], None] | None = None,
    ) -> None:
        content = read_artifact(path, descriptor.size)
        if content is None:
            content = self.downloader.get(
                descriptor.url, descriptor.size, cwd=path.parent, deadline=deadline
            )
        verify_file(content, descriptor, path.name)
        if validate is not None:
            validate(content)
        write_artifact(path, content)
