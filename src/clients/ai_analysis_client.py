from __future__ import annotations

import httpx
from pydantic import BaseModel, ValidationError

import config
from src.schemas.http.ai_analysis_service import (
    AIServiceAnalysisRequestBatchReadSchema,
    AIServiceAnalysisRequestReadSchema,
    AIServiceLogErrorAnalysisCreateResponseSchema,
    AIServiceLogErrorAnalysisCreateSchema,
)


class AIAnalysisClient:
    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if config.AI_ANALYSIS.SERVICE_API_KEY:
            headers["Authorization"] = f"Bearer {config.AI_ANALYSIS.SERVICE_API_KEY}"
        return headers

    def _raise_for_response(self, response: httpx.Response, *, action: str) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text.strip()
            details = f": {body}" if body else ""
            raise RuntimeError(
                f"AI service {action} failed with status {exc.response.status_code}{details}"
            ) from exc

    def _parse_response_model[TModel: BaseModel](
        self,
        response: httpx.Response,
        *,
        action: str,
        schema: type[TModel],
    ) -> TModel:
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"AI service {action} returned invalid JSON") from exc

        try:
            return schema.model_validate(payload)
        except ValidationError as exc:
            raise RuntimeError(f"AI service {action} returned invalid payload: {exc}") from exc

    async def create_request(
        self,
        payload: AIServiceLogErrorAnalysisCreateSchema,
    ) -> AIServiceLogErrorAnalysisCreateResponseSchema:
        url = f"{config.AI_ANALYSIS.SERVICE_URL}/v1/analysis/log-error"
        async with httpx.AsyncClient(timeout=config.AI_ANALYSIS.REQUEST_TIMEOUT_SEC) as client:
            response = await client.post(
                url,
                headers=self._build_headers(),
                json=payload.model_dump(mode="json", by_alias=True),
            )
            self._raise_for_response(response, action="create request")
            return self._parse_response_model(
                response,
                action="create request",
                schema=AIServiceLogErrorAnalysisCreateResponseSchema,
            )

    async def get_request(self, remote_request_id: str) -> AIServiceAnalysisRequestReadSchema:
        url = f"{config.AI_ANALYSIS.SERVICE_URL}/v1/analysis/requests/{remote_request_id}"
        async with httpx.AsyncClient(timeout=config.AI_ANALYSIS.REQUEST_TIMEOUT_SEC) as client:
            response = await client.get(url, headers=self._build_headers())
            self._raise_for_response(response, action="poll request")
            return self._parse_response_model(
                response,
                action="poll request",
                schema=AIServiceAnalysisRequestReadSchema,
            )

    async def get_requests(
        self,
        remote_request_ids: list[str],
    ) -> AIServiceAnalysisRequestBatchReadSchema:
        normalized_request_ids = []
        for remote_request_id in remote_request_ids:
            request_id = str(remote_request_id).strip()
            if request_id and request_id not in normalized_request_ids:
                normalized_request_ids.append(request_id)

        if not normalized_request_ids:
            return AIServiceAnalysisRequestBatchReadSchema()

        url = f"{config.AI_ANALYSIS.SERVICE_URL}/v1/analysis/requests"
        params = [("request_id", request_id) for request_id in normalized_request_ids]
        async with httpx.AsyncClient(timeout=config.AI_ANALYSIS.REQUEST_TIMEOUT_SEC) as client:
            response = await client.get(url, headers=self._build_headers(), params=params)
            self._raise_for_response(response, action="poll requests")
            return self._parse_response_model(
                response,
                action="poll requests",
                schema=AIServiceAnalysisRequestBatchReadSchema,
            )


ai_analysis_client = AIAnalysisClient()


async def create_remote_analysis_request(
    payload: AIServiceLogErrorAnalysisCreateSchema,
) -> AIServiceLogErrorAnalysisCreateResponseSchema:
    return await ai_analysis_client.create_request(payload)


async def get_remote_analysis_request(remote_request_id: str) -> AIServiceAnalysisRequestReadSchema:
    return await ai_analysis_client.get_request(remote_request_id)


async def get_remote_analysis_requests(
    remote_request_ids: list[str],
) -> AIServiceAnalysisRequestBatchReadSchema:
    return await ai_analysis_client.get_requests(remote_request_ids)
