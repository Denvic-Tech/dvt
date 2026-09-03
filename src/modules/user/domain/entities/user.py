from dataclasses import dataclass

from src import enums


@dataclass(slots=True)
class User:
    id: str
    organization_id: str
    role: enums.DVTDefaultRoles | str = enums.DVTDefaultRoles.USER

    def change_role(self, role: enums.DVTDefaultRoles | str) -> None:
        self.role = role

    def move_to_organization(self, organization_id: str) -> None:
        if not organization_id:
            raise ValueError("organization_id must not be empty")

        self.organization_id = organization_id
