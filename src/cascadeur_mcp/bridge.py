"""Private local mailbox transport shared by stdio MCP clients."""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
import uuid
from pathlib import Path

from filelock import FileLock, Timeout

from .app_bridge import MAX_BYTES, atomic_json


class BridgeError(RuntimeError):
    pass


class Bridge:
    def __init__(self, directory, workspace, timeout=90, allow_scripts=False):
        self.directory = Path(directory).expanduser().resolve()
        self.workspace = Path(workspace).expanduser().resolve()
        if not math.isfinite(timeout) or not 1 <= timeout <= 3600:
            raise ValueError("Timeout must be between 1 and 3600 seconds.")
        self.timeout = timeout
        self.allow_scripts = allow_scripts
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            os.chmod(self.directory, 0o700)
        self._lock = asyncio.Lock()

    def status(self):
        path = self.directory / "status.json"
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise BridgeError(
                "Cascadeur bridge is not connected. Run the generated start_bridge.py in Cascadeur Python Console."
            ) from exc
        if value.get("protocol") != 1:
            raise BridgeError("Incompatible app bridge protocol. Update the bridge.")
        if time.time() - value.get("heartbeat", 0) > 10:
            raise BridgeError(
                "Cascadeur bridge heartbeat is stale. The app may be closed or busy."
            )
        if Path(value.get("workspace", "")).resolve() != self.workspace:
            raise BridgeError("Workspace mismatch between MCP server and app bridge.")
        return value

    async def call(self, method, params):
        async with self._lock:
            lock = FileLock(str(self.directory / "client.lock"))
            started = time.monotonic()
            while True:
                try:
                    lock.acquire(timeout=0)
                    break
                except Timeout:
                    if time.monotonic() - started > self.timeout:
                        raise BridgeError(
                            "Another client is still using Cascadeur; no request was sent."
                        ) from None
                    await asyncio.sleep(0.05)
            try:
                state = self.status()
                if method == "run_script" and not (
                    self.allow_scripts and state.get("allow_scripts")
                ):
                    raise BridgeError(
                        "Scripting must be explicitly enabled in both the server and app bridge."
                    )
                rid = uuid.uuid4().hex
                request = self.directory / f"request-{rid}.json"
                response = self.directory / f"response-{rid}.json"
                value = dict(
                    id=rid,
                    instance=state["instance"],
                    deadline=time.time() + self.timeout,
                    method=method,
                    params=params,
                )
                if len(json.dumps(value, allow_nan=False).encode()) > MAX_BYTES:
                    raise BridgeError("Request exceeds 4 MiB.")
                atomic_json(request, value)
                try:
                    deadline = time.monotonic() + self.timeout
                    while time.monotonic() < deadline:
                        if response.exists():
                            if response.stat().st_size > 32 * 1024 * 1024:
                                raise BridgeError("Response exceeds 32 MiB.")
                            result = json.loads(response.read_text())
                            if (
                                result.get("id") != rid
                                or result.get("instance") != state["instance"]
                            ):
                                raise BridgeError("Response identity mismatch.")
                            if not result.get("ok"):
                                raise BridgeError(
                                    result.get("error", "Cascadeur operation failed")
                                )
                            return dict(
                                result=result.get("result"),
                                log=result.get("log", ""),
                                messages=result.get("messages", []),
                            )
                        await asyncio.sleep(0.05)
                    raise BridgeError(
                        "Cascadeur operation timed out; it may already have changed the scene. Inspect before retrying. Request ID: "
                        + rid
                    )
                finally:
                    # Deleting an unclaimed request prevents late execution after cancellation.
                    request.unlink(missing_ok=True)
                    response.unlink(missing_ok=True)
            finally:
                lock.release()

    def file_stamp(self, value):
        path = Path(value).expanduser().resolve()
        if not path.is_relative_to(self.workspace):
            raise BridgeError("Output is outside workspace.")
        if not path.is_file():
            return None
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size, stat.st_ino)

    async def wait_file(self, value, seconds=30, previous_stamp=None):
        path = Path(value).resolve()
        if not path.is_relative_to(self.workspace):
            raise BridgeError("Output is outside workspace.")
        end = time.monotonic() + seconds
        previous = None
        while time.monotonic() < end:
            if path.is_file():
                size = path.stat().st_size
                stamp = self.file_stamp(path)
                if size > 0 and previous == stamp and stamp != previous_stamp:
                    return path
                previous = stamp
            await asyncio.sleep(0.2)
        raise BridgeError("Cascadeur has not produced the output yet: " + str(path))
