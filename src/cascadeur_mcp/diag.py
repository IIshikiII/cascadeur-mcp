"""Crash diagnostics inside Cascadeur: main-window lifecycle and fatal errors.

install(directory) writes to <directory>/window_events.log and faulthandler.log. (No Qt message
handler: Qt may call it from its render thread, which is unsafe for the embedded interpreter.)
Idempotent; call it again when the main window was replaced.
"""
import builtins
import datetime
import os
import traceback

_STATE = builtins.__dict__.setdefault("_cascadeur_mcp_diag", {})


def _stamp():
    return datetime.datetime.now().isoformat(timespec="milliseconds")


def _write(name, text):
    try:
        with open(os.path.join(_STATE["dir"], name), "a", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass


def _window_event(what):
    stack = "".join(traceback.format_stack()[:-1][-12:])
    _write("window_events.log", "%s pid %d %s\n%s\n" % (_stamp(), os.getpid(), what, stack or "  (no Python frames: C++ event loop)\n"))


def install(directory):
    from PySide6 import QtCore, QtGui, QtQuick  # noqa: F401  (QtQuick first: typed wrappers)

    _STATE["dir"] = directory
    if not _STATE.get("faulthandler"):
        import faulthandler

        _STATE["fault_file"] = open(os.path.join(directory, "faulthandler.log"), "a", encoding="utf-8")
        _STATE["fault_file"].write("%s pid %d faulthandler on\n" % (_stamp(), os.getpid()))
        _STATE["fault_file"].flush()
        faulthandler.enable(file=_STATE["fault_file"], all_threads=True)
        _STATE["faulthandler"] = True
    if not _STATE.get("saveall"):
        # The main window was destroyed from inside Python's cyclic GC (2026-09-30). With
        # DEBUG_SAVEALL the collector parks unreachable cycles in gc.garbage instead of freeing
        # them: nothing is destroyed that way, and suspects() shows what it would have freed.
        import gc

        gc.set_debug(gc.DEBUG_SAVEALL)
        _STATE["saveall"] = True
    hooked = _STATE.setdefault("windows", [])
    for window in QtGui.QGuiApplication.topLevelWindows():
        if window.objectName() != "MainWindow" or any(w is window for w, _ in hooked):
            continue
        slots = []
        for signal, what in (
            ("destroyed", "MainWindow destroyed"),
            ("visibleChanged", "MainWindow visibleChanged"),
            ("visibilityChanged", "MainWindow visibilityChanged"),
            ("closing", "MainWindow closing"),
        ):
            sig = getattr(window, signal, None)
            if sig is None:
                continue
            slot = (lambda *args, _w=what: _window_event("%s %s" % (_w, [str(a) for a in args])))
            sig.connect(slot)
            slots.append(slot)
        hooked.append((window, slots))
        _window_event("hooks installed on MainWindow")
    return dict(dir=directory, windows_hooked=len(hooked))


def suspects():
    """Qt wrappers the cyclic GC wanted to free (parked in gc.garbage by DEBUG_SAVEALL)."""
    import gc

    import shiboken6
    from PySide6 import QtCore

    found = {}
    for o in list(gc.garbage):
        try:
            if isinstance(o, QtCore.QObject):
                key = "%s owned=%s valid=%s name=%r" % (
                    type(o).__name__, shiboken6.ownedByPython(o), shiboken6.isValid(o),
                    o.objectName() if shiboken6.isValid(o) else "?")
                found[key] = found.get(key, 0) + 1
        except Exception as exc:
            found["error %r" % exc] = found.get("error %r" % exc, 0) + 1
    return dict(garbage=len(gc.garbage), qt=found)


def sweep():
    """Empty gc.garbage without letting the collector destroy Qt objects.

    The main window was destroyed from inside Python's cyclic GC: freeing a wrapper that Python
    owns deletes its C++ object. Live Qt wrappers owned by Python are kept for good (quarantine);
    everything else parked by DEBUG_SAVEALL is released."""
    import gc

    import shiboken6
    from PySide6 import QtCore

    keep = _STATE.setdefault("quarantine", [])
    kept = 0
    for o in gc.garbage:
        try:
            if isinstance(o, QtCore.QObject) and shiboken6.isValid(o) and shiboken6.ownedByPython(o):
                keep.append(o)
                kept += 1
        except Exception:
            continue
    released = len(gc.garbage)
    del gc.garbage[:]
    return dict(released=released - kept, quarantined=kept, quarantine_total=len(keep))


def protect(interval_ms=60000):
    """DEBUG_SAVEALL + a periodic sweep(): cyclic GC never deletes a Qt object."""
    import gc

    from PySide6 import QtCore

    gc.set_debug(gc.DEBUG_SAVEALL)
    if _STATE.get("timer") is None:
        timer = QtCore.QTimer()
        timer.setInterval(interval_ms)
        timer.timeout.connect(sweep)
        timer.start()
        _STATE["timer"] = timer
    return dict(debug=gc.get_debug(), interval_ms=interval_ms)
