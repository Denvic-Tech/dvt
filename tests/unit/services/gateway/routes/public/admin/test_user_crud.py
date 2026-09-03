from __future__ import annotations

import pytest
from fastapi import status
from usrak.core.dependencies.user import get_optional_user_any

from services.gateway.routes.public.admin.user import crud as public_admin_crud

from src.enums import DVTDefaultRoles
from src.modules.user.infra.db_models import UserRecord


@pytest.fixture
def set_current_admin_user(gateway_client):
    from services.gateway.main import app

    def _set(user: UserRecord) -> None:
        app.dependency_overrides[get_optional_user_any] = lambda: user
        app.dependency_overrides[public_admin_crud._get_user] = lambda: user

    return _set



@pytest.mark.asyncio
async def test_get_user_by_id_success_as_superadmin(
    gateway_client,
    router_prefix,
    set_current_admin_user,
    test_admin_user, 
    db_session
):
    """Тест успешного получения пользователя по ID супер-администратором"""
    set_current_admin_user(test_admin_user)

    response = await gateway_client.get(f"{router_prefix}/public/admin/users/{test_admin_user.id}")
    
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_get_user_by_id_not_found(
    gateway_client,
    router_prefix,
    set_current_admin_user,
    test_admin_user,
    db_session,
):
    """Тест получения несуществующего пользователя"""
    set_current_admin_user(test_admin_user)
        
    response = await gateway_client.get(f"{router_prefix}/public/admin/users/non-existent")
    
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_get_users_success(
    gateway_client,
    router_prefix,
    set_current_admin_user,
    test_admin_user,
    db_session,
):
    """Тест успешного получения списка пользователей с пагинацией"""
    set_current_admin_user(test_admin_user)
        
    response = await gateway_client.get(
        f"{router_prefix}/public/admin/users",
        params={"page": 2, "limit": 10, "email_contains": "test"}
    )
    
    assert response.status_code == status.HTTP_200_OK
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_get_users_with_default_params(
    gateway_client,
    router_prefix,
    set_current_admin_user,
    test_admin_user,
    db_session,
):
    """Тест получения списка пользователей с параметрами по умолчанию"""
    set_current_admin_user(test_admin_user)
        
    response = await gateway_client.get(f"{router_prefix}/public/admin/users")
    
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_get_users_empty_list(
    gateway_client,
    router_prefix,
    set_current_admin_user,
    test_admin_user,
    db_session,
):
    """Тест получения пустого списка пользователей"""
    set_current_admin_user(test_admin_user)

    response = await gateway_client.get(f"{router_prefix}/public/admin/users")
    
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_create_user_success(
    gateway_client,
    router_prefix,
    set_current_admin_user,
    test_admin_user,
    db_session,
):
    """Тест успешного создания пользователя"""
    set_current_admin_user(test_admin_user)
    
    create_data = {
        "email": "newuser@example.com",
        "password": "SecurePass123!",
        "role": DVTDefaultRoles.USER.value,
        "organization_id": "org-123",
        "user_name": "newuser"
    }
        
    response = await gateway_client.post(
        f"{router_prefix}/public/admin/users",
        json=create_data
    )
    
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["success"] is True


@pytest.mark.asyncio
async def test_create_user_duplicate_email(
    gateway_client,
    router_prefix,
    set_current_admin_user,
    test_admin_user,
    db_session,
):
    """Тест создания пользователя с уже существующим email"""
    set_current_admin_user(test_admin_user)
    
    create_data = {
        "email": "existing@example.com",
        "password": "SecurePass123!",
        "role": DVTDefaultRoles.USER.value,
        "organization_id": "org-123",
        "user_name": "existinguser"
    }
 
    response = await gateway_client.post(
        f"{router_prefix}/public/admin/users",
        json=create_data
    )
    
    assert response.status_code == status.HTTP_200_OK

    create_data = {
        "email": "existing@example.com",
        "password": "SecurePass123!",
        "role": DVTDefaultRoles.USER.value,
        "organization_id": "org-123",
        "user_name": "existinguser"
    }

    response = await gateway_client.post(
        f"{router_prefix}/public/admin/users",
        json=create_data
    )

    assert response.status_code == status.HTTP_409_CONFLICT


@pytest.mark.asyncio
async def test_update_user_success(
    gateway_client,
    router_prefix,
    set_current_admin_user,
    test_admin_user,
    db_session,
):
    """Тест успешного обновления пользователя"""
    set_current_admin_user(test_admin_user)
    
    update_data = {
        "user_id": test_admin_user.id,
        "email": "updated@example.com",
        "role": DVTDefaultRoles.ADMIN.value,
        "is_active": False,
    }
    
    response = await gateway_client.patch(
        f"{router_prefix}/public/admin/users",
        json=update_data
    )
    
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["success"] is True


@pytest.mark.asyncio
async def test_update_user_not_found(
    gateway_client,
    router_prefix,
    set_current_admin_user,
    test_admin_user,
    db_session,
):
    """Тест обновления несуществующего пользователя"""
    set_current_admin_user(test_admin_user)
    
    update_data = {
        "user_id": "non-existent-id",
        "email": "updated@example.com",
    }

    response = await gateway_client.patch(
        f"{router_prefix}/public/admin/users",
        json=update_data
    )
    
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_update_user_self_role_demotion(
    gateway_client,
    router_prefix,
    set_current_admin_user,
    test_admin_user,
    db_session,
):
    """Тест обновления собственной роли (понижение прав)"""
    set_current_admin_user(test_admin_user)
    
    update_data = {
        "user_id": test_admin_user.id,
        "role": DVTDefaultRoles.USER.value,
    }

    response = await gateway_client.patch(
        f"{router_prefix}/public/admin/users",
        json=update_data
    )
    
    assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]


@pytest.mark.asyncio
async def test_delete_user_success(
    gateway_client,
    router_prefix,
    set_current_admin_user,
    test_admin_user,
    test_user,
    db_session,
):
    """Тест успешного удаления пользователя"""
    set_current_admin_user(test_admin_user)

    response = await gateway_client.delete(f"{router_prefix}/public/admin/users/{test_user.id}")
    
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["success"] is True



@pytest.mark.asyncio
async def test_delete_user_not_found(
    gateway_client,
    router_prefix,
    set_current_admin_user,
    test_admin_user,
    db_session,
):
    """Тест удаления несуществующего пользователя"""
    set_current_admin_user(test_admin_user)
        
    response = await gateway_client.delete(f"{router_prefix}/public/admin/users/non-existent")
        
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_delete_self_forbidden(
    gateway_client,
    router_prefix,
    set_current_admin_user,
    test_admin_user,
    db_session,
):
    """Тест попытки удаления самого себя"""
    set_current_admin_user(test_admin_user)
    
    response = await gateway_client.delete(f"{router_prefix}/public/admin/users/{test_admin_user.id}")
    
    assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]


@pytest.mark.asyncio
async def test_create_user_missing_required_fields(
    gateway_client,
    router_prefix,
    set_current_admin_user,
    test_admin_user,
    db_session,
):
    """Тест создания пользователя без обязательных полей"""
    set_current_admin_user(test_admin_user)
    
    invalid_data = {
        "email": "incomplete@example.com"
        # missing password, role, organization_id
    }
    
    response = await gateway_client.post(
        f"{router_prefix}/public/admin/users",
        json=invalid_data
    )
    
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_create_user_with_invalid_role(
    gateway_client,
    router_prefix,
    set_current_admin_user,
    test_admin_user,
    db_session,
):
    """Тест создания пользователя с невалидной ролью"""
    set_current_admin_user(test_admin_user)
    
    create_data = {
        "email": "newuser@example.com",
        "password": "SecurePass123!",
        "role": "invalid_role",
        "organization_id": "org-123",
    }
    
    response = await gateway_client.post(
        f"{router_prefix}/public/admin/users",
        json=create_data
    )
    
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_admin_access_denied_for_regular_user_on_all_endpoints(
    gateway_client,
    router_prefix,
    set_current_admin_user,
    mock_regular_user,
    db_session,
):
    """Тест запрета доступа обычному пользователю ко всем admin эндпоинтам"""
    set_current_admin_user(mock_regular_user)
    
    # Попытка получить список пользователей
    response1 = await gateway_client.get(f"{router_prefix}/public/admin/users")
    assert response1.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
    
    # Попытка создать пользователя
    response2 = await gateway_client.post(
        f"{router_prefix}/public/admin/users",
        json={
            "email": "test@example.com",
            "password": "pass",
            "role": "user",
            "organization_id": "org",
            "user_name": "test-user",
        }
    )
    assert response2.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
    
    # Попытка обновить пользователя
    response3 = await gateway_client.patch(
        f"{router_prefix}/public/admin/users",
        json={"user_id": "some-id", "email": "test@example.com"}
    )
    assert response3.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
    
    # Попытка удалить пользователя
    response4 = await gateway_client.delete(f"{router_prefix}/public/admin/users/some-id")
    assert response4.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
