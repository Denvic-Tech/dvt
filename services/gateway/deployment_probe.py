"""Probe the running Scheduler and actual execution workers from the target network."""

import json
import sys
import urllib.request

import grpc
from contracts.src.orchestrator.v1 import orchestrator_pb2, orchestrator_pb2_grpc

import config


def probe(hostnames: set[str]) -> bool:
    with grpc.insecure_channel(
        config.ORCHESTRATOR.ORCHESTRATOR_URL, options=(("grpc.enable_http_proxy", 0),)
    ) as channel:
        capacity = orchestrator_pb2_grpc.OrchestratorStub(channel).GetExecutionCapacity(
            orchestrator_pb2.GetExecutionCapacityRequest(), timeout=4
        )
    ready_hostnames = {
        worker.worker_id.removeprefix("task-worker-").rpartition("-")[0]
        for worker in capacity.workers
        if worker.alive
        and worker.status.lower() == "online"
        and worker.max_concurrent == 1
        and (worker.available_slots == 1 or worker.busy)
    }
    if not hostnames or not hostnames <= ready_hostnames:
        return False

    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
        f"http://{config.PROJECT_SCHEDULER.PROJECT_SCHEDULER_HOST}:"
        f"{config.PROJECT_SCHEDULER.PROJECT_SCHEDULER_PORT}/health",
        timeout=4,
    ) as response:
        return response.status == 200 and json.load(response)["status"] == "ok"


if __name__ == "__main__":
    sys.exit(0 if probe(set(sys.argv[1:])) else 1)
