"""In-memory индекс документа lineage: колонки по ссылке, обратные зависимости, порты нод."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ...lineage import ColumnLineage, LineageRef, PortLineage, ProjectLineage


@dataclass(slots=True)
class LineageIndex:
    project_id: str
    columns: dict[str, tuple[PortLineage, ColumnLineage]] = field(default_factory=dict)
    dependents: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    ports: dict[tuple[str, str], PortLineage] = field(default_factory=dict)

    def column(self, ref: LineageRef) -> tuple[PortLineage, ColumnLineage] | None:
        return self.columns.get(ref.key)

    def node_ports(self, node_id: str) -> list[PortLineage]:
        return [port for (pid, _), port in self.ports.items() if pid == node_id]

    def dependents_of(self, ref: LineageRef) -> list[LineageRef]:
        return [LineageRef.parse(key) for key in self.dependents.get(ref.key, [])]

    def dataset_ids(self) -> set[str]:
        found: set[str] = set()
        for _, column in self.columns.values():
            for dep in column.deps:
                if dep.is_dataset_field and dep.dataset_id:
                    found.add(dep.dataset_id)
        return found


def index_lineage(project_id: str, lineage: ProjectLineage) -> LineageIndex:
    index = LineageIndex(project_id=project_id)
    for port in lineage.ports:
        index.ports[(port.node_id, port.port)] = port
        for column in port.columns:
            key = port.ref(column.name).key
            index.columns[key] = (port, column)
            for dep in column.deps:
                index.dependents[dep.key].append(key)
    return index
