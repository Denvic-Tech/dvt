from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

from src.enums import ExtensionDepsStatus
from src.modules.extension_management.infra import (
    dependency_bootstrap as extensions,
    dependency_manager,
)
from src.modules.extension_management.infra.db_models import ExtensionRecord


@pytest.mark.asyncio
@pytest.mark.parametrize("returncode", [0, 1])
async def test_local_dependency_barrier_preserves_shared_record(
    async_test_db_engine, monkeypatch, tmp_path, returncode,
):
    factory = async_sessionmaker(async_test_db_engine, expire_on_commit=False)
    async with factory() as session:
        record = ExtensionRecord(
            name="local-deps", display_name="Local deps", is_installed=True,
            deps_status=ExtensionDepsStatus.READY, install_path=str(tmp_path),
            manifest_json={"requirements": ["example-package==1.0"]},
            error_message="Existing diagnostic",
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        timestamp = record.updated_at

    monkeypatch.setattr(extensions, "AsyncSessionLocal", factory)
    monkeypatch.setattr(dependency_manager, "AsyncSessionLocal", factory)
    monkeypatch.setattr(
        extensions, "open", lambda *_args: (tmp_path / "deps.lock").open("a"), raising=False,
    )
    monkeypatch.setattr(
        dependency_manager.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=returncode, stderr="Local pip failure", stdout="",
        ),
    )
    if returncode:
        with pytest.raises(RuntimeError, match="Local pip failure"):
            await extensions.ensure_extension_deps_installed(
                raise_on_failure=True, publish_status=False,
            )
    else:
        await extensions.ensure_extension_deps_installed(
            raise_on_failure=True, publish_status=False,
        )

    async with factory() as session:
        record = (await session.execute(select(ExtensionRecord))).scalars().one()
        assert record.deps_status == ExtensionDepsStatus.READY
        assert record.error_message == "Existing diagnostic"
        assert record.updated_at == timestamp
