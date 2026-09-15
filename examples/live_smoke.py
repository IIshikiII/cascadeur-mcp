"""End-to-end MCP test using the user's installed Cascy sample; no asset redistribution.
Run with --sample /path/to/Cascy.casc --workspace /absolute/test/output --bridge-dir /absolute/session.
This creates/edits only body-and-fingers-test.casc in the specified workspace.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import shutil
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run(args):
    workspace = args.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    project = workspace / "body-and-fingers-test.casc"
    shutil.copyfile(args.sample, project)
    report = {"checks": [], "tool_count": 0}
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "cascadeur_mcp",
            "--bridge-dir",
            str(args.bridge_dir.resolve()),
            "--workspace",
            str(workspace),
            "--timeout",
            "90",
        ],
    )
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as client:
            await client.initialize()
            report["tool_count"] = len((await client.list_tools()).tools)

            async def call(name, **kw):
                value = await client.call_tool("cascadeur_" + name, kw)
                if value.is_error:
                    raise RuntimeError(name + ": " + str(value.content))
                if name == "capture_viewport":
                    assert any(x.type == "image" for x in value.content), (
                        "Missing MCP image"
                    )
                    return {"image": True}
                texts = [x.text for x in value.content if x.type == "text"]
                data = json.loads(texts[0])
                if "result" in data and ("log" in data or "messages" in data):
                    data = data["result"]
                return data

            await call("open_scene", path=str(project))
            report["capabilities"] = await call("capabilities")
            state = await call("get_state")
            report["initial_state"] = state
            rig = await call("rig_summary")
            report["finger_controls"] = rig["finger_controls"]
            tracks = [x["name"] for x in (await call("list_tracks"))["tracks"]]
            await call(
                "set_keys",
                tracks=tracks,
                frames=[0, 12, 24, 36, 48],
                interpolation="BEZIER",
            )
            names = [
                "chest_Box",
                "hand_MainPoint_r",
                "hand_Box_r",
                "f_index1_Box_r",
                "f_index4_r",
            ]
            initial = await call("get_pose", objects=names, frame=0)
            by_name = {x["name"]: x for x in initial["objects"]}
            base_hand = by_name["hand_MainPoint_r"]["global_position"]
            right_fingers = [
                x["name"] for x in rig["finger_controls"] if x["name"].endswith("_r")
            ]
            keys = []
            for f, amount, lift in [
                (0, 0, 0),
                (12, 0.4, 0.65),
                (24, 1, 1),
                (36, 0.45, 0.8),
                (48, 0, 0),
            ]:
                hand = [
                    base_hand[0] - 18 * lift,
                    base_hand[1] + 40 * lift,
                    base_hand[2] + 18 * lift,
                ]
                trs = [
                    {
                        "object": "chest_Box",
                        "rotation_delta_degrees": [0, 8 * amount, 0],
                        "reference_frame": 0,
                    },
                    {"object": "hand_MainPoint_r", "space": "global", "position": hand},
                ]
                for name in right_fingers:
                    curl = (
                        12 if "thumb" in name else 30 if "1_" in name else 42
                    ) * amount
                    trs.append(
                        {
                            "object": name,
                            "rotation_delta_degrees": [curl, 0, 0],
                            "reference_frame": 0,
                        }
                    )
                keys.append({"frame": f, "transforms": trs})
            report["animation"] = await call(
                "animate_transforms", keyframes=keys, interpolation="BEZIER"
            )
            poses = {
                str(f): await call("get_pose", objects=names, frame=f)
                for f in [0, 6, 12, 18, 24, 30, 36, 42, 48]
            }
            report["poses"] = poses

            def obj(f, name):
                return next(x for x in poses[str(f)]["objects"] if x["name"] == name)

            def angle(a, b):
                qa = a["local_rotation"]["quaternion_wxyz"]
                qb = b["local_rotation"]["quaternion_wxyz"]
                return math.degrees(
                    2
                    * math.acos(
                        min(1, abs(sum(x * y for x, y in zip(qa, qb, strict=True))))
                    )
                )

            finger_angle = angle(obj(0, "f_index1_Box_r"), obj(24, "f_index1_Box_r"))
            body_angle = angle(obj(0, "chest_Box"), obj(24, "chest_Box"))
            assert finger_angle > 10, finger_angle
            assert body_angle > 3, body_angle
            assert (
                math.dist(
                    obj(0, "hand_MainPoint_r")["global_position"],
                    obj(24, "hand_MainPoint_r")["global_position"],
                )
                > 10
            )
            assert (
                math.dist(
                    obj(0, "f_index4_r")["global_position"],
                    obj(48, "f_index4_r")["global_position"],
                )
                < 0.15
            )
            for f in poses:
                for o in poses[f]["objects"]:
                    assert all(math.isfinite(v) for v in o["global_position"])
            report["checks"] += [
                {"body_rotation_degrees": body_angle},
                {"index_rotation_degrees": finger_angle},
                "body and fingertip change at keys",
                "inbetween poses are finite",
                "fingertip returns to start",
            ]
            report["motion"] = await call(
                "sample_motion",
                objects=["f_index4_r", "hand_MainPoint_r", "foot_Box_r", "foot_Box_l"],
                first=0,
                last=48,
                step=2,
            )
            await call("save_scene", path=str(project), overwrite=True)
            await call("set_view_mode", mode="View")
            await call("select_objects", objects=[])
            await call("set_camera", position=[220, 170, 380], target=[0, 90, 0])
            for f in [0, 12, 24, 36, 48]:
                await call("set_frame", frame=f)
                await call(
                    "capture_viewport",
                    path=str(workspace / f"body-frame-{f:02d}.png"),
                    width=1000,
                    height=900,
                    overwrite=True,
                )
            report["checks"].append(
                "five full-body renders returned as MCP image content"
            )
            await call("set_range", first=0, last=48)
            await call("set_frame", frame=0)
            await call("set_frame", frame=24)
            hand = obj(24, "hand_MainPoint_r")["global_position"]
            await call(
                "set_camera",
                position=[hand[0] - 35, hand[1] + 5, hand[2] + 65],
                target=[hand[0], hand[1] - 7, hand[2] + 3],
            )
            await call(
                "capture_viewport",
                path=str(workspace / "hand-closed.png"),
                width=1000,
                height=800,
                overwrite=True,
            )
            await call("set_frame", frame=0)
            hand0 = obj(0, "hand_MainPoint_r")["global_position"]
            await call(
                "set_camera",
                position=[hand0[0] - 35, hand0[1] + 5, hand0[2] + 65],
                target=[hand0[0], hand0[1] - 7, hand0[2] + 3],
            )
            await call(
                "capture_viewport",
                path=str(workspace / "hand-open.png"),
                width=1000,
                height=800,
                overwrite=True,
            )
            report["checks"].append(
                "open and curled hand closeups returned as MCP images"
            )
            await call("set_camera", position=[220, 170, 380], target=[0, 90, 0])
            await call("save_scene", path=str(project), overwrite=True)
            await call(
                "export_fbx",
                path=str(workspace / "body-and-fingers-test.fbx"),
                mode="animation",
                overwrite=True,
            )
            report["checks"].append("native scene saved and animation FBX exported")
            await call("open_scene", path=str(project))
            loaded = await call("get_pose", objects=names, frame=24)
            for a, b in zip(loaded["objects"], poses["24"]["objects"], strict=True):
                assert math.dist(a["global_position"], b["global_position"]) < 0.15
            report["checks"].append("saved scene reopened and frame-24 positions match")
            await call("set_frame", frame=24)
            (workspace / "live-test-report.json").write_text(
                json.dumps(report, indent=2)
            )
            print(
                json.dumps(
                    {"tool_count": report["tool_count"], "checks": report["checks"]},
                    indent=2,
                )
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--bridge-dir", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
