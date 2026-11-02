"""Описания колонок входного порта ноды из Data Catalog для экспорта в физический слой.

Используется Write-нодами на воркере: описания берутся из сохранённого документа lineage и
аннотаций без пересборки проекции. Любая ошибка каталога даёт пустой словарь и предупреждение в
лог, прогон не падает. Импорты каталога ленивые: пакет `data_catalog` намеренно не импортируется
рядом с `node_dsl`.
"""

from __future__ import annotations

from collections.abc import Mapping

from src.logger import logger


async def load_catalog_descriptions(
    *,
    project_id: str,
    node_id: str,
    port: str = "df",
) -> dict[str, str]:
    """`имя колонки DataFrame -> непустое описание`; `{}`, если каталог выключен или недоступен."""
    try:
        import config

        if not config.DATA_CATALOG.WORKER_OBSERVATION_ENABLED:
            return {}
        from src.db import AsyncSessionLocal
        from src.modules.data_catalog import resolve_port_descriptions

        async with AsyncSessionLocal() as session:
            return dict(
                await resolve_port_descriptions(
                    session=session, project_id=project_id, node_id=node_id, port=port
                )
            )
    except Exception as exc:
        logger.warning(
            "Data catalog descriptions are unavailable for node {} port {}: {}", node_id, port, exc
        )
        return {}


def map_descriptions_to_targets(
    descriptions: Mapping[str, str],
    column_mapping: Mapping[str, str] | None,
) -> dict[str, str]:
    """Переводит описания колонок DataFrame в описания целевых колонок по маппингу источник -> цель."""
    mapping = dict(column_mapping or {})
    result: dict[str, str] = {}
    for source, text in descriptions.items():
        target = mapping.get(source, source)
        if text and text.strip():
            result[target] = text.strip()
    return result
