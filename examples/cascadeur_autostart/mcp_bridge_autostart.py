"""Start the cascadeur-mcp app bridge when Cascadeur creates its first scene (at startup).

Added for the cascadeur-mcp workflow; delete this file to turn autostart off. Runs once per
Cascadeur process: later scenes do not restart a running bridge.
"""
import csc

START = r"C:\Users\IshikiI\Desktop\Coding\Cascadeur\VibeAnimating\cascadeur-work\setup\start_bridge.py"


def run(scene: csc.domain.Scene):
    import sys

    if sys.modules.get("cascadeur_mcp.app_bridge") is not None:
        return
    try:
        exec(open(START, encoding="utf-8").read(), {"__name__": "__mcp_autostart__"})
    except Exception as exc:  # never break scene creation
        import logging

        logging.error("cascadeur-mcp bridge autostart failed: %s", exc)
