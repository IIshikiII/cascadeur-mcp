"""AutoPhysics per character test in duo_physics.casc: both characters jump in place with a
hand-made (non-ballistic) flight, so AutoPhysics must change it.

    python duo_jump.py build          keys 8/14/20/28 from anchors + AutoPosing, contacts
    python duo_jump.py sample NAME    pelvis/feet of both characters on frames 0..28 -> NAME.json
    python duo_jump.py diff A B       per-character max difference between two samples
"""
import asyncio
import json
import sys

import numpy as np

sys.path.insert(0, "..")
from mcp_call import call  # noqa: E402

Q = "character1:"
CHARS = {"manny": ("", 1.0), "quinn": (Q, -1.0)}  # prefix, forward sign along Z
ANCHORS = ["pelvis_MainPoint", "spine_04_MainPoint"] + [
    f"{n}_{s}" for s in "lr" for n in (
        "foot_MainPoint", "ball_MainPoint", "ball_DirectionPoint", "thigh_MainPoint",
        "hand_MainPoint", "hand_DirectionPoint", "hand_AdditionalPoint")]
LOWER = ("foot_", "ball_")
TRACKED = ["pelvis_MainPoint", "spine_04_MainPoint", "head_MainPoint", "foot_MainPoint_l", "hand_MainPoint_r"]


def rpc(method, **params):
    return asyncio.run(call(method, params))["result"]


def pose(names, frame):
    rows = rpc("get_pose", objects=names, frame=frame)["objects"]
    return {r["name"]: np.array(r["global_position"], float) for r in rows}


def shifted(base, prefix, fwd, body, feet, hands_back=0.0, hands_up=0.0):
    """Anchor targets: upper body shifted by `body`, feet by `feet` (x, y, z-forward in cm)."""
    out = {}
    for n in ANCHORS:
        v = base[prefix + n].copy()
        d = np.array(feet if n.startswith(LOWER) else body, float)
        d[2] *= fwd
        if n.startswith("hand_"):
            d = d + [0, hands_up, -hands_back * fwd]
        out[prefix + n] = v + d
    return out


def build():
    ids = [t["id"] for t in rpc("list_tracks")["tracks"] if t["object_count"]]
    rpc("set_keys", tracks=ids, frames=[8, 14, 20, 28], interpolation="BEZIER")
    for who, (prefix, fwd) in CHARS.items():
        base = pose([prefix + n for n in ANCHORS], 0)
        plan = {
            8: shifted(base, prefix, fwd, body=[0, -28, 6], feet=[0, 0, 0], hands_back=20, hands_up=5),
            14: shifted(base, prefix, fwd, body=[0, 35, 0], feet=[0, 35, 0], hands_up=45),
            20: shifted(base, prefix, fwd, body=[0, -28, 6], feet=[0, 0, 0], hands_back=5, hands_up=10),
            28: shifted(base, prefix, fwd, body=[0, 0, 0], feet=[0, 0, 0]),
        }
        kfs = [dict(frame=f, transforms=[dict(object=n, space="global", position=[round(float(x), 3) for x in v])
                                          for n, v in t.items()]) for f, t in plan.items()]
        rpc("animate_transforms", keyframes=kfs, interpolation="BEZIER")
        for frames in ([8, 14], [20, 28]):
            r = rpc("autopose", frames=frames, anchors=ANCHORS,
                    include_directions=False, character=prefix)
            for fr in r["frames"]:
                print(who, fr["frame"], fr["status"], "drift", fr["anchor_drift_cm"], "head", fr["head_facing"])
        contacts = [prefix + f"{n}_{s}" for s in "lr" for n in ("ball_MainPoint", "foot_Self0Point")]
        rpc("set_contacts", points=contacts, intervals=[[0, 9], [19, 28]])
    ids_all = rpc("list_tracks")["tracks"]
    print("keys", sorted({k for t in ids_all for k in t["keys"]}))


def hang():
    """Hold the flight pose of frame 14 on frames 11 and 17: a hover, impossible for physics."""
    ids = [t["id"] for t in rpc("list_tracks")["tracks"] if t["object_count"]]
    rpc("set_keys", tracks=ids, frames=[11, 17], interpolation="BEZIER")
    for who, (prefix, _) in CHARS.items():
        top = pose([prefix + n for n in ANCHORS], 14)
        kfs = [dict(frame=f, transforms=[dict(object=n, space="global", position=[round(float(x), 3) for x in v])
                                          for n, v in top.items()]) for f in (11, 17)]
        rpc("animate_transforms", keyframes=kfs, interpolation="BEZIER")
        r = rpc("autopose", frames=[11, 17], anchors=ANCHORS,
                include_directions=False, character=prefix)
        for fr in r["frames"]:
            print(who, fr["frame"], fr["status"], "drift", fr["anchor_drift_cm"], "head", fr["head_facing"])


def sample(name):
    names = [p + n for p, _ in CHARS.values() for n in TRACKED]
    data = {f: {n: v.tolist() for n, v in pose(names, f).items()} for f in range(0, 29)}
    json.dump(data, open(name + ".json", "w"))


def diff(a, b):
    A, B = json.load(open(a + ".json")), json.load(open(b + ".json"))
    for who, (prefix, _) in CHARS.items():
        worst = max(((np.linalg.norm(np.subtract(A[f][prefix + n], B[f][prefix + n])), f, n)
                     for f in A for n in TRACKED), key=lambda x: x[0])
        print("%s: max change %.1f cm (frame %s, %s)" % (who, *worst))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "build":
        build()
    elif cmd == "hang":
        hang()
    elif cmd == "sample":
        sample(sys.argv[2])
    elif cmd == "diff":
        diff(sys.argv[2], sys.argv[3])
