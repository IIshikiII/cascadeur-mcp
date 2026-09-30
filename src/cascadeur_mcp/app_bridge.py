"""Runs inside Cascadeur on Qt's main thread; no MCP dependencies required."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import time
import traceback
import uuid
from pathlib import Path

_timer = None
_state = None
_busy = False
MAX_BYTES = 4 * 1024 * 1024


def json_value(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_value(v) for v in value]
    if hasattr(value, "tolist"):
        return value.tolist()
    return str(value)


def atomic_json(path, value):
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as out:
            os.chmod(temp, 0o600)
            json.dump(value, out, allow_nan=False)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def stop():
    global _timer, _state
    if _timer is not None:
        _timer.stop()
        _timer = None
    if _state is not None:
        (_state["directory"] / "status.json").unlink(missing_ok=True)
        _state = None


def start(bridge_dir, workspace, allow_scripts=False, pyside6_site=None):
    global _timer, _state
    directory = Path(bridge_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        os.chmod(directory, 0o700)
    previous = directory / "status.json"
    if previous.exists():
        data = json.loads(previous.read_text())
        if (
            data.get("pid") != os.getpid()
            and time.time() - data.get("heartbeat", 0) < 10
        ):
            raise RuntimeError(
                "Another Cascadeur instance already uses this bridge directory."
            )
    stop()
    _state = dict(
        directory=directory,
        workspace=Path(workspace).expanduser().resolve(),
        allow_scripts=bool(allow_scripts),
        pyside6_site=str(Path(pyside6_site).expanduser().resolve()) if pyside6_site else None,
        instance=uuid.uuid4().hex,
        last_status=0,
    )
    _state["workspace"].mkdir(parents=True, exist_ok=True)
    if _state["pyside6_site"]:
        _enable_pyside6(_state["pyside6_site"])
    _timer = _start_timer(50, _poll)
    _poll()
    try:  # keep Python's cyclic GC from destroying Qt objects (it destroyed the main window)
        from . import diag

        diag.protect()
    except Exception as exc:
        print("cascadeur-mcp: GC protection unavailable: %r" % (exc,))
    print("Cascadeur MCP bridge started: " + str(directory))


def _enable_pyside6(site):
    """Make a PySide6 build bound to Cascadeur's own Qt importable (see docs/FIELD_NOTES.md)."""
    import sys

    if os.name == "nt":
        os.add_dll_directory(site)  # python3.dll for the abi3 bindings
        os.add_dll_directory(str(Path(sys.executable).parent))  # Cascadeur's Qt DLLs
    if site not in sys.path:
        sys.path.insert(0, site)


class _QtTimer:
    def __init__(self, interval, callback):
        from PySide6.QtCore import QCoreApplication, QThread, QTimer

        if QThread.currentThread() != QCoreApplication.instance().thread():
            raise RuntimeError(
                "Start the bridge from Cascadeur Python Console on the main thread."
            )
        self._timer = QTimer(QCoreApplication.instance())
        self._timer.setInterval(interval)
        self._timer.timeout.connect(callback)
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self._timer.deleteLater()


class _Win32Timer:
    """Thread timer dispatched by the app's own message loop (Qt pumps it)."""

    def __init__(self, interval, callback):
        import ctypes
        from ctypes import wintypes

        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        proc_type = ctypes.WINFUNCTYPE(
            None, wintypes.HWND, wintypes.UINT, ctypes.c_size_t, wintypes.DWORD
        )
        self._user32.SetTimer.restype = ctypes.c_size_t
        self._user32.SetTimer.argtypes = [
            wintypes.HWND, ctypes.c_size_t, wintypes.UINT, proc_type
        ]
        self._user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]

        def on_timer(hwnd, message, timer_id, tick):
            try:
                callback()
            except Exception:
                traceback.print_exc()

        # Keep a reference: the callback must outlive the timer.
        self._proc = proc_type(on_timer)
        self._id = self._user32.SetTimer(None, 0, interval, self._proc)
        if not self._id:
            raise ctypes.WinError(ctypes.get_last_error())

    def stop(self):
        if self._id:
            self._user32.KillTimer(None, self._id)
            self._id = 0


def _start_timer(interval, callback):
    try:
        return _QtTimer(interval, callback)
    except ImportError:
        if os.name != "nt":
            raise
        return _Win32Timer(interval, callback)


def _poll():
    global _busy
    if _busy:
        return
    _busy = True
    try:
        _poll_once()
    finally:
        _busy = False


def _poll_once():
    if _state is None:
        return
    directory = _state["directory"]
    try:
        if time.time() - _state["last_status"] > 1:
            atomic_json(
                directory / "status.json",
                dict(
                    version="0.1.0",
                    protocol=1,
                    pid=os.getpid(),
                    instance=_state["instance"],
                    heartbeat=time.time(),
                    workspace=str(_state["workspace"]),
                    allow_scripts=_state["allow_scripts"],
                ),
            )
            _state["last_status"] = time.time()
        # Exactly one request each tick: no work starvation and no reentrant scene edits.
        pending = sorted(directory.glob("request-*.json"))
        if not pending:
            return
        path = pending[0]
        rid = path.name[8:-5]
        if not re.fullmatch("[a-f0-9]{32}", rid):
            path.rename(path.with_suffix(".invalid"))
            return
        claimed = path.with_suffix(".running")
        path.replace(claimed)
        result = {"id": rid, "instance": _state["instance"]}
        try:
            if claimed.stat().st_size > MAX_BYTES:
                raise ValueError("Request exceeds 4 MiB.")
            req = json.loads(claimed.read_text())
            if req.get("id") != rid or req.get("instance") != _state["instance"]:
                raise ValueError("Request identity or app instance mismatch.")
            if time.time() > req["deadline"]:
                raise TimeoutError("Request expired before execution; no action taken.")
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                value, messages = execute_with_messages(
                    req["method"], req.get("params", {})
                )
            result.update(
                ok=True,
                result=json_value(value),
                log=output.getvalue()[-16000:],
                messages=messages,
            )
        except Exception as exc:
            result.update(
                ok=False, error=str(exc), traceback=traceback.format_exc()[-8000:]
            )
        finally:
            claimed.unlink(missing_ok=True)
        atomic_json(directory / ("response-" + rid + ".json"), result)
    except Exception:
        traceback.print_exc()


def execute_with_messages(method, params):
    import csc

    try:
        from events import event_message_manager
    except ImportError:
        # Older builds (e.g. Windows releases) lack the message manager.
        return dispatch(method, params), []

    messages = []
    levels = {int(v): k for k, v in csc.MessageLevel.__members__.items()}

    def on_message(scene, full_message, level, simple_message):
        messages.append(
            {"level": levels.get(int(level), str(level)), "text": full_message[-4000:]}
        )

    subscription = event_message_manager.subscribe(on_message)
    try:
        value = dispatch(method, params)
    finally:
        event_message_manager.unsubscribe(subscription)
    errors = [m["text"] for m in messages if m["level"] == "Error"]
    if errors:
        raise RuntimeError("Cascadeur reported: " + "; ".join(errors[-5:]))
    return value, messages[-30:]


def dispatch(method, params):
    import csc

    if method == "run_script":
        if not _state["allow_scripts"]:
            raise PermissionError("Scripting is disabled in the app bridge.")
        app = csc.app.get_application()
        view = app.get_scene_manager().current_scene()
        ns = dict(
            csc=csc, app=app, view=view, scene=view.domain_scene() if view else None
        )
        exec(compile(params["code"], "<cascadeur-mcp>", "exec"), ns, ns)
        return ns.get("result")
    return _operations().dispatch(method, params, _state)


_module_stamps = {}


def _operations():
    """Import operations, reloading them when their files change on disk."""
    import importlib
    import sys

    for name in ("cascadeur_mcp.actions", "cascadeur_mcp.operations"):
        module = sys.modules.get(name)
        if module is None:
            module = importlib.import_module(name)
        stamp = os.stat(module.__file__).st_mtime_ns
        if _module_stamps.setdefault(name, stamp) != stamp:
            module = importlib.reload(module)
            _module_stamps[name] = stamp
    return module
