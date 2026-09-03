from fastapi import APIRouter, Depends

import config as app_config

from .deps import set_user_log_context
from .routes import (
    admin,
    app_settings,
    cache,
    config,
    db_connections,
    exception_registry,
    extensions,
    logs,
    nodes,
    organization,
    project,
    public,
    queue,
    queue_topic,
    setup,
    storage,
    store,
    system,
    user,
    utils,
    websocket,
)
from .routes.installation import update

router = APIRouter()

GLOBAL_DEPS = [Depends(set_user_log_context)]

router.include_router(websocket.router)
router.include_router(system.router)
router.include_router(queue.router)
router.include_router(queue_topic.router)
router.include_router(update.router)
router.include_router(nodes.router)
router.include_router(logs.router)
router.include_router(organization.router)
router.include_router(project.router, dependencies=GLOBAL_DEPS)
router.include_router(db_connections.router)
router.include_router(utils.router)
router.include_router(storage.router, dependencies=GLOBAL_DEPS)
router.include_router(public.router, dependencies=GLOBAL_DEPS)
router.include_router(admin.router)
router.include_router(user.router)
router.include_router(exception_registry.router)
router.include_router(cache.router)
router.include_router(config.router)
router.include_router(store.router)
router.include_router(app_settings.router)
router.include_router(setup.router)
router.include_router(extensions.router)

if app_config.AI_MCP.ENABLED:
    from .routes.internal.ai_mcp.router import router as ai_mcp_internal_router
    from .routes.mcp_tokens import router as mcp_tokens_router

    router.include_router(mcp_tokens_router)
    router.include_router(ai_mcp_internal_router)


if app_config.COMMON.ENVIRONMENT == "dev":
    from .routes.pytest_mon import PytestMonitorRouter

    pytest_mon_router = PytestMonitorRouter(tests_root=app_config.PROJECT.TESTS_DIR)
    router.include_router(pytest_mon_router)
