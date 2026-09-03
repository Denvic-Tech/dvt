import os
import sys
import asyncio
from pathlib import Path

import urllib3
import logging

def _bootstrap_project_path() -> None:
    project_root = Path(__file__).resolve().parents[2]
    project_root_str = str(project_root)

    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)

    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    path_entries = [entry for entry in existing_pythonpath.split(os.pathsep) if entry]
    if project_root_str not in path_entries:
        os.environ["PYTHONPATH"] = os.pathsep.join([project_root_str, *path_entries])

_bootstrap_project_path()

os.environ["SERVICE_NAME"] = "task-worker"

# os.environ["GRPC_VERBOSITY"] = "debug"
# os.environ["GRPC_TRACE"] = "tcp,api"

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class IgnoreWinError10035Filter(logging.Filter):
    def filter(self, record):
        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            if isinstance(exc_value, BlockingIOError) and exc_value.winerror == 10035:
                return False
        return True


logging.getLogger("asyncio").addFilter(IgnoreWinError10035Filter())


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


if __name__ == '__main__':
    from services.task_worker.main import run
    run()
