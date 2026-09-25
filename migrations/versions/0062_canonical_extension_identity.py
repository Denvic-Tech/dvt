"""Canonical extension names with preserved physical storage.

Revision ID: 0062
Revises: 0061
"""
import hashlib
import re

import sqlalchemy as sa
from alembic import op

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


_CANONICAL_RE = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
)


def _canonical(value):
    raw = value.strip() if isinstance(value, str) else str(value or "").strip()

    # Сохраняем старую семантику для уже корректных имён.
    if _CANONICAL_RE.fullmatch(raw):
        return re.sub(r"[-_.]+", "-", raw).lower()

    # Best-effort normalization для старых/грязных данных.
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    slug = slug or "extension"

    # Так `foo bar`, `foo@bar`, `.foo`, `foo-` и т.п.
    # не превратятся молча в одну identity.
    digest = hashlib.sha256(raw.encode()).hexdigest()[:8]

    return f"{slug}-{digest}"


def _storage_schema(name):
    # Frozen pre-0062 algorithm: changing identity must not move user data.
    raw = name.strip()
    slug = re.sub(r"[^a-z0-9_]+", "_", raw.lower()).strip("_") or "extension"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:8]
    suffix = f"_{digest}" if raw != raw.lower() or not re.fullmatch(r"[a-z0-9_]+", raw) else ""
    available = 63 - len("dvt_ext_") - len(suffix)
    if len(slug) > available:
        suffix = f"_{digest}"
        slug = slug[:63 - len("dvt_ext_") - len(suffix)].rstrip("_") or "extension"
    return f"dvt_ext_{slug}{suffix}"


def upgrade():
    bind = op.get_bind()
    table = sa.table(
        "extensions", sa.column("id", sa.String), sa.column("name", sa.String),
        sa.column("manifest_json", sa.JSON), sa.column("storage_schema", sa.String),
    )
    rows = bind.execute(sa.select(table.c.id, table.c.name, table.c.manifest_json)).mappings().all()
    updates = []
    owners = {}
    for row in rows:
        payload = dict(row["manifest_json"] or {})
        name = _canonical(payload.get("package_name") or payload.get("name") or row["name"])
        aliases = set(payload.get("legacy_names") or ()) | {row["name"]}
        aliases.discard(name)
        for alias in aliases | {name}:
            key = re.sub(r"[-_.]+", "-", alias.strip()).lower()
            if key in owners and owners[key] != row["id"]:
                raise ValueError(f"Conflicting extension identity {alias!r}; migration aborted")
            owners[key] = row["id"]
        payload.update(name=name, package_name=name, legacy_names=sorted(aliases))
        updates.append((row["id"], name, payload, _storage_schema(row["name"])))
    op.add_column("extensions", sa.Column("storage_schema", sa.String(), nullable=True))
    for record_id, name, payload, schema in updates:
        bind.execute(table.update().where(table.c.id == record_id).values(
            name=name, manifest_json=payload, storage_schema=schema,
        ))


def downgrade():
    # Names cannot safely be reverted: subsequent packages may already use them.
    # Likewise dropping the mapping would orphan schemas belonging to old names.
    pass
