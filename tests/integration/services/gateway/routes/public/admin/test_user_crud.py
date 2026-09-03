import httpx
import pytest
from typing import Any, Generator
from uuid import uuid4

from src.enums import DVTDefaultRoles
from src.modules.user.infra.db_models import UserRecord

pytestmark = [pytest.mark.asyncio, pytest.mark.docker_required]


@pytest.fixture
async def auth_client(
    gateway_live_client: httpx.AsyncClient,
) -> Generator[httpx.AsyncClient, None, None]:
    yield gateway_live_client


@pytest.fixture
async def regular_user_auth_client(
        gateway_live_base_url: str,
        auth_client: httpx.AsyncClient,
) -> Generator[httpx.AsyncClient, Any, None]:
    """Создает HTTP клиент с авторизацией обычного пользователя."""
    org_response = await auth_client.get("/api/public/organizations")
    orgs = org_response.json()
    org_id = orgs[0]["id"]

    regular_user_email = f"user_{uuid4().hex[:8]}@example.com"
    regular_user_password = "RegularUser123"
    user_data = {
        "email": regular_user_email,
        "user_name": f"regular_{uuid4().hex[:8]}",
        "password": regular_user_password,
        "role": DVTDefaultRoles.USER.value,
        "organization_id": org_id,
    }

    create_response = await auth_client.post("/api/public/admin/users", json=user_data)
    assert create_response.status_code == 200, f"Failed to create regular user: {create_response.text}"

    users_response = await auth_client.get("/api/public/admin/users")
    users = users_response.json()
    created_user = next(u for u in users if u["email"] == regular_user_email)
    user_id = created_user["id"]

    async with httpx.AsyncClient(base_url=gateway_live_base_url, timeout=30.0) as client:
        login_data = {
            "auth_provider": "email",
            "email": regular_user_email,
            "password": regular_user_password,
        }

        response = await client.post("/api/auth/sign-in", json=login_data)
        assert response.status_code == 200, f"Regular user login failed: {response.text}"

        client.cookies.update(response.cookies)
        response_data = response.json()
        if "access_token" in response_data:
            client.headers["Authorization"] = f"Bearer {response_data['access_token']}"

        yield client

    await auth_client.delete(f"/api/public/admin/users/{user_id}")


class TestAdminUserRoutes:
    """Интеграционные тесты для админских эндпоинтов управления пользователями"""

    async def test_get_users_list_success(
            self,
            auth_client: httpx.AsyncClient,
            test_admin_user: UserRecord,
            test_user: UserRecord,
    ):
        """Тест получения списка пользователей"""
        response = await auth_client.get("/api/public/admin/users")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1  # как минимум setup-созданный суперадмин

    async def test_get_users_list_with_pagination(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест пагинации при получении списка пользователей"""
        response = await auth_client.get("/api/public/admin/users", params={"page": 1, "limit": 1})

        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 1

    async def test_create_user_success(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест успешного создания пользователя"""
        # Получаем список организаций
        org_response = await auth_client.get("/api/public/organizations")
        assert org_response.status_code == 200
        orgs = org_response.json()
        assert len(orgs) > 0
        org_id = orgs[0]["id"]

        new_user_data = {
            "email": f"new_test_user_{uuid4().hex[:8]}@email.com",
            "user_name": "new_test_user",
            "password": "NewUser123",
            "role": DVTDefaultRoles.USER.value,
            "organization_id": org_id,
        }

        response = await auth_client.post("/api/public/admin/users", json=new_user_data)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Проверяем, что пользователь действительно создан
        get_response = await auth_client.get("/api/public/admin/users")
        users = get_response.json()
        created_user = next(
            (u for u in users if u["email"] == new_user_data["email"]),
            None
        )
        assert created_user is not None
        assert created_user["email"] == new_user_data["email"]

        # Удаляем созданного пользователя
        await auth_client.delete(f"/api/public/admin/users/{created_user['id']}")

    async def test_create_user_duplicate_email(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест создания пользователя с уже существующим email"""
        # Получаем первый существующий email
        users_response = await auth_client.get("/api/public/admin/users")
        users = users_response.json()
        existing_email = users[0]["email"]

        org_response = await auth_client.get("/api/public/organizations")
        orgs = org_response.json()
        org_id = orgs[0]["id"]

        new_user_data = {
            "email": existing_email,
            "user_name": "duplicate_user",
            "password": "Duplicate123",
            "role": DVTDefaultRoles.USER.value,
            "organization_id": org_id,
        }

        response = await auth_client.post("/api/public/admin/users", json=new_user_data)

        assert response.status_code in [400, 409]

    async def test_update_user_success(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест успешного обновления пользователя"""
        # Создаем временного пользователя
        org_response = await auth_client.get("/api/public/organizations")
        orgs = org_response.json()
        org_id = orgs[0]["id"]

        new_user_data = {
            "email": f"update_test_{uuid4().hex[:8]}@email.com",
            "user_name": "update_test_user",
            "password": "Update123",
            "role": DVTDefaultRoles.USER.value,
            "organization_id": org_id,
        }

        create_response = await auth_client.post("/api/public/admin/users", json=new_user_data)
        assert create_response.status_code == 200

        # Получаем ID созданного пользователя
        users_response = await auth_client.get("/api/public/admin/users")
        users = users_response.json()
        created_user = next(u for u in users if u["email"] == new_user_data["email"])

        # Обновляем пользователя
        update_data = {
            "user_id": created_user["id"],
            "email": f"updated_{new_user_data['email']}",
            "user_name": "updated_username",
        }

        response = await auth_client.patch("/api/public/admin/users", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Проверяем обновление
        get_response = await auth_client.get(f"/api/public/admin/users/{created_user['id']}")
        updated_user = get_response.json()
        # ошибка возникает тут 'update_test_21dd0663@email.com' == 'updated_update_test_21dd0663@email.com'
        assert updated_user["email"] == update_data["email"]
        assert updated_user["user_name"] == update_data["user_name"]

        # Удаляем пользователя
        await auth_client.delete(f"/api/public/admin/users/{created_user['id']}")

    async def test_update_user_not_found(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест обновления несуществующего пользователя"""
        fake_id = str(uuid4())
        update_data = {
            "user_id": fake_id,
            "email": "nonexistent@email.com",
        }

        response = await auth_client.patch("/api/public/admin/users", json=update_data)

        assert response.status_code == 404

    async def test_delete_user_success(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест успешного удаления пользователя"""
        # Создаем временного пользователя
        org_response = await auth_client.get("/api/public/organizations")
        orgs = org_response.json()
        org_id = orgs[0]["id"]

        new_user_data = {
            "email": f"delete_test_{uuid4().hex[:8]}@email.com",
            "user_name": "delete_test_user",
            "password": "Delete123",
            "role": DVTDefaultRoles.USER.value,
            "organization_id": org_id,
        }

        create_response = await auth_client.post("/api/public/admin/users", json=new_user_data)
        assert create_response.status_code == 200

        # Получаем ID созданного пользователя
        users_response = await auth_client.get("/api/public/admin/users")
        users = users_response.json()
        created_user = next(u for u in users if u["email"] == new_user_data["email"])

        # Удаляем пользователя
        response = await auth_client.delete(f"/api/public/admin/users/{created_user['id']}")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Админ по-прежнему видит пользователя после soft-delete, но как неактивного
        get_response = await auth_client.get(f"/api/public/admin/users/{created_user['id']}")
        assert get_response.status_code == 200
        deleted_user = get_response.json()
        assert deleted_user["id"] == created_user["id"]
        assert deleted_user["is_active"] is False

    async def test_delete_user_not_found(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест удаления несуществующего пользователя"""
        fake_id = str(uuid4())
        response = await auth_client.delete(f"/api/public/admin/users/{fake_id}")

        assert response.status_code == 404


class TestAdminUserRoutesAccessControl:
    """Тесты контроля доступа для админских эндпоинтов"""

    async def test_unauthorized_access(
            self,
            gateway_live_unauthenticated_client: httpx.AsyncClient,
    ):
        """Тест: неавторизованный доступ запрещен"""
        response = await gateway_live_unauthenticated_client.get("/api/public/admin/users")
        assert response.status_code in [401, 403]

    async def test_regular_user_cannot_access_admin_routes(
            self,
            regular_user_auth_client: httpx.AsyncClient,
    ):
        """Тест: обычный пользователь не может получить доступ к админским маршрутам"""
        response = await regular_user_auth_client.get("/api/public/admin/users")
        assert response.status_code in [401, 403]


class TestAdminUserRoutesEdgeCases:
    """Тесты граничных случаев для админских эндпоинтов"""

    async def test_create_user_with_invalid_email(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест создания пользователя с некорректным email"""
        org_response = await auth_client.get("/api/public/organizations")
        orgs = org_response.json()
        org_id = orgs[0]["id"]

        invalid_user_data = {
            "email": "not_an_email",
            "user_name": "invalid_email_user",
            "password": "Invalid123",
            "role": DVTDefaultRoles.USER.value,
            "organization_id": org_id,
        }

        response = await auth_client.post("/api/public/admin/users", json=invalid_user_data)

        # Ожидаем ошибку валидации
        assert response.status_code == 422

    async def test_get_users_list_empty_page(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест получения пустой страницы (слишком большой номер страницы)"""
        response = await auth_client.get("/api/public/admin/users", params={"page": 999, "limit": 30})

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0
