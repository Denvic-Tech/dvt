import asyncio
import os
import sys

os.environ["SERVICE_NAME"] = "project-scheduler"

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if __name__ == '__main__':
    import uvicorn

    from services.project_scheduler.main import app
    import config

    uvicorn.run(app, host=config.PROJECT_SCHEDULER.PROJECT_SCHEDULER_HOST,
                port=config.PROJECT_SCHEDULER.PROJECT_SCHEDULER_PORT)
