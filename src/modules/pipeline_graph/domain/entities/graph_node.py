from dataclasses import dataclass, field

from src.shared.value_objects import OrganizationID, ProjectID, UserID

from ..value_objects import GraphNodeID


@dataclass(frozen=True, kw_only=True)
class GraphNode:
    id: GraphNodeID
    
    user_id: UserID
    project_id: ProjectID
    organization_id: OrganizationID
