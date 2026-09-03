import json
import logging
from datetime import datetime, UTC

from airflow.sdk import DAG

from airflow.models.param import Param
from airflow.providers.standard.operators.python import PythonOperator
from airflow.providers.standard.sensors.python import PythonSensor

from airflow.providers.http.hooks.http import HttpHook
from airflow.providers.http.operators.http import HttpOperator

from airflow.models import Connection
from airflow.exceptions import AirflowException

log = logging.getLogger("airflow.task")

POKE_INTERVAL = 10
SENSOR_TIMEOUT = 60 * 60
SUCCESS_STATES = {"success"}
FAIL_STATES = {"cancelled", "error"}

HTTP_CONNECTOR_ID = "dvt_api"


def run_project_callable(api_key: str, **context) -> str:
    """Стартуем задачу и возвращаем task_id (улетит в XCom как return_value)."""
    dag_run = context["dag_run"]
    project_id = dag_run.conf.get("project_id") or context["params"]["project_id"]
    endpoint = f"/api/projects/{project_id}/tasks/new"

    op = HttpOperator(
        task_id="run_project_http_call",
        http_conn_id=HTTP_CONNECTOR_ID,
        endpoint=endpoint,
        method="POST",
        params={
            "mode": "full",
            "force_exec": False,
        },
        headers={
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
        },
        log_response=True,
        response_filter=lambda response: response.text,
    )

    raw = op.execute(context=context)
    try:
        data = json.loads(raw)
    except Exception:
        raise AirflowException(f"Неверный ответ старта задачи (не JSON): {raw!r}")

    if not (isinstance(data, dict) and data.get("success") and data.get("task_id")):
        raise AirflowException(f"Неверный ответ старта задачи: {data!r}")

    return data["task_id"]


def wait_until_done_callable(
        project_id: str,
        api_key: str,
        http_conn_id: str,
        task_id_to_track: str,
        **context,
) -> bool:
    """
    Возвращает True, когда задача завершилась успешно.
    Поднимает AirflowException, если задача завершилась неуспешно.
    Возвращает False — продолжать ждать.
    """
    ti = context["ti"]
    run_id = context["dag_run"].run_id
    try_no = ti.try_number
    log.info(f"[run_id={run_id} try={try_no}] Poll {task_id_to_track}")

    hook = HttpHook(method="GET", http_conn_id=http_conn_id)
    endpoint = f"/api/projects/{project_id}/tasks/{task_id_to_track}/info"

    headers = {"X-API-KEY": api_key}
    resp = hook.run(endpoint, headers=headers)
    try:
        info = resp.json()
    except Exception:
        raise AirflowException(f"Некорректный JSON от {endpoint}: {resp.text!r}")

    status = info.get("status")
    if not status:
        return False

    status_norm = str(status).strip().lower()
    log.info(f"Task {task_id_to_track}: current status = '{status_norm}'")

    if status_norm in SUCCESS_STATES:
        return True
    if status_norm in FAIL_STATES:
        raise AirflowException(f"Задача {task_id_to_track} завершилась со статусом: {status}")

    return False


with DAG(
        dag_id="manual_run_project",
        start_date=datetime(2025, 10, 1, tzinfo=UTC),
        schedule=None,
        catchup=False,
        tags=["api", "project"],
        params={
            "project_id": Param(
                default="",
                type="string",
                title="Project ID",
                description="UUID проекта, который нужно запустить",
            )
        },
) as dag:
    hook = HttpHook(http_conn_id=HTTP_CONNECTOR_ID, method="POST")
    conn: Connection = hook.get_connection(HTTP_CONNECTOR_ID)
    extra = conn.extra_dejson
    api_key_conn = extra.get("api_key")
    if not api_key_conn:
        raise ValueError("❌ Не указан api_key в extra подключения dvt_api")

    run_project = PythonOperator(
        task_id="run_project",
        python_callable=run_project_callable,
        op_kwargs={"api_key": api_key_conn},
    )

    wait_for_project = PythonSensor(
        task_id="wait_for_project",
        python_callable=wait_until_done_callable,
        op_kwargs={
            "project_id": "{{ dag_run.conf.get('project_id') or params.project_id }}",
            "api_key": api_key_conn,
            "http_conn_id": HTTP_CONNECTOR_ID,
            "task_id_to_track": run_project.output,
        },
        poke_interval=POKE_INTERVAL,
        timeout=SENSOR_TIMEOUT,
        mode="reschedule",
        soft_fail=False,
    )

    run_project >> wait_for_project
