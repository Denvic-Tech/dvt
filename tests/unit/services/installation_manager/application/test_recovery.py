import pytest

from services.installation_manager.application.recovery import MigrationState, classify_migration


@pytest.mark.parametrize(
    ("phase", "revision", "running", "locked", "expected"),
    [
        (None, "0069", False, False, MigrationState.NOT_STARTED),
        (None, "0070", True, False, MigrationState.IN_PROGRESS),
        (None, "0070", False, True, MigrationState.IN_PROGRESS),
        (None, "0070", False, False, MigrationState.UNKNOWN),
        ("unrecognized", "0070", False, False, MigrationState.UNKNOWN),
        ("core", "0070", False, False, MigrationState.CORE_COMMITTED),
        ("done", "0069", False, False, MigrationState.UNKNOWN),
        ("done", "0070", False, False, MigrationState.TARGET_CONFIRMED),
        ("resumed", "0070", False, False, MigrationState.RESUMED),
    ],
)
def test_restart_classification_requires_observed_revision_and_receipt(
    phase, revision, running, locked, expected,
):
    assert classify_migration(
        phase=phase, revision=revision, source="0069", target="0070", running=running, locked=locked
    ) is expected
