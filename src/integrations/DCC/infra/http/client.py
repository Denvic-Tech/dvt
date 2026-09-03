import httpx

class DCCHttpClient:
    def __init__(
        self,
        *,
        base_url: str,
        auth: httpx.BasicAuth,
        timeout: float = 10.0,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            auth=auth,
            timeout=httpx.Timeout(timeout=timeout),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def ping(self) -> httpx.Response:
        return await self._client.get("/ping")

    async def get(self, url: str, *, params: dict | None = None) -> httpx.Response:
        return await self._client.get(url, params=params)

    async def post(self, url: str, *, json: dict | list | None = None) -> httpx.Response:
        return await self._client.post(url, json=json)

    async def delete(self, url: str, *, params: dict | None = None) -> httpx.Response:
        return await self._client.delete(url, params=params)

    async def __aenter__(self) -> "DCCHttpClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()
