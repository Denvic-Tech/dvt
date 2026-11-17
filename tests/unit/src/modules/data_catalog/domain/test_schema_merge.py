from datetime import UTC, datetime
from itertools import count

from src.modules.data_catalog.domain import DatasetField, FieldStatus, ObservedField
from src.modules.data_catalog.domain.policies import merge_observed_fields

NOW = datetime(2026, 10, 7, tzinfo=UTC)
EARLIER = datetime(2026, 10, 1, tzinfo=UTC)


def _field(name: str, dtype: str, status: FieldStatus = FieldStatus.OK) -> DatasetField:
    return DatasetField(
        id=f"f-{name}",
        dataset_id="d",
        name=name,
        status=status,
        first_seen_at=EARLIER,
        last_seen_at=EARLIER,
        dtype=dtype,
        observed_via=("conn-a",),
    )


def _merge(existing, observed, **options):
    ids = count(1)
    return merge_observed_fields(
        dataset_id="d",
        existing=existing,
        observed=observed,
        connection_id="conn-b",
        now=NOW,
        new_id=lambda: f"new-{next(ids)}",
        **options,
    )


def test_merge_marks_new_missing_and_type_changed_without_dropping_rows():
    existing = [_field("id", "integer"), _field("name", "text"), _field("gone", "text")]
    observed = [
        ObservedField(name="id", dtype="INTEGER"),
        ObservedField(name="name", dtype="varchar"),
        ObservedField(name="created", dtype="timestamp", ordinal=3),
    ]

    merged = _merge(existing, observed)

    by_name = {field.name: field for field in merged}
    assert set(by_name) == {"id", "name", "gone", "created"}
    assert by_name["id"].status is FieldStatus.OK
    assert by_name["id"].observed_via == ("conn-a", "conn-b")
    assert by_name["id"].last_seen_at == NOW
    assert by_name["name"].status is FieldStatus.TYPE_CHANGED
    assert by_name["name"].dtype == "varchar"
    assert by_name["gone"].status is FieldStatus.MISSING
    assert by_name["gone"].last_seen_at == EARLIER
    assert by_name["created"].status is FieldStatus.NEW
    assert by_name["created"].id == "new-1"
    assert by_name["created"].observed_via == ("conn-b",)


def test_untrusted_types_keep_dtype_and_type_status_but_restore_missing():
    existing = [
        _field("id", "INT"),
        _field("flag", "BOOLEAN", FieldStatus.TYPE_CHANGED),
        _field("back", "STRING", FieldStatus.MISSING),
    ]
    observed = [
        ObservedField(name="id", dtype="FLOAT", nullable=True, comment="pk"),
        ObservedField(name="flag", dtype="STRING"),
        ObservedField(name="back", dtype="STRING"),
        ObservedField(name="fresh", dtype="DATETIME", ordinal=4, primary_key=True),
    ]

    merged = _merge(existing, observed, update_types=False)

    by_name = {field.name: field for field in merged}
    assert by_name["id"].dtype == "INT", "типы FULL-прогона не доверяются"
    assert by_name["id"].status is FieldStatus.OK
    assert by_name["id"].source_comment == "pk"
    assert by_name["flag"].status is FieldStatus.TYPE_CHANGED, "статус типа без доверия не трогается"
    assert by_name["back"].status is FieldStatus.OK, "вернувшаяся колонка снова ok"
    assert by_name["fresh"].status is FieldStatus.NEW
    assert (by_name["fresh"].dtype, by_name["fresh"].ordinal, by_name["fresh"].primary_key) == (None, None, False)


def test_partial_observation_does_not_mark_unseen_fields_missing():
    existing = [_field("id", "INT"), _field("unseen", "STRING")]

    merged = _merge(existing, [ObservedField(name="id", dtype="INT")], mark_missing=False)

    by_name = {field.name: field for field in merged}
    assert by_name["unseen"].status is FieldStatus.OK
    assert by_name["unseen"].last_seen_at == EARLIER
