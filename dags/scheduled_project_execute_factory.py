import json
import logging
import re
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.exceptions import AirflowException
from airflow.models import Variable, Connection
from airflow.providers.standard.operators.python import PythonOperator
from airflow.providers.standard.sensors.python import PythonSensor
from airflow.providers.http.hooks.http import HttpHook
from airflow.providers.http.operators.http import HttpOperator

log = logging.getLogger("airflow.task")

POKE_INTERVAL = 10
SENSOR_TIMEOUT = 60 * 60
TASK_SUCCESS_STATUSES = {"success"}
TASK_FAIL_STATUSES = {"cancelled", "canceled", "error", "failed"}
TZ = pendulum.timezone("Europe/Moscow")

HTTP_CONNECTOR_ID = "dvt_api"
PROJECT_VARIABLE_KEY = "PROJECTS_CONFIG"


def _sanitize(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", str(text))


def _get_projects_config(var_key: str) -> list[dict]:
    data = Variable.get(var_key, default_var=[], deserialize_json=True)

    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            data = [data]

    projects: list[dict] = []

    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                projects.append({"project_id": item, "schedule": "@daily"})

            elif isinstance(item, dict):
                project_id = item.get("project_id")
                if not project_id:
                    continue

                projects.append({
                    "project_id": project_id,
                    "project_name": item.get("project_name", None),
                    "schedule": item.get("schedule", "@daily")
                })
            else:
                log.warning(f"{PROJECT_VARIABLE_KEY}: unknown list element: %r", item)

    for p in projects:
        p.setdefault("schedule", "@daily")

    if not projects:
        log.warning(f"{PROJECT_VARIABLE_KEY} is empty — no DAGs will be generated.")

    return projects


def run_project_callable(
        project_id: str,
        **context
) -> str:
    """POST /api/projects/<id>/tasks/new and returns task_id."""
    hook = HttpHook(http_conn_id=HTTP_CONNECTOR_ID, method="POST")
    conn: Connection = hook.get_connection(HTTP_CONNECTOR_ID)
    api_key = (conn.extra_dejson or {}).get("api_key")
    if not api_key:
        raise AirflowException("❌ api_key not found in 'dvt_api' connection extra.")

    endpoint = f"/api/projects/{project_id}/tasks/new"

    op = HttpOperator(
        task_id="run_project_http_call",
        http_conn_id=HTTP_CONNECTOR_ID,
        endpoint=endpoint,
        method="POST",
        params={
            "mode": "full",
            "force_exec": False
        },
        headers={"Content-Type": "application/json", "X-API-KEY": api_key},
        log_response=True,
        response_filter=lambda r: r.text,
    )
    raw = op.execute(context=context)

    try:
        data = json.loads(raw)

    except Exception:
        raise AirflowException(f"Invalid JSON response: {raw!r}")

    if not (isinstance(data, dict) and data.get("success") and data.get("task_id")):
        raise AirflowException(f"Unexpected start-task response: {data!r}")

    task_id = str(data["task_id"])
    log.info("✅ External task started: project=%s task_id=%s", project_id, task_id)
    return task_id


def wait_until_done_callable(project_id: str, task_id_to_track: str, **context) -> bool:
    """GET /api/projects/<id>/tasks/<task_id>/info — waits until completion."""
    ti = context["ti"]
    run_id = context["dag_run"].run_id

    hook = HttpHook(method="GET", http_conn_id=HTTP_CONNECTOR_ID)
    conn: Connection = hook.get_connection(HTTP_CONNECTOR_ID)
    api_key = (conn.extra_dejson or {}).get("api_key")
    if not api_key:
        raise AirflowException("❌ api_key not found in 'dvt_api' connection extra.")

    endpoint = f"/api/projects/{project_id}/tasks/{task_id_to_track}/info"
    resp = hook.run(endpoint, headers={
        "X-API-KEY": api_key,
        "X-Airflow-Run-Id": run_id,
        "X-Airflow-Task-Id": ti.task_id,
    })

    try:
        info = resp.json()

    except Exception:
        raise AirflowException(f"Invalid JSON from {endpoint}: {resp.text!r}")

    status = (info.get("status") or "").strip().lower()
    log.info(f"[run_id={run_id}] projectID={project_id} taskID={task_id_to_track} status={status}")

    if status in TASK_SUCCESS_STATUSES:
        log.info(f"✅ External task ID={task_id_to_track} completed successfully.")
        return True

    if status in TASK_FAIL_STATUSES:
        log.error(f"❌ External taskID={task_id_to_track} failed with status: {status}")
        raise AirflowException(f"External taskID={task_id_to_track} failed with status: {status}")

    return False


# --------------------------------------------------------------------------- #
#                               DAG factory                                   #
# --------------------------------------------------------------------------- #

def _make_single_project_dag(
        project_id: str,
        schedule: str,
        project_name: str | None = None,
) -> DAG:
    safe_name = _sanitize(project_name or "no_name")
    dag_id = f"run_project_{safe_name}_{project_id}"

    with DAG(
        dag_id=dag_id,
        description=f"Run external project {project_id}",
        start_date=pendulum.now(TZ).subtract(days=1),
        schedule=schedule,
        catchup=False,
        max_active_runs=1,
        tags=["api", "project"],
        default_args={"retries": 0},
        dagrun_timeout=timedelta(hours=4),
    ) as dag:

        run_project = PythonOperator(
            task_id="run_project",
            python_callable=run_project_callable,
            op_kwargs={
                "project_id": project_id,
            },
        )

        wait_for_project = PythonSensor(
            task_id="wait_for_project",
            python_callable=wait_until_done_callable,
            op_kwargs={
                "project_id": project_id,
                "task_id_to_track": run_project.output,
            },
            poke_interval=POKE_INTERVAL,
            timeout=SENSOR_TIMEOUT,
            mode="reschedule",
        )

        run_project >> wait_for_project
        return dag


# --------------------------------------------------------------------------- #
#                            Generate DAGs                                    #
# --------------------------------------------------------------------------- #

_PROJECTS = _get_projects_config(PROJECT_VARIABLE_KEY)
log.info(f"{PROJECT_VARIABLE_KEY} normalized: %s", _PROJECTS)

for cfg in _PROJECTS:
    try:
        pid = cfg["project_id"]
        schedule = cfg["schedule"]
        pname = cfg.get("project_name")
        dag_obj = _make_single_project_dag(pid, schedule, pname)
        globals()[dag_obj.dag_id] = dag_obj

    except Exception as e:
        log.error(f"Invalid {PROJECT_VARIABLE_KEY} element: %r (%s)", cfg, e)
