import asyncio
import json
import time
import uuid

import pytest

from cascadeur_mcp import app_bridge
from cascadeur_mcp.bridge import Bridge, BridgeError


def state(directory, workspace):
    value = dict(
        version="0.1.0",
        protocol=1,
        pid=123,
        instance=uuid.uuid4().hex,
        heartbeat=time.time(),
        workspace=str(workspace),
        allow_scripts=False,
    )
    app_bridge.atomic_json(directory / "status.json", value)
    return value


@pytest.fixture
def connection(tmp_path):
    directory = tmp_path / "bridge"
    workspace = tmp_path / "workspace"
    directory.mkdir()
    workspace.mkdir()
    value = state(directory, workspace)
    return directory, workspace, value


def test_stale_workspace_and_protocol_are_rejected(connection):
    directory, workspace, value = connection
    bridge = Bridge(directory, workspace)
    assert bridge.status()["instance"] == value["instance"]
    for patch, match in [
        ({"heartbeat": 0}, "stale"),
        ({"workspace": str(workspace / "elsewhere")}, "mismatch"),
        ({"protocol": 99}, "protocol"),
    ]:
        app_bridge.atomic_json(directory / "status.json", value | patch)
        with pytest.raises(BridgeError, match=match):
            bridge.status()


@pytest.mark.parametrize("field,value", [("deadline", 0), ("instance", "wrong")])
def test_app_never_executes_expired_or_wrong_session_request(
    connection, monkeypatch, field, value
):
    directory, workspace, status = connection
    called = []
    monkeypatch.setattr(
        app_bridge,
        "_state",
        dict(
            directory=directory,
            workspace=workspace,
            instance=status["instance"],
            allow_scripts=False,
            last_status=time.time(),
        ),
    )
    monkeypatch.setattr(
        app_bridge, "execute_with_messages", lambda *args: called.append(args)
    )
    rid = uuid.uuid4().hex
    request = dict(
        id=rid,
        instance=status["instance"],
        deadline=time.time() + 5,
        method="set_pose",
        params={},
    )
    request[field] = value
    app_bridge.atomic_json(directory / f"request-{rid}.json", request)
    app_bridge._poll()
    result = json.loads((directory / f"response-{rid}.json").read_text())
    assert not result["ok"]
    assert called == []
    assert not list(directory.glob("*.running"))


async def test_timeout_removes_unclaimed_request(connection):
    directory, workspace, _ = connection
    bridge = Bridge(directory, workspace, timeout=1)
    with pytest.raises(BridgeError, match="may already have changed"):
        await bridge.call("set_pose", {})
    assert not list(directory.glob("request-*.json"))


async def test_cancellation_removes_unclaimed_request(connection):
    directory, workspace, _ = connection
    bridge = Bridge(directory, workspace)
    task = asyncio.create_task(bridge.call("set_pose", {}))
    while not list(directory.glob("request-*.json")):
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not list(directory.glob("request-*.json"))


async def test_concurrent_clients_are_serialized_and_errors_propagate(connection):
    directory, workspace, status = connection
    clients = [Bridge(directory, workspace) for _ in range(2)]
    observed = []

    async def app():
        while len(observed) < 2:
            files = list(directory.glob("request-*.json"))
            assert len(files) <= 1
            if not files:
                await asyncio.sleep(0.01)
                continue
            request = json.loads(files[0].read_text())
            observed.append(request["params"]["n"])
            await asyncio.sleep(0.1)
            assert len(list(directory.glob("request-*.json"))) == 1
            app_bridge.atomic_json(
                directory / f"response-{request['id']}.json",
                dict(
                    id=request["id"],
                    instance=status["instance"],
                    ok=True,
                    result={"n": request["params"]["n"]},
                ),
            )
            files[0].unlink()

    app_task = asyncio.create_task(app())
    results = await asyncio.gather(
        *(client.call("get_state", {"n": i}) for i, client in enumerate(clients))
    )
    await app_task
    assert sorted(x["result"]["n"] for x in results) == [0, 1]
    assert not list(directory.glob("response-*.json"))


async def test_scripts_require_double_opt_in(connection):
    directory, workspace, _ = connection
    for allowed in (False, True):
        with pytest.raises(BridgeError, match="both"):
            await Bridge(directory, workspace, allow_scripts=allowed).call(
                "run_script", {"code": "pass"}
            )
    assert not list(directory.glob("request-*.json"))


async def test_old_output_is_not_returned_as_fresh_render(connection):
    directory, workspace, _ = connection
    bridge = Bridge(directory, workspace)
    image = workspace / "capture.png"
    image.write_bytes(b"old-output")
    old = bridge.file_stamp(image)
    with pytest.raises(BridgeError, match="not produced"):
        await bridge.wait_file(image, seconds=0.1, previous_stamp=old)
    image.write_bytes(b"new-output-longer")
    assert await bridge.wait_file(image, seconds=1, previous_stamp=old) == image
