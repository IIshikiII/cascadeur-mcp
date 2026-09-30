"""Start the cascadeur-mcp app bridge when Cascadeur opens a scene (restart_cascadeur.ps1 passes one).

Added for the cascadeur-mcp workflow; delete this file to turn autostart off. Runs once per
Cascadeur process: later scenes do not restart a running bridge. Every call is logged to
cascadeur-work/session/autostart.log; crash diagnostics (cascadeur_mcp.diag) go to the same folder.
"""
import csc

START = r"C:\Users\IshikiI\Desktop\Coding\Cascadeur\VibeAnimating\cascadeur-work\setup\start_bridge.py"
SESSION = r"C:\Users\IshikiI\Desktop\Coding\Cascadeur\VibeAnimating\cascadeur-work\session"


def _log(text):
    import datetime
    import os

    try:
        with open(os.path.join(SESSION, "autostart.log"), "a", encoding="utf-8") as f:
            f.write("%s pid %d %s\n" % (datetime.datetime.now().isoformat(timespec="seconds"), os.getpid(), text))
    except OSError:
        pass


def run(scene: csc.domain.Scene):
    import sys

    if sys.modules.get("cascadeur_mcp.app_bridge") is not None:
        _log("event: bridge already loaded")
        return
    try:
        exec(open(START, encoding="utf-8").read(), {"__name__": "__mcp_autostart__"})
        _log("event: bridge started")
    except Exception as exc:  # never break scene loading
        import traceback

        _log("event: FAILED %r\n%s" % (exc, traceback.format_exc()))
        return
    try:
        from cascadeur_mcp import diag

        _log("event: diag %s" % diag.install(SESSION))
        from PySide6 import QtCore

        # the main window does not exist yet at scene load: hook it a little later
        QtCore.QTimer.singleShot(5000, lambda: _log("event: diag later %s" % diag.install(SESSION)))
    except Exception as exc:
        _log("event: diag FAILED %r" % exc)
