"""
Основной файл FastAPI приложения для ETL шлюза.
Инициализирует приложение и подключает все роутеры.
"""

import asyncio
import copy
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from src.db import async_engine
from src.exception_registry.handlers import exception_handler
from src.extensions.gateway_runtime import get_extension_gateway_runtime
from src.logger import logger
from src.modules.db_connection import build_db_connection_extension
from src.modules.user.infra.fastapi.dependencies import get_user_access_only
from src.utils.openapi import rebuild_openapi
from src.version import get_version_from_pyproject

import config

from .auth_app import create_auth_app
from .lifespan import lifespan
from .main_router import router as main_router
from .metrics import get_metrics_cache, install_metrics_exporter
from .openapi import included_models
from .update_runtime import get_system_state_monitor
from .update_runtime.middleware import SystemUpdateMiddleware

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

install_metrics_exporter(get_metrics_cache())


class ExceptionLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            return await call_next(request)

        except Exception:
            logger.exception(f"Unhandled exception during request: {request.method} {request.url}")
            raise


app = FastAPI(
    title="DVT Gateway",
    description="API шлюз для DVT.",
    version=get_version_from_pyproject(),
    root_path="/api",
    lifespan=lifespan
)

app.add_exception_handler(Exception, exception_handler)
app.add_exception_handler(HTTPException, exception_handler)

app.add_middleware(ExceptionLoggingMiddleware)
app.add_middleware(
    SystemUpdateMiddleware,
    monitor=get_system_state_monitor(),
)

origins = config.GATEWAY.GATEWAY_ORIGINS[:]
origins.append("http://localhost:81")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # TODO: Настроить для безопасности в production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["retry-after", "cool-down", "X-Language"],
)

Instrumentator().instrument(app).expose(app, tags=["Metrics"])

app.include_router(main_router)

auth_app = create_auth_app()
app.mount(path="/auth", app=auth_app)
app.mount(
    path="/extensions",
    app=get_extension_gateway_runtime(),
    name="extension-runtime",
)


app = rebuild_openapi(app, include_models=included_models)
_core_openapi_schema = copy.deepcopy(app.openapi())


def _runtime_openapi():
    return get_extension_gateway_runtime().merge_openapi(_core_openapi_schema)


app.openapi = _runtime_openapi


@app.get("/openapi-core.json", include_in_schema=False)
async def core_openapi():
    return _core_openapi_schema


@app.api_route('/health', methods=['GET', 'HEAD'], include_in_schema=False)
async def health():
    return {"status": "ok"}


# --- Запуск Uvicorn (остается для запуска шлюза) ---
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "services.gateway.main:app",
        host=config.GATEWAY.GATEWAY_HOST,
        port=config.GATEWAY.GATEWAY_PORT,
        log_level=logger.level(config.LOGGING.LOG_LEVEL).no
    )
