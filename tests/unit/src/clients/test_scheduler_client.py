from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.clients.scheduler_client import SchedulerClient


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 404, 422, 503])
async def test_request_preserves_scheduler_http_error(status):
    response = MagicMock(status=status, content_type="application/json")
    response.json = AsyncMock(return_value={"detail": "scheduler error"})
    request = AsyncMock()
    request.__aenter__.return_value = response
    session = MagicMock(closed=False)
    session.request.return_value = request
    client = SchedulerClient(session=session)
    with pytest.raises(HTTPException) as error:
        await client._request("PATCH", "/projects/schedule/p", json={})
    assert error.value.status_code == status
    assert error.value.detail == "scheduler error"
