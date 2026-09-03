from __future__ import annotations

from .generated import models
from .resources.base import AsyncResourceBase, SyncResourceBase


class AsyncAuthApiTokensResource(AsyncResourceBase):
    async def list(self) -> models.ApiTokensListData | None:
        return await self._request_json(
            method="GET",
            path="/auth/api-tokens",
            response_type=models.ApiTokensListData | None,
            unwrap_data=True,
        )

    async def create(
        self,
        *,
        data: models.ApiTokenCreate | dict,
    ) -> models.ApiTokenCreatedData | None:
        return await self._request_json(
            method="POST",
            path="/auth/api-tokens",
            data=data,
            response_type=models.ApiTokenCreatedData | None,
            unwrap_data=True,
        )

    async def delete(self, *, token_identifier: str) -> models.ApiTokenEmptyData | None:
        return await self._request_json(
            method="DELETE",
            path="/auth/api-tokens/{token_identifier}",
            path_params={"token_identifier": token_identifier},
            response_type=models.ApiTokenEmptyData | None,
            unwrap_data=True,
        )


class AsyncAuthAdminResource(AsyncResourceBase):
    users: AsyncAuthAdminUsersResource

    async def register_user(
        self,
        *,
        data: models.AdminUserCreate | dict,
    ) -> models.ManagedUserData | None:
        return await self._request_json(
            method="POST",
            path="/auth/admin/register_user",
            data=data,
            response_type=models.ManagedUserData | None,
            unwrap_data=True,
        )


class AsyncAuthAdminUsersResource(AsyncResourceBase):
    async def update(
        self,
        *,
        user_identifier: str,
        data: models.AdminUserUpdate | dict,
    ) -> models.ManagedUserData | None:
        return await self._request_json(
            method="PATCH",
            path="/auth/admin/users/{user_identifier}",
            path_params={"user_identifier": user_identifier},
            data=data,
            response_type=models.ManagedUserData | None,
            unwrap_data=True,
        )

    async def delete(self, *, user_identifier: str) -> models.CommonResponse:
        return await self._request_json(
            method="DELETE",
            path="/auth/admin/users/{user_identifier}",
            path_params={"user_identifier": user_identifier},
            response_type=models.CommonResponse,
        )


class AsyncAuthResource(AsyncResourceBase):
    api_tokens: AsyncAuthApiTokensResource
    admin: AsyncAuthAdminResource

    async def sign_in(
        self,
        *,
        username: str | None = None,
        password: str | None = None,
    ):
        return await self._transport.sign_in(username=username, password=password)

    async def profile(self) -> models.UserProfileData | None:
        return await self._request_json(
            method="GET",
            path="/auth/profile",
            response_type=models.UserProfileData | None,
            unwrap_data=True,
        )

    async def check_auth(self) -> models.AuthenticatedData | None:
        return await self._request_json(
            method="POST",
            path="/auth/check-auth",
            response_type=models.AuthenticatedData | None,
            unwrap_data=True,
        )

    async def refresh(self):
        return await self._request_json(
            method="POST",
            path="/auth/refresh",
            response_type=models.CommonResponse,
        )

    async def logout(self) -> models.CommonResponse:
        return await self._request_json(
            method="POST",
            path="/auth/logout",
            response_type=models.CommonResponse,
        )

class SyncAuthApiTokensResource(SyncResourceBase):
    def list(self) -> models.ApiTokensListData | None:
        return self._request_json(
            method="GET",
            path="/auth/api-tokens",
            response_type=models.ApiTokensListData | None,
            unwrap_data=True,
        )

    def create(
        self,
        *,
        data: models.ApiTokenCreate | dict,
    ) -> models.ApiTokenCreatedData | None:
        return self._request_json(
            method="POST",
            path="/auth/api-tokens",
            data=data,
            response_type=models.ApiTokenCreatedData | None,
            unwrap_data=True,
        )

    def delete(self, *, token_identifier: str) -> models.ApiTokenEmptyData | None:
        return self._request_json(
            method="DELETE",
            path="/auth/api-tokens/{token_identifier}",
            path_params={"token_identifier": token_identifier},
            response_type=models.ApiTokenEmptyData | None,
            unwrap_data=True,
        )


class SyncAuthAdminResource(SyncResourceBase):
    users: SyncAuthAdminUsersResource

    def register_user(
        self,
        *,
        data: models.AdminUserCreate | dict,
    ) -> models.ManagedUserData | None:
        return self._request_json(
            method="POST",
            path="/auth/admin/register_user",
            data=data,
            response_type=models.ManagedUserData | None,
            unwrap_data=True,
        )


class SyncAuthAdminUsersResource(SyncResourceBase):
    def update(
        self,
        *,
        user_identifier: str,
        data: models.AdminUserUpdate | dict,
    ) -> models.ManagedUserData | None:
        return self._request_json(
            method="PATCH",
            path="/auth/admin/users/{user_identifier}",
            path_params={"user_identifier": user_identifier},
            data=data,
            response_type=models.ManagedUserData | None,
            unwrap_data=True,
        )

    def delete(self, *, user_identifier: str) -> models.CommonResponse:
        return self._request_json(
            method="DELETE",
            path="/auth/admin/users/{user_identifier}",
            path_params={"user_identifier": user_identifier},
            response_type=models.CommonResponse,
        )


class SyncAuthResource(SyncResourceBase):
    api_tokens: SyncAuthApiTokensResource
    admin: SyncAuthAdminResource

    def sign_in(
        self,
        *,
        username: str | None = None,
        password: str | None = None,
    ):
        return self._transport.sign_in(username=username, password=password)

    def profile(self) -> models.UserProfileData | None:
        return self._request_json(
            method="GET",
            path="/auth/profile",
            response_type=models.UserProfileData | None,
            unwrap_data=True,
        )

    def check_auth(self) -> models.AuthenticatedData | None:
        return self._request_json(
            method="POST",
            path="/auth/check-auth",
            response_type=models.AuthenticatedData | None,
            unwrap_data=True,
        )

    def refresh(self):
        return self._request_json(
            method="POST",
            path="/auth/refresh",
            response_type=models.CommonResponse,
        )

    def logout(self) -> models.CommonResponse:
        return self._request_json(
            method="POST",
            path="/auth/logout",
            response_type=models.CommonResponse,
        )
