from __future__ import annotations

import pytest
from fastapi import status
from usrak.core.dependencies.user import get_optional_user_any

from services.gateway.routes.organization import crud as organization_crud
from services.gateway.routes.public.organization import crud as public_organization_crud

from src.modules.user.infra.db_models import UserRecord
from src.modules.user.infra.fastapi.dependencies import get_user_access_only


@pytest.fixture
def set_current_user(gateway_client):
    from services.gateway.main import app

    def _set(user: UserRecord) -> None:
        app.dependency_overrides[get_user_access_only] = lambda: user
        app.dependency_overrides[get_optional_user_any] = lambda: user
        app.dependency_overrides[organization_crud._get_user] = lambda: user
        app.dependency_overrides[public_organization_crud._get_user] = lambda: user

    return _set


@pytest.mark.asyncio
async def test_get_organizations_success(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
):
    """Тест успешного получения списка организаций"""
    set_current_user(test_admin_user)
        
    response = await gateway_client.get(f"{router_prefix}/public/organizations")
    
    assert response.status_code == status.HTTP_200_OK
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_get_organization_success(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    test_organization
):
    """Тест успешного получения организации по ID"""
    set_current_user(test_admin_user)
        
    response = await gateway_client.get(f"{router_prefix}/public/organizations/{test_organization.id}")     
    assert response.status_code == status.HTTP_200_OK
    

@pytest.mark.asyncio
async def test_get_organization_not_found(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
):
    """Тест получения несуществующей организации"""
    set_current_user(test_admin_user)
    
    response = await gateway_client.get(f"{router_prefix}/public/organizations/non-existent")
    
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_create_organization_success(
    gateway_client,
    router_prefix,
    set_current_user,
    test_superadmin_user,
):
    """Тест успешного создания организации (только супер-админ)"""
    set_current_user(test_superadmin_user)
    
    create_data = {
        "name": "New Organization",
        "description": "New Description",
        "inn": "9876543210",
        "is_active": True,
    }
    
    response = await gateway_client.post(
        f"{router_prefix}/public/organizations",
        json=create_data
    )
    
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_create_organization_forbidden_for_user(
    gateway_client,
    router_prefix,
    set_current_user,
    test_user,
):
    """Тест создания организации обычным пользователем (должно быть запрещено)"""
    set_current_user(test_user)
    
    create_data = {
        "name": "New Organization",
        "description": "New Description",
        "inn": "9876543210",
        "is_active": True,
    }
    
    response = await gateway_client.post(
        f"{router_prefix}/public/organizations",
        json=create_data
    )
    
    assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]


@pytest.mark.asyncio
async def test_update_organization_success(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
    test_organization
):
    """Тест успешного обновления организации"""
    set_current_user(test_admin_user)
    
    update_data = {
        "name": "Updated Organization",
        "description": "Updated Description",
    }
    
        
    response = await gateway_client.patch(
        f"{router_prefix}/public/organizations/{test_organization.id}",
        json=update_data
    )

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_update_organization_not_found(
    gateway_client,
    router_prefix,
    set_current_user,
    test_admin_user,
):
    """Тест обновления несуществующей организации"""
    set_current_user(test_admin_user)
    
    update_data = {"name": "Updated Organization"}
    
    response = await gateway_client.patch(
        f"{router_prefix}/public/organizations/non-existent",
        json=update_data
    )
    
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_update_organization_forbidden(
    gateway_client,
    router_prefix,
    set_current_user,
    test_user,
    test_organization
):
    """Тест обновления организации без прав"""
    set_current_user(test_user)
    
    update_data = {"name": "Updated Organization"}

    response = await gateway_client.patch(
        f"{router_prefix}/public/organizations/{test_organization.id}",
        json=update_data
    )
    
    assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]


@pytest.mark.asyncio
async def test_delete_organization_success(
    gateway_client,
    router_prefix,
    set_current_user,
    test_superadmin_user,
    test_delete_organization
):
    """Тест успешного удаления организации"""
    set_current_user(test_superadmin_user)
    
    response = await gateway_client.delete(f"{router_prefix}/public/organizations/{test_delete_organization.id}")
    
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_delete_organization_not_found(
    gateway_client,
    router_prefix,
    set_current_user,
    test_superadmin_user,
):
    """Тест удаления несуществующей организации"""
    set_current_user(test_superadmin_user)
    
    response = await gateway_client.delete(f"{router_prefix}/public/organizations/non-existent")
    
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_delete_organization_forbidden(
    gateway_client,
    router_prefix,
    set_current_user,
    test_user,
    test_organization
):
    """Тест удаления организации без прав (только супер-админ)"""
    set_current_user(test_user)
    
    response = await gateway_client.delete(f"{router_prefix}/public/organizations/{test_organization.id}")
    
    assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]


@pytest.mark.asyncio
async def test_create_organization_without_required_fields(
    gateway_client,
    router_prefix,
    set_current_user,
    test_superadmin_user,
):
    """Тест создания организации без обязательных полей"""
    set_current_user(test_superadmin_user)
    
    invalid_data = {
        "description": "Missing name and inn"
    }
    
    response = await gateway_client.post(
        f"{router_prefix}/public/organizations",
        json=invalid_data
    )
    
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_create_organization_with_invalid_inn(
    gateway_client,
    router_prefix,
    set_current_user,
    test_superadmin_user
):
    """Тест создания организации с невалидным ИНН"""
    set_current_user(test_superadmin_user)

    response = await gateway_client.post(
        f"{router_prefix}/public/organizations",
        json={
            "name": "Test Org",
            "inn": "invalid",
            "is_active": True
        }
    )
    
    assert response.status_code == status.HTTP_400_BAD_REQUEST