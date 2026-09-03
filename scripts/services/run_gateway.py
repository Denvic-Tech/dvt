import os
import sys
import asyncio
import uvicorn

os.environ["SERVICE_NAME"] = "gateway"
# os.environ["GRPC_VERBOSITY"] = "debug"
# os.environ["GRPC_TRACE"] = "tcp,api"

import config


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


if __name__ == '__main__':
    uvicorn.run("services.gateway.main:app", host=config.GATEWAY.GATEWAY_HOST, port=config.GATEWAY.GATEWAY_PORT)
