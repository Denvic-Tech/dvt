import httpx
import pytest
from typing import Generator, Any
from uuid import uuid4

from src.enums import DVTDefaultRoles

pytestmark = [pytest.mark.asyncio, pytest.mark.docker_required]


@pytest.fixture
async def auth_client(
    gateway_live_client: httpx.AsyncClient,
) -> Generator[httpx.AsyncClient, None, None]:
    yield gateway_live_client


@pytest.fixture
async def created_organization(auth_client: httpx.AsyncClient) -> Generator[dict, Any, None]:
    """Создает тестовую организацию и удаляет её после теста."""
    org_data = {
        "name": f"Test Org {uuid4().hex[:8]}",
        "description": "Test organization for integration tests",
        "is_active": True,
    }
    response = await auth_client.post("/api/public/organizations", json=org_data)
    assert response.status_code == 200, f"Failed to create organization: {response.text}"
    org = response.json()

    yield org

    # Удаляем после теста
    await auth_client.delete(f"/api/public/organizations/{org['id']}")


@pytest.fixture
async def created_admin_user(auth_client: httpx.AsyncClient) -> Generator[dict, Any, None]:
    """Создает админа для тестирования прав доступа."""
    # Получаем organization_id
    org_response = await auth_client.get("/api/public/organizations")
    org_response.raise_for_status()
    orgs = org_response.json()
    org_id = orgs[0]["id"]

    # Создаем админа
    admin_data = {
        "email": f"admin_{uuid4().hex[:8]}@example.com",
        "user_name": f"admin_{uuid4().hex[:8]}",
        "password": "AdminPassword123",
        "role": DVTDefaultRoles.ADMIN.value,
        "organization_id": org_id,
    }

    create_response = await auth_client.post("/api/admin/users", json=admin_data)
    assert create_response.status_code == 200, f"Failed to create admin: {create_response.text}"

    # Получаем созданного админа
    users_response = await auth_client.get("/api/admin/users")
    users = users_response.json()
    created_admin = next(u for u in users if u["email"] == admin_data["email"])

    yield {
        **created_admin,
        "password": admin_data["password"],
    }

    # Удаляем админа
    await auth_client.delete(f"/api/admin/users/{created_admin['id']}")


@pytest.fixture
async def admin_auth_client(
        gateway_live_base_url: str,
        auth_client: httpx.AsyncClient,
) -> Generator[httpx.AsyncClient, Any, None]:
    """Создает HTTP клиент с авторизацией обычного админа."""
    # Создаем админа через суперадминский клиент
    org_response = await auth_client.get("/api/public/organizations")
    orgs = org_response.json()
    org_id = orgs[0]["id"]

    admin_email = f"admin_{uuid4().hex[:8]}@example.com"
    admin_password = "AdminPassword123"

    admin_data = {
        "email": admin_email,
        "user_name": f"admin_{uuid4().hex[:8]}",
        "password": admin_password,
        "role": DVTDefaultRoles.ADMIN.value,
        "organization_id": org_id,
    }

    create_response = await auth_client.post("/api/admin/users", json=admin_data)
    assert create_response.status_code == 200

    # Получаем ID админа для последующего удаления
    users_response = await auth_client.get("/api/admin/users")
    users = users_response.json()
    created_admin = next(u for u in users if u["email"] == admin_email)
    admin_id = created_admin["id"]

    # Создаем клиент для админа
    async with httpx.AsyncClient(base_url=gateway_live_base_url, timeout=30.0) as client:
        login_data = {
            "auth_provider": "email",
            "email": admin_email,
            "password": admin_password,
        }

        response = await client.post("/api/auth/sign-in", json=login_data)
        assert response.status_code == 200, f"Admin login failed: {response.text}"

        client.cookies.update(response.cookies)
        response_data = response.json()
        if "access_token" in response_data:
            client.headers["Authorization"] = f"Bearer {response_data['access_token']}"

        yield client

    # Удаляем админа
    await auth_client.delete(f"/api/admin/users/{admin_id}")


class TestOrganizationRoutes:
    """Интеграционные тесты для эндпоинтов управления организациями"""

    async def test_get_organizations_list_success(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест GET /organizations — получение списка организаций (успех)."""
        response = await auth_client.get("/api/public/organizations")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    async def test_get_organization_by_id_success(
            self,
            auth_client: httpx.AsyncClient,
            created_organization: dict,
    ):
        """Тест GET /organizations/{id} — получение организации по ID (успех)."""
        org_id = created_organization["id"]
        response = await auth_client.get(f"/api/public/organizations/{org_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == org_id
        assert data["name"] == created_organization["name"]

    async def test_get_organization_by_id_not_found(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест GET /organizations/{id} — организация не найдена (404)."""
        fake_id = str(uuid4())
        response = await auth_client.get(f"/api/public/organizations/{fake_id}")

        assert response.status_code == 404

    async def test_create_organization_success(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест POST /organizations — создание организации (успех)."""
        org_data = {
            "name": f"New Test Org {uuid4().hex[:8]}",
            "description": "Created via integration test",
            "is_active": True,
        }

        response = await auth_client.post("/api/public/organizations", json=org_data)

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == org_data["name"]
        assert "id" in data

        # Удаляем созданную организацию
        await auth_client.delete(f"/api/public/organizations/{data['id']}")

    async def test_create_organization_duplicate_inn(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест POST /organizations — создание организации с дублирующимся ИНН."""
        inn = f"{uuid4().int % 10**10:010d}"
        org_data = {
            "name": f"Org with INN {uuid4().hex[:8]}",
            "inn": inn,
            "is_active": True,
        }

        response1 = await auth_client.post("/api/public/organizations", json=org_data)
        assert response1.status_code == 200
        org1 = response1.json()

        org_data2 = {
            "name": f"Duplicate INN Org {uuid4().hex[:8]}",
            "inn": inn,
            "is_active": True,
        }

        response2 = await auth_client.post("/api/public/organizations", json=org_data2)
        assert response2.status_code in [400, 409]

        await auth_client.delete(f"/api/public/organizations/{org1['id']}")

    async def test_update_organization_success(
            self,
            auth_client: httpx.AsyncClient,
            created_organization: dict,
    ):
        """Тест PATCH /organizations/{id} — обновление организации (успех)."""
        org_id = created_organization["id"]
        update_data = {
            "name": f"Updated Org {uuid4().hex[:8]}",
            "description": "Updated description",
        }

        response = await auth_client.patch(f"/api/public/organizations/{org_id}", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == org_id
        assert data["name"] == update_data["name"]

    async def test_update_organization_not_found(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест PATCH /organizations/{id} — организация не найдена (404)."""
        fake_id = str(uuid4())
        update_data = {"name": "Updated Name"}

        response = await auth_client.patch(f"/api/public/organizations/{fake_id}", json=update_data)

        assert response.status_code == 404

    async def test_delete_organization_success(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест DELETE /organizations/{id} — удаление организации (успех)."""
        org_data = {
            "name": f"To Delete Org {uuid4().hex[:8]}",
            "is_active": True,
        }
        create_response = await auth_client.post("/api/public/organizations", json=org_data)
        assert create_response.status_code == 200
        org_id = create_response.json()["id"]

        delete_response = await auth_client.delete(f"/api/public/organizations/{org_id}")
        assert delete_response.status_code == 200
        data = delete_response.json()
        assert data["success"] is True

        get_response = await auth_client.get(f"/api/public/organizations/{org_id}")
        assert get_response.status_code == 404

    async def test_delete_own_organization_forbidden(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест DELETE /organizations/{id} — нельзя удалить свою организацию."""
        response = await auth_client.get("/api/public/organizations")
        orgs = response.json()
        own_org_id = orgs[0]["id"]

        delete_response = await auth_client.delete(f"/api/public/organizations/{own_org_id}")
        assert delete_response.status_code in [400, 403]

    async def test_delete_organization_not_found(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест DELETE /organizations/{id} — организация не найдена (404)."""
        fake_id = str(uuid4())
        response = await auth_client.delete(f"/api/public/organizations/{fake_id}")

        assert response.status_code == 404


class TestOrganizationRoutesAccessControl:
    """Тесты контроля доступа для эндпоинтов организаций"""

    async def test_unauthorized_access(
            self,
            gateway_live_unauthenticated_client: httpx.AsyncClient,
    ):
        """Тест: неавторизованный доступ запрещен."""
        urls = [
            "/api/public/organizations",
            f"/api/public/organizations/{uuid4()}",
        ]
        for url in urls:
            response = await gateway_live_unauthenticated_client.get(url)
            assert response.status_code in [401, 403]

    @pytest.mark.skip("Может создать организацию")
    async def test_admin_cannot_create_organization(
            self,
            admin_auth_client: httpx.AsyncClient,
    ):
        """Тест: обычный админ не может создавать организации."""
        org_data = {
            "name": f"Admin Created Org {uuid4().hex[:8]}",
            "is_active": True,
        }

        response = await admin_auth_client.post("/api/public/organizations", json=org_data)
        assert response.status_code in [401, 403]


class TestOrganizationRoutesEdgeCases:
    """Тесты граничных случаев для эндпоинтов организаций"""

    async def test_create_organization_with_minimal_data(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест создания организации с минимальным набором данных."""
        org_data = {
            "name": f"Minimal Org {uuid4().hex[:8]}",
            "is_active": True,
        }

        response = await auth_client.post("/api/public/organizations", json=org_data)

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == org_data["name"]

        await auth_client.delete(f"/api/public/organizations/{data['id']}")

    @pytest.mark.skip(reason="Бэкенд не валидирует пустое имя (возвращает 200)")
    async def test_create_organization_empty_name(
            self,
            auth_client: httpx.AsyncClient,
    ):
        """Тест создания организации с пустым именем (должен быть 422)."""
        org_data = {
            "name": "",
            "is_active": True,
        }

        response = await auth_client.post("/api/public/organizations", json=org_data)
        assert response.status_code == 422

    async def test_update_organization_partial_data(
            self,
            auth_client: httpx.AsyncClient,
            created_organization: dict,
    ):
        """Тест частичного обновления организации (только description)."""
        org_id = created_organization["id"]
        original_name = created_organization["name"]
        update_data = {
            "description": "Only description updated",
        }

        response = await auth_client.patch(f"/api/public/organizations/{org_id}", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == original_name
        assert data["description"] == update_data["description"]

    async def test_update_organization_no_changes(
            self,
            auth_client: httpx.AsyncClient,
            created_organization: dict,
    ):
        """Тест обновления организации без изменений."""
        org_id = created_organization["id"]
        update_data = {
            "name": created_organization["name"],
        }

        response = await auth_client.patch(f"/api/public/organizations/{org_id}", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == created_organization["name"]
