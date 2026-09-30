"""LEGACY (inferred locks, extra anchors): superseded by turn_ends.py + apose.py.

Two-character smoke test in duo_test.casc (run from cascadeur-work/animations as duo_test.py): UE5 Manny + UE5 Quinn (namespace "character1:").

Only anchor points are written; AutoPosing solves the rest of each body.

    python duo_test.py keys F,F..     key every track of both characters (STEP)
    python duo_test.py face           frame 0: Quinn turns to face Manny, pelvis at z=DIST
    python duo_test.py five           frame 20: Manny's right hand meets Quinn's left hand
    python duo_test.py solve F who    AutoPosing for one character (manny | quinn) on frame F
    python duo_test.py report F       positions of both characters on frame F
"""
import asyncio
import json
import sys

import numpy as np

sys.path.insert(0, "..")
from mcp_call import call  # noqa: E402

Q = "character1:"
QUINN_SEED = ["cbab1ed7-913b-4b29-99a3-bf5e026b9f99"]  # read with autopose_seed after a click
DIST = 100.0  # Quinn's pelvis on z = DIST, Manny's stays near z = 0
BODY = ["pelvis_MainPoint", "spine_04_MainPoint"]
TURN = [f"{n}_{s}" for s in "lr" for n in ("thigh_MainPoint", "upperarm_MainPoint", "hand_MainPoint", "hand_DirectionPoint", "hand_AdditionalPoint")]
FEET = [f"{n}_{s}" for s in "lr" for n in ("foot_MainPoint", "ball_MainPoint", "ball_DirectionPoint")]
REPORT = ["pelvis_MainPoint", "spine_04_MainPoint", "head_MainPoint", "hand_MainPoint_r", "hand_MainPoint_l",
          "foot_MainPoint_r", "foot_MainPoint_l", "ball_MainPoint_r", "ball_MainPoint_l"]


def rpc(method, **params):
    return asyncio.run(call(method, params))["result"]


def pose(names, frame):
    rows = rpc("get_pose", objects=names, frame=frame)["objects"]
    return {r["name"]: np.array(r["global_position"], float) for r in rows}


def write(frame, positions):
    trs = [dict(object=n, space="global", position=[round(float(x), 3) for x in v]) for n, v in positions.items()]
    return rpc("animate_transforms", keyframes=[dict(frame=frame, transforms=trs)], interpolation="STEP")


def solve(frame, who, anchors, release=()):
    params = dict(frames=[frame], anchors=anchors, release=list(release), include_directions=False)
    if who == "quinn":
        params.update(character=Q, tool_seeds=QUINN_SEED)
    r = rpc("autopose", **params)["frames"][0]
    other = [n for n, v in r["moved_cm"].items() if n.startswith(Q) != (who == "quinn")]
    print(frame, who, r["status"], "drift", r["anchor_drift_cm"], "controllers", r["controllers"],
          "missing", r["missing_anchors"], "OTHER CHARACTER MOVED" if other else "other character untouched")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "keys":
        frames = [int(x) for x in sys.argv[2].split(",")]
        ids = [t["id"] for t in rpc("list_tracks")["tracks"] if t["object_count"]]
        print(rpc("set_keys", tracks=ids, frames=frames, interpolation="STEP"))
    elif cmd == "face":
        names = BODY + FEET + TURN
        m = pose(names, 0)
        # Quinn stands like Manny, turned 180 degrees about Y: (x, y, z) -> (-x, y, DIST - z).
        # A rotation keeps sides: Manny's left foot maps to Quinn's left foot (now at -X).
        # A turn is a task that needs the shoulders: thighs and upperarms carry the new facing of
        # pelvis and chest (their direction controllers still point the old way). Everywhere else
        # shoulders and head stay with AutoPosing.
        target = {Q + n: np.array([-v[0], v[1], DIST - v[2]]) for n, v in m.items()}
        for n in BODY + TURN:  # Quinn's pelvis sits 1.7 cm higher than Manny's (rest poses)
            target[Q + n] = target[Q + n] + [0, 1.7, 0]
        for f in (0, 20):
            write(f, target)
            solve(f, "quinn", names)
    elif cmd == "five":
        meet = np.array([-20.0, 150.0, DIST / 2])
        write(20, {"hand_MainPoint_r": meet + [0, 0, -3], Q + "hand_MainPoint_l": meet + [0, 0, 3]})
        free = ["hand_MainPoint_l"]
        solve(20, "manny", BODY + FEET + ["hand_MainPoint_r"], release=free)
        # Quinn keeps her thighs: her pelvis direction controller still points the pre-turn way.
        # The raised hand's orientation points were locked by `face`; the network picks them now.
        thighs = ["thigh_MainPoint_l", "thigh_MainPoint_r"]
        solve(20, "quinn", BODY + FEET + thighs + ["hand_MainPoint_l"],
              release=["hand_DirectionPoint_l", "hand_AdditionalPoint_l"])
    elif cmd == "solve":
        f, who = int(sys.argv[2]), sys.argv[3]
        solve(f, who, BODY + FEET)
    elif cmd == "report":
        p = pose(REPORT + [Q + n for n in REPORT], int(sys.argv[2]))
        print(json.dumps({n: np.round(v, 1).tolist() for n, v in p.items()}))
