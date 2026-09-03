import uvicorn

from services.dvt_ai_mcp.settings import settings

if __name__ == "__main__":
    uvicorn.run(
        "services.dvt_ai_mcp.server:app",
        host=settings.host,
        port=settings.port,
        workers=1,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
