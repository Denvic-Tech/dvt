from ..domain.entities import User as UserEntity
from .db_models import UserRecord as UserModel


def persisted_user_to_entity(model: UserModel) -> UserEntity:
    return UserEntity(
        id=model.id,
        role=model.role,
        organization_id=model.organization_id,
    )


def user_entity_to_persisted(entity: UserEntity) -> UserModel:
    return UserModel(
        id=entity.id,
        role=entity.role,
        organization_id=entity.organization_id,
    )


def update_persisted_user_from_entity(model: UserModel, entity: UserEntity) -> UserModel:
    model.role = entity.role
    model.organization_id = entity.organization_id
    return model
