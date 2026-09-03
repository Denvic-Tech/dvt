import os
import sys
import asyncio

os.environ["SERVICE_NAME"] = "orchestrator"
os.environ["LOG_TO_WS"] = "true"
os.environ["LOG_TO_DB"] = "false"
os.environ["INTERCEPT_STANDARD_LOGGING"] = "true"
# os.environ["GRPC_VERBOSITY"] = "debug"
# os.environ["GRPC_TRACE"] = "tcp,api"


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


if __name__ == '__main__':
    from services.orchestrator.main import serve
    asyncio.run(serve())
