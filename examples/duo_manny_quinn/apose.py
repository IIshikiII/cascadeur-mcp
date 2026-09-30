"""AutoPosing with explicit locks (cascadeur_mcp.autopose_flow) from scripts:
python apose.py FRAMES [prefix] [anchor,anchor,...]   (default anchors: hands and feet)"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "cascadeur-mcp" / "src"))
from cascadeur_mcp.autopose_flow import autopose_explicit  # noqa: E402
from mcp_call import call as _call  # noqa: E402


async def step(method, **params):
    return (await _call(method, params))["result"]


def apose(frames, character="", anchors=None):
    return asyncio.run(autopose_explicit(step, frames, anchors, character))


if __name__ == "__main__":
    frames = [int(x) for x in sys.argv[1].split(",")]
    prefix = sys.argv[2] if len(sys.argv) > 2 else ""
    anchors = sys.argv[3].split(",") if len(sys.argv) > 3 and sys.argv[3] else None
    print(json.dumps(apose(frames, prefix, anchors), indent=1))
