from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from tests.data.installation_manager.verified_staging.fixtures import (
    ORIGIN,
    ROOT,
    SOURCE_IMAGE,
    TARGET_IMAGE,
    make_compose,
    make_manifest,
    sign_manifest,
)

from services.installation_manager import catalog_api
from services.installation_manager.application.release_catalog import (
    CATALOG_PATH,
    CatalogHost,
    ReleaseCatalog,
    SourceFacts,
    version_tag,
)
from services.installation_manager.domain.operation_state import FailureReason
from services.installation_manager.domain.release_manifest import (
    StagingError,
    canonical_json,
    digest_of,
)
from services.installation_manager.host_bootstrap import CONTROL, atomic_write
from services.installation_manager.infrastructure.release_verification import TrustPolicy

HOST = CatalogHost("linux/amd64", "debian", "13")
LIST = ORIGIN + CATALOG_PATH


def offer(manifest, *, corrupt=False):
    pin, content = sign_manifest(manifest)
    if corrupt:
        envelope = json.loads(content)
        envelope["manifest_signature"] = "00" * 64
        content = canonical_json(envelope)
        pin = type(pin)(pin.release_id, digest_of(content))
    version = version_tag(manifest["version"])
    url = f"{LIST}/{version}/manifest/{pin.manifest_digest}"
    schema = manifest["schema"]
    return {
        "format_version": 1,
        "version": version,
        "channel": manifest["channel"],
        "release_id": pin.release_id,
        "published_at": "2026-11-16T08:00:00Z",
        "platforms": list(manifest["platforms"]),
        "distributions": manifest["environment"]["distributions"],
        "initial_install": schema["initial_install"],
        "target_revision": schema["target_revision"],
        "from_releases": [
            {"version": row["version"], "revision": row["revision"]}
            for row in schema["from_releases"]
        ],
        "manifest_digest": pin.manifest_digest,
        "manifest_url": url,
    }, content


class Network:
    def __init__(self, *offers):
        self.online = True
        self.requests = []
        self.files = {row["manifest_url"]: raw for row, raw in offers}
        self.publish(*(row for row, _ in offers))

    def publish(self, *rows):
        self.files[LIST] = canonical_json({"format_version": 1, "releases": rows})

    def get(self, url, _limit):
        self.requests.append(url)
        if not self.online:
            raise OSError("Distributor is offline")
        return self.files[url]


@pytest.fixture
def release(tmp_path):
    manifest = make_manifest(make_compose(TARGET_IMAGE, infrastructure=SOURCE_IMAGE))
    (tmp_path / CONTROL).mkdir(mode=0o700)
    return manifest


def client(path, network, *, trust=True, host=HOST):
    verifier = TrustPolicy({"beta-root": ROOT.public_key().public_bytes_raw()})
    return ReleaseCatalog(
        data=path, origin=ORIGIN, host=host, download=network.get,
        verify=verifier.verify if trust else None,
    )


def test_cache_preserves_catalog_date_and_the_same_verified_pin_when_distribution_is_down(
    tmp_path, release,
):
    row, raw = offer(release)
    network = Network((row, raw))
    catalog = client(tmp_path, network)
    snapshot = catalog.refresh()
    (entry,) = snapshot.releases
    source = SourceFacts("1.23.0", "0068")
    assert catalog.paths(snapshot, source)[entry.version] == (entry,)
    assert catalog.paths(snapshot, SourceFacts("1.23.0", "9999")) == {}
    selection = catalog.select(entry, source)
    network.files[row["manifest_url"]] = b"changed target"
    network.online = False

    restarted = client(tmp_path, network)
    cached = restarted.refresh()
    assert cached.fetched_at == snapshot.fetched_at
    assert cached.error == FailureReason.DISTRIBUTOR_UNAVAILABLE.value
    assert restarted.select(cached.releases[0], source) == selection
    assert network.requests.count(row["manifest_url"]) == 1
    with pytest.raises(StagingError, match="No DVT release trust verifier"):
        client(tmp_path, network, trust=False).select(entry, source)


def test_recommend_intermediate_stable_from_actual_revision_and_keep_rc_opt_in(tmp_path, release):
    intermediate = offer(release)
    release.update(version="1.25.0", release_id="final")
    schema = release["schema"]
    schema.update(
        target_revision="0070",
        from_releases=[{
            "version": "1.24.0", "revision": "0069",
            "migration": "from_revision", "rollback": "restore_backup",
        }],
    )
    end = offer(release)
    release.update(version="1.25.0rc2", release_id="rc", channel="rc")
    candidate = offer(release)
    network = Network(end, candidate, intermediate)
    catalog = client(tmp_path, network)
    snapshot = catalog.refresh()
    source = SourceFacts("1.23.0", "0068")
    stable = catalog.paths(snapshot, source)
    assert [row.version for row in stable["1.25.0"]] == ["1.24.0", "1.25.0"]
    selection = catalog.select_route(snapshot, stable["1.25.0"][-1], source)
    assert (selection.pin, *selection.following) == tuple(row.pin for row in stable["1.25.0"])
    assert "1.25.0-rc2" not in stable
    assert "1.25.0-rc2" in catalog.paths(snapshot, source, allow_rc=True)
    with pytest.raises(StagingError, match="different compatible release"):
        catalog.select(stable["1.25.0"][-1], source)
    rc = catalog.paths(snapshot, source, allow_rc=True)["1.25.0-rc2"][-1]
    advanced = SourceFacts("1.24.0", "0069")
    with pytest.raises(StagingError, match="explicit consent"):
        catalog.select(rc, advanced)
    assert catalog.select(rc, advanced, allow_rc=True).pin.release_id == "rc"


@pytest.mark.parametrize("distribution,version", [("debian", "12"), ("", "")])
def test_catalog_selects_signed_release_outside_declared_distributions(
    tmp_path, release, distribution, version,
):
    row, raw = offer(release)
    host = CatalogHost("linux/amd64", distribution, version)
    catalog = client(tmp_path, Network((row, raw)), host=host)
    snapshot = catalog.refresh()
    paths = catalog.paths(snapshot, observed=None)

    selected = catalog.select(paths[row["version"]][-1], observed=None)

    assert selected.pin.manifest_digest == row["manifest_digest"]


def test_catalog_cannot_authorize_a_transition_or_substitute_untrusted_content(tmp_path, release):
    row, raw = offer(release)
    forged = dict(row, from_releases=[{"version": "1.22.0", "revision": "0060"}])
    network = Network((forged, raw))
    catalog = client(tmp_path, network)
    snapshot = catalog.refresh()
    source = SourceFacts("1.22.0", "0060")
    with pytest.raises(StagingError, match="different compatible release"):
        catalog.select(snapshot.releases[0], source)

    network.publish(dict(row, manifest_url=row["manifest_url"].rsplit("/", 1)[0]))
    cached = catalog.refresh()
    assert cached.error == FailureReason.INVALID_PACKAGE.value
    assert cached.releases == snapshot.releases
    assert all(not url.endswith("/manifest") for url in network.requests)

    invalid, invalid_raw = offer(release, corrupt=True)
    network = Network((invalid, invalid_raw))
    catalog = client(tmp_path, network)
    with pytest.raises(StagingError, match="trust chain"):
        catalog.select(catalog.refresh().releases[0], SourceFacts("1.23.0", "0068"))


def test_observer_uses_running_gateway_and_database_before_exposing_source(tmp_path, monkeypatch):
    (tmp_path / CONTROL).mkdir(mode=0o700)
    config = {"data": str(tmp_path), "instance": "fixture", "project": "fixture"}
    store = SimpleNamespace(active=lambda: None)
    roles = {"installation_manager": [{}]}
    monkeypatch.setattr(catalog_api, "_containers", lambda _: roles)
    assert catalog_api.observe_source(config, store) is None
    roles |= {
        "gateway": [{"State": {"Running": True}, "Image": "gateway-image"}],
        "postgres": [{"State": {"Running": True}, "Id": "postgres"}],
    }
    with pytest.raises(ValueError, match="No supported source"):
        catalog_api.observe_source(config, store)

    atomic_write(tmp_path / CONTROL / "current-release.json", canonical_json({
        "format_version": 1,
        "instance": "fixture",
        "version": "1.23.0rc2",
        "revision": "0068",
        "database": "123:456",
        "images": {"gateway": SOURCE_IMAGE},
    }))
    (tmp_path / ".env").write_text("DVT_VERSION=1.99.0\n")
    image = {"RepoDigests": [SOURCE_IMAGE]}
    monkeypatch.setattr(
        catalog_api, "docker", lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps([image])),
    )
    results = {
        "SELECT version_num FROM alembic_version": "0068",
        catalog_api.DATABASE_ID: "123:456",
    }
    monkeypatch.setattr(
        catalog_api.ComposeMaintenanceHost, "sql", lambda container, query: results[query],
    )
    assert catalog_api.observe_source(config, store) == SourceFacts("1.23.0-rc2", "0068")
    results["SELECT version_num FROM alembic_version"] = "0099"
    with pytest.raises(ValueError, match="database differs"):
        catalog_api.observe_source(config, store)
    image["RepoDigests"] = [TARGET_IMAGE]
    with pytest.raises(ValueError, match="Gateway image differs"):
        catalog_api.observe_source(config, store)


def test_current_trust_override_revokes_cached_pin_and_explicit_ca_is_used(
    tmp_path, release, monkeypatch,
):
    row, raw = offer(release)
    network = Network((row, raw))
    config = {
        "data": str(tmp_path), "instance": "fixture",
        "release_catalog": {
            "origin": ORIGIN, "platform": HOST.platform, "distribution": HOST.distribution,
            "distribution_version": HOST.distribution_version,
            "trust": {"roots": {"beta-root": ROOT.public_key().public_bytes_raw().hex()},
                      "revoked_signers": []},
        },
    }
    ca = tmp_path / CONTROL / "release-catalog-ca.pem"
    atomic_write(ca, b"supplied CA bundle")
    observed_ca = []

    def get(downloader, url, limit, **kwargs):
        observed_ca.append(downloader.ca_file)
        return network.get(url, limit)

    monkeypatch.setattr(catalog_api.ReleaseDownloader, "get", get)
    catalog = catalog_api.configured_catalog(config)
    (entry,) = catalog.refresh().releases
    source = SourceFacts("1.23.0", "0068")
    catalog.select(entry, source)
    assert observed_ca == [ca, ca]

    target = tmp_path / CONTROL / "release-trust.json"
    signer = json.loads(raw)["signing_key"]["public_key"]
    document = {**config["release_catalog"]["trust"],
                "revoked_signers": [digest_of(bytes.fromhex(signer))]}
    atomic_write(target, canonical_json(document))
    network.online = False
    next_catalog = catalog_api.configured_catalog(config)
    assert next_catalog.refresh().releases == (entry,)
    with pytest.raises(StagingError, match="trust chain"):
        next_catalog.select(entry, source)
    assert network.requests.count(row["manifest_url"]) == 1
    atomic_write(target, b"null")
    with pytest.raises(ValueError, match="trust policy"):
        catalog_api.configured_catalog(config)
