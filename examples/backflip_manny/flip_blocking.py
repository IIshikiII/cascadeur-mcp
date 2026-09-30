"""Backflip for UE5 Manny, blocked pose-to-pose like an animator (see cascadeur-mcp/docs/AI_GUIDE.md).

Only the MAIN controllers are placed (pelvis, chest, head, hands, feet); AutoPosing solves the rest.
Levels: 1 = story poses, 2 = breakdowns, 3 = spline fixes. Physics comes last.

    python flip_blocking.py write 16,22,32     write main controllers of these key poses
    python flip_blocking.py check 16,22,32     knee/elbow sanity of the scene poses
    python flip_blocking.py dry 16,22,32       print the targets

Pose fields (see backflip_generator.pose_at): pitch = whole-body rotation about the lateral axis
(negative = backward), lean = extra forward bend at the hips, curl = spine/head tuck, pelvis = offset
from rest (None in flight: ballistic height), hands = hand offset from the shoulder in the body frame
(x out, y up, z forward; kept shorter than the arm so the elbow never straightens and flips),
ankles = ankle offset from the hip in flight (shorter than the leg, same reason), heel = heel lift.
"""
import asyncio
import json
import sys

import numpy as np

import backflip_generator as B

POSES = {
    # level 1: story poses
    16: dict(arm=25, pitch=0, lean=35, curl=0, pelvis=[0, -32, -14], hands=[4, -38, -30], ankles=None, heel=0),
    22: dict(arm=20, pitch=-14, lean=0, curl=-5, pelvis=[0, 6, -2], hands=[3, 48, 6], ankles=None, heel=40),
    32: dict(pitch=-185, lean=35, curl=25, spine=(35, 30, 30), pelvis=None, hands=[-4, -12, 40],
             ankles=[4, -30, 15], knees_out=0.15, grab=(2, 8, 0.35), heel=0),  # rounded back, clear of the legs
    42: dict(arm=45, pitch=-360, lean=15, curl=0, pelvis=[0, -10, -3], hands=[10, -5, 40], ankles=None, heel=25),
    48: dict(arm=50, pitch=-360, lean=30, curl=0, pelvis=[0, -30, -10], hands=[6, -20, 40], ankles=None, heel=0),
    # level 2: breakdowns
    8: dict(arm=25, pitch=0, lean=-3, curl=0, pelvis=[0, 2, 0], hands=[4, 5, 50], ankles=None, heel=10),
    19: dict(arm=25, pitch=-4, lean=20, curl=0, pelvis=[0, -18, -8], hands=[3, -20, 44], ankles=None, heel=15),
    26: dict(arm=25, pitch=-60, lean=8, curl=5, pelvis=None, hands=[4, 42, 22], ankles=[0, -62, 22], heel=0),
    29: dict(arm=50, pitch=-120, lean=25, curl=18, pelvis=None, hands=[0, 10, 38], ankles=[0, -38, 30], heel=0),
    35: dict(pitch=-255, lean=35, curl=25, pelvis=None, hands=[-4, -12, 40], ankles=[0, -20, 30], heel=0),
    38: dict(arm=40, pitch=-310, lean=18, curl=8, pelvis=None, hands=[16, 5, 38], ankles=[0, -58, 22], heel=0),
    60: dict(arm=35, pitch=-360, lean=8, curl=0, pelvis=[0, -7, -3], hands=[2, -38, 14], ankles=None, heel=0),
}
MAIN = [
    "pelvis_MainPoint", "pelvis_AdditionalPoint",
    "spine_04_MainPoint", "spine_04_AdditionalPoint",
    "head_MainPoint", "head_DirectionPoint",
    "hand_MainPoint_l", "hand_DirectionPoint_l", "hand_MainPoint_r", "hand_DirectionPoint_r",
    "foot_MainPoint_l", "foot_MainPoint_r", "ball_MainPoint_l", "ball_MainPoint_r",
]
# Positions AND orientation of every end: a position-only anchor lets AutoPosing turn the torso or a
# foot 180 degrees about its own axis (it did on the inverted tuck: crossed limbs, feet inside out).
ANCHORS = ["pelvis_MainPoint", "pelvis_AdditionalPoint", "spine_04_MainPoint", "spine_04_AdditionalPoint",
           "head_MainPoint", "head_DirectionPoint"]
ANCHORS += [f"{p}_{s}" for s in "lr" for p in ("hand_MainPoint", "hand_DirectionPoint", "hand_AdditionalPoint",
                                                "foot_MainPoint", "ball_MainPoint", "ball_DirectionPoint",
                                                "ball_AdditionalPoint")]
# direction vectors that must match the target (name: (from, to))
AXES = {"pelvis": ("pelvis_MainPoint", "pelvis_AdditionalPoint"), "chest": ("spine_04_MainPoint", "spine_04_AdditionalPoint"),
        "head": ("head_MainPoint", "head_DirectionPoint")}
for _s in "lr":
    AXES.update({f"hand_dir_{_s}": (f"hand_MainPoint_{_s}", f"hand_DirectionPoint_{_s}"),
                 f"hand_add_{_s}": (f"hand_MainPoint_{_s}", f"hand_AdditionalPoint_{_s}"),
                 f"foot_toe_{_s}": (f"foot_MainPoint_{_s}", f"ball_MainPoint_{_s}"),
                 f"foot_roll_{_s}": (f"ball_MainPoint_{_s}", f"ball_AdditionalPoint_{_s}"),
                 f"hips_{_s}": ("pelvis_MainPoint", f"thigh_MainPoint_{_s}"),
                 f"shoulder_{_s}": ("spine_04_MainPoint", f"upperarm_MainPoint_{_s}")})


# Body volume as capsules (from, to, radius cm, trim the ends near joints shared with neighbours).
def _caps(p):
    c = {"belly": ("pelvis_MainPoint", "spine_02_MainPoint", 14, 0, 0),
         "chest": ("spine_02_MainPoint", "spine_04_MainPoint", 15, 0, 0),
         "neck": ("spine_04_MainPoint", "neck_01_MainPoint", 9, 0, 0),
         "head": ("neck_01_MainPoint", "head_MainPoint", 10, 0.3, 0)}
    for s in "lr":
        c.update({f"thigh_{s}": (f"thigh_MainPoint_{s}", f"calf_MainPoint_{s}", 8, 0.3, 0),
                  f"shin_{s}": (f"calf_MainPoint_{s}", f"foot_MainPoint_{s}", 5.5, 0, 0),
                  f"upperarm_{s}": (f"upperarm_MainPoint_{s}", f"lowerarm_MainPoint_{s}", 5, 0.3, 0),
                  f"forearm_{s}": (f"lowerarm_MainPoint_{s}", f"hand_MainPoint_{s}", 4, 0, 0.25)})
    return c


PAIRS = [(a, b) for s in "lr" for o in "lr" for a in (f"upperarm_{s}", f"forearm_{s}")
         for b in (f"thigh_{o}", f"shin_{o}")]
PAIRS += [(f"forearm_{s}", t) for s in "lr" for t in ("belly", "chest")]
PAIRS += [(f"{a}_{s}", t) for s in "lr" for a in ("thigh", "shin") for t in ("chest", "neck", "head")]
PAIRS += [("thigh_l", "thigh_r"), ("shin_l", "shin_r"), ("shin_l", "thigh_r"), ("shin_r", "thigh_l")]


def collisions(p, allow=1.0):
    """Capsule pairs that interpenetrate by more than `allow` cm: {pair: depth}."""
    caps = _caps(p)

    def samples(name):
        a, b, r, t0, t1 = caps[name]
        u = np.linspace(t0, 1 - t1, 24)[:, None]
        return p[a] + u * (p[b] - p[a]), r

    out = {}
    for a, b in PAIRS:
        (A, ra), (Bs, rb) = samples(a), samples(b)
        dist = np.min(np.linalg.norm(A[:, None, :] - Bs[None, :, :], axis=2))
        depth = ra + rb - dist
        if depth > allow:
            out[f"{a}~{b}"] = round(float(depth), 1)
    return out


def verify(scene, tgt, tol=25):
    """Angles between scene and target directions; anything above tol degrees is a turned part."""
    bad = {}
    for k, (a, b) in AXES.items():
        u, v = unit(scene[b] - scene[a]), unit(tgt[b] - tgt[a])
        ang = float(np.degrees(np.arccos(np.clip(u @ v, -1, 1))))
        if ang > (tol * 2 if k == "pelvis" else tol):  # pelvis vector is 3.5 cm: the rig tilts it
            bad[k] = round(ang)
    return bad


def reach(l1, l2, bend):
    """Shoulder-hand (hip-ankle) distance for a joint bent by `bend` degrees."""
    return float(np.sqrt(l1 * l1 + l2 * l2 + 2 * l1 * l2 * np.cos(np.radians(bend))))


def target(t):
    if t in (0, B.LAST):
        return dict(B.REST)
    pose = dict(POSES[t])
    if "arm" in pose:  # the hand direction is the pose; its distance sets the elbow bend
        h = np.array(pose["hands"], float)
        pose["hands"] = list(h / np.linalg.norm(h) * reach(27.8, 27.3, pose["arm"]))
    p = B.pose_at(t, pose)
    if t in GRAB_SHINS:
        p = grab_shins(t, pose, p)
    return p


GRAB_SHINS = (32, 35)


def grab_shins(t, pose, p):
    """Solve the hand offset so each hand lies on the front of its shin just below the knee."""
    def goal(q, s):
        knee, ankle = q["calf_MainPoint_" + s], q["foot_MainPoint_" + s]
        hip = q["thigh_MainPoint_" + s]
        line = unit(ankle - hip)
        front = unit((knee - hip) - ((knee - hip) @ line) * line)  # the way the knee points
        side = unit(q["thigh_MainPoint_l"] - q["thigh_MainPoint_r"]) * (1 if s == "l" else -1)
        g_front, g_side, g_along = pose.get("grab", (5, 3, 0.35))
        shin = knee + g_along * (ankle - knee)
        return shin + g_front * front + g_side * side
    h = np.array(pose["hands"], float)
    for _ in range(4):
        q = B.pose_at(t, dict(pose, hands=list(h)))
        err = goal(q, "l") - q["hand_MainPoint_l"]
        J = np.zeros((3, 3))
        for i in range(3):
            d = np.zeros(3); d[i] = 1.0
            J[:, i] = B.pose_at(t, dict(pose, hands=list(h + d)))["hand_MainPoint_l"] - q["hand_MainPoint_l"]
        h = h + np.linalg.lstsq(J, err, rcond=None)[0]
    return B.pose_at(t, dict(pose, hands=list(h)))


def unit(v):
    return v / np.linalg.norm(v)


def body_frame(p):
    up = unit(p["spine_04_MainPoint"] - p["pelvis_MainPoint"])
    lat = unit(p["thigh_MainPoint_l"] - p["thigh_MainPoint_r"])  # character's left
    fwd = unit(np.cross(lat, up))
    return up, lat, fwd


def limb_report(p):
    """Knees must point to the body's front; elbows back and/or outward; both slightly bent."""
    up, lat, fwd = body_frame(p)
    out = {}
    for s, sign in (("l", 1), ("r", -1)):
        for name, a, b, c, ok in (
            ("knee", "thigh_MainPoint_", "calf_MainPoint_", "foot_MainPoint_",
             lambda d: d @ fwd + max(d @ up, 0) > 0.3),  # in a tuck the knee points to the chest
            ("elbow", "upperarm_MainPoint_", "lowerarm_MainPoint_", "hand_MainPoint_",
             lambda d: max(-(d @ fwd) + sign * (d @ lat), -(d @ up)) > 0.2),  # back/out, or down for a forward reach
        ):
            A, M, C = p[a + s], p[b + s], p[c + s]
            line = unit(C - A)
            off = (M - A) - ((M - A) @ line) * line
            bend = np.degrees(np.arccos(np.clip(unit(M - A) @ unit(C - M), -1, 1)))
            d = unit(off) if np.linalg.norm(off) > 1e-6 else off
            out[f"{name}_{s}"] = dict(bend=round(float(bend)), fwd=round(float(d @ fwd), 2),
                                      out=round(float(sign * (d @ lat)), 2), ok=bool(ok(d)) or bend < 8)
    return out


def write(frames, full=False):
    kfs = []
    for t in frames:
        p = target(t)
        keys = list(p) if full else MAIN
        kfs.append(dict(frame=t, transforms=[
            dict(object=k, space="global", position=[round(float(x), 3) for x in p[k]]) for k in keys]))
    return asyncio.run(B.call("animate_transforms", dict(keyframes=kfs, interpolation="STEP")))["result"]


def scene_pose(t):
    names = [f"{j}_{s}" for s in "lr" for j in ("thigh_MainPoint", "calf_MainPoint", "foot_MainPoint",
                                                  "upperarm_MainPoint", "lowerarm_MainPoint", "hand_MainPoint")]
    names += ["pelvis_MainPoint", "spine_04_MainPoint"]
    names = sorted(set(names) | {n for ab in AXES.values() for n in ab} | set(B.REST))
    r = asyncio.run(B.call("get_pose", dict(frame=t, objects=names)))["result"]
    rows = r.get("objects", r) if isinstance(r, dict) else r
    return {o["name"]: np.array(o["global_position"], float) for o in rows}


if __name__ == "__main__":
    cmd, frames = sys.argv[1], [int(x) for x in sys.argv[2].split(",")]
    if cmd == "dry":
        for t in frames:
            p = target(t)
            print(t, {k: v for k, v in limb_report(p).items()})
    elif cmd == "write":
        print(write(frames))
    elif cmd == "write-full":
        print(write(frames, full=True))
    elif cmd == "check":
        for t in frames:
            sp = scene_pose(t)
            rep = limb_report(sp)
            bad = {k: v for k, v in rep.items() if not v["ok"]}
            turned = verify(sp, target(t))
            if turned:
                bad["turned_vs_target_deg"] = turned
            hits = collisions(sp)
            if hits:
                bad["intersections_cm"] = hits
            print(t, "OK" if not bad else "PROBLEM", json.dumps(bad if bad else {k: v["bend"] for k, v in rep.items()}, default=str))
