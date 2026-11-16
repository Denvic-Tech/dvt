"""Observe candidate HTTPS and Docker state on the dedicated fixture host."""

import json
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

mode, work = sys.argv[1], Path(sys.argv[2])
project = (work / "project").read_text().strip()
previous = (work / "previous").read_text().strip()
target = (work / "target").read_text().strip()
origin = f"https://localhost:{(work / 'port').read_text().strip()}"
context = ssl.create_default_context(cafile=work / "cert.pem")
opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context)
)
cookie = None


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def request(path, method="GET", body=None, *, csrf=True, headers=None, expected=200):
    params = {"Cookie": cookie} if cookie else {}
    if method == "POST" and csrf:
        params.update(Origin=origin, **{"X-DVT-CSRF": "1", "Content-Type": "application/json"})
    params.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(origin + path, data=data, headers=params, method=method)
    try:
        response = opener.open(req, timeout=3)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        assert response.status == expected, (path, response.status, expected)
        return json.load(response), response.headers


def wait(probe, timeout=100):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if result := probe():
                return result
        except (OSError, subprocess.CalledProcessError):
            pass
        time.sleep(1)
    raise AssertionError("Fixture condition did not become true")


def current():
    container_id = docker("ps", "-aq", "--filter", f"label=com.docker.compose.project={project}")
    if container_id:
        result, = json.loads(docker("inspect", container_id))
        return result


if mode == "arm":
    wait(lambda: request("/health"))
    assert request("/health")[0] == {"status": "ok"}
    for endpoint in ("/api/config", "/api/secrets", "/api/operations/active"):
        request(endpoint, expected=401)
    token = docker(
        "run", "--rm", "--network", "none", "--pull=never",
        "--mount", f"type=bind,source={work / 'data'},target={work / 'data'}",
        previous, "candidate-pair", str(work / "data"),
    )
    request(
        "/api/session", "POST", {"code": token}, headers={"Origin": "https://other.invalid"},
        expected=403,
    )
    _, headers = request("/api/session", "POST", {"code": token})
    cookie = headers["Set-Cookie"].split(";", 1)[0]
    assert {"HttpOnly", "Secure", "SameSite=strict"} <= set(
        item.strip() for item in headers["Set-Cookie"].split(";")
    )
    request("/api/session", "POST", {"code": token}, expected=401)
    (work / "session").write_text(cookie)
    previous_id = current()["Id"]
    pin, _ = request("/api/operations/candidate")
    selection = {"kind": "manager_recovery", "release": pin}
    request("/api/operations", "POST", selection, csrf=False, expected=403)
    request("/api/operations", "POST", selection,
            headers={"Origin": "https://other.invalid", "Idempotency-Key": "invalid"}, expected=403)
    request("/api/install", "POST", {}, expected=410)
    operation, _ = request("/api/operations", "POST", selection,
                           headers={"Idempotency-Key": "fixture-handoff"}, expected=202)
    operation = operation["operation"]
    operation_id, instance = operation["id"], operation["instance_id"]
    (work / "previous-id").write_text(previous_id)
    (work / "instance").write_text(instance)
    (work / "candidate-pin").write_text(json.dumps(pin))
    executor = f"dvt-bootstrap-executor-{instance}"

    def detached_replacement():
        data = current()
        return data if data and data["Config"]["Image"] == target and data["State"]["Running"] else None

    armed = wait(detached_replacement)
    assert armed["Id"] != previous_id
    execution, = json.loads(docker("inspect", executor))
    assert execution["State"]["Running"]
    assert execution["Config"]["Image"] == previous
    assert execution["HostConfig"]["NetworkMode"] == "host"
    assert not execution["HostConfig"]["PortBindings"]
    assert "com.docker.compose.project" not in execution["Config"]["Labels"]
    assert execution["Config"]["Labels"]["dvt.executor.operation"] == operation_id
    (work / "executor-before").write_text(execution["Id"])
    (work / "reboot.ready").write_text(f"{operation_id}\n")
    with (work / "reboot.ready").open("rb") as marker:
        import os

        os.fsync(marker.fileno())
    print(f"ARMED operation={operation_id} instance={instance}")
    print(f"Previous manager {previous_id[:12]}; candidate manager {armed['Id'][:12]}; "
          f"detached executor {execution['Id'][:12]}")
elif mode in {"verify", "verify-fallback"}:
    cookie = (work / "session").read_text()
    operation_id = (work / "reboot.ready").read_text().strip()
    instance = (work / "instance").read_text()
    pin = json.loads((work / "candidate-pin").read_text())

    expected_stage, expected_image, claim_count = (
        ("succeeded", target, 2) if mode == "verify" else ("cancelled", previous, 1)
    )

    def finished():
        state, _ = request(f"/api/operations/{operation_id}")
        return state if state["operation"]["stage"] == expected_stage else None

    state = wait(finished)
    operation = state["operation"]
    assert operation["instance_id"] == instance
    assert operation["observation"]["observed_digest"] == expected_image.split("@")[1]
    assert current()["Config"]["Image"] == expected_image
    assert state["journal_format"] == 1
    assert operation["last_owner"]
    assert current()["Id"] != (work / "previous-id").read_text()
    events, _ = request(f"/api/operations/{operation_id}/events")
    claims = [event["owner"]["claim_id"] for event in events if event["kind"] == "owner_acquired"]
    assert len(claims) == len(set(claims)) == claim_count
    if mode == "verify-fallback":
        assert any(
            event.get("checkpoint") and event["checkpoint"]["reason"] == "manager_unavailable"
            for event in events
        )
    assert claims[-1] == operation["last_owner"]["claim_id"]
    replay, _ = request("/api/operations", "POST", {"kind": "manager_recovery", "release": pin},
                        headers={"Idempotency-Key": "fixture-handoff"}, expected=202)
    assert replay["operation"]["id"] == operation_id
    assert replay["operation"]["stage"] == expected_stage
    (work / "session").unlink()
    print(f"COMPLETE operation={operation_id} instance={instance} stage={expected_stage} "
          f"claims={len(claims)} manager={current()['Id'][:12]}")
else:
    raise AssertionError(mode)
