"""Midpoint keys between existing keys of flip_blocking.casc, averaged through the rig hierarchy.

Every Box is averaged relative to its parent Box (slerp), every Point in the frame of its own Box,
so limbs travel on arcs, keep their length and a left part is only ever mixed with the same left
part. The root (pelvis_Box) turns as an angle in the planned direction of the flip. Planted feet stay
put in the world and the knee is re-seated. The result is only a baseline: it is checked in the scene
and then refined (big masses + AutoPosing).

    python flip_midpoints.py dry 8,27        report the baseline poses
    python flip_midpoints.py write 8,27      write points + orientation boxes (STEP keys)
    python flip_midpoints.py check 8,27      sides / limbs / collisions of the SCENE poses
"""
import asyncio
import json
import sys

import numpy as np

import backflip_generator as B
import flip_blocking as F

PARENT = {"pelvis_Box": None, "spine_02_Box": "pelvis_Box", "spine_04_Box": "spine_02_Box",
          "neck_01_Box": "spine_04_Box", "head_Box": "neck_01_Box"}
for _s in "lr":
    PARENT.update({f"clavicle_Box_{_s}": "spine_04_Box", f"upperarm_Box_{_s}": f"clavicle_Box_{_s}",
                   f"lowerarm_Box_{_s}": f"upperarm_Box_{_s}", f"hand_Box_{_s}": f"lowerarm_Box_{_s}",
                   f"thigh_Box_{_s}": "pelvis_Box", f"calf_Box_{_s}": f"thigh_Box_{_s}",
                   f"foot_Box_{_s}": f"calf_Box_{_s}", f"ball_Box_{_s}": f"foot_Box_{_s}"})
# boxes whose rotation is written (orientation of the ends and the trunk); limb segments follow the points
WRITE_BOXES = ["pelvis_Box", "spine_02_Box", "spine_04_Box", "neck_01_Box", "head_Box"] + \
    [f"{b}_Box_{s}" for s in "lr" for b in ("clavicle", "hand", "foot", "ball")]
PLAN = {0: 0, 16: 0, 22: -14, 26: -60, 29: -120, 32: -185, 35: -255, 38: -310, 42: -360, 48: -360, 72: -360}
GROUND = [(0, 22), (42, 72)]
# Arm swings that must go forward through the bottom (the shortest rotation would abduct sideways).
SWING = {(16, 22): +1}
M = np.diag([-1.0, 1, 1])


def point_box(name):
    base = name.rsplit("_", 1)[0] if name.endswith(("_l", "_r")) else name
    side = name[-2:] if name.endswith(("_l", "_r")) else ""
    part = base.split("_Main")[0].split("_Additional")[0].split("_Direction")[0].split("_Self0")[0]
    table = {"pelvis": "pelvis_Box", "spine_02": "spine_02_Box", "spine_04": "spine_04_Box",
             "neck_01": "neck_01_Box", "head": "head_Box", "clavicle": "clavicle_Box", "upperarm": "upperarm_Box",
             "lowerarm": "lowerarm_Box", "hand": "hand_Box", "thigh": "thigh_Box", "calf": "calf_Box",
             "foot": "foot_Box", "ball": "ball_Box"}
    return table[part] + side


# ---------------------------------------------------------------- quaternions (w, x, y, z)
def qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array([w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                     w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2])


def qconj(q):
    return np.array([q[0], -q[1], -q[2], -q[3]])


def qrot(q, v):
    return qmul(qmul(q, np.array([0.0, *v])), qconj(q))[1:]


def slerp(a, b, u):
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    d = a @ b
    if d < 0:
        b, d = -b, -d
    if d > 0.9995:
        q = a + u * (b - a)
        return q / np.linalg.norm(q)
    th = np.arccos(d)
    return (np.sin((1 - u) * th) * a + np.sin(u * th) * b) / np.sin(th)


def qexp(rv):
    ang = np.linalg.norm(rv)
    if ang < 1e-9:
        return np.array([1.0, 0, 0, 0])
    return np.array([np.cos(ang / 2), *(np.sin(ang / 2) * rv / ang)])


def qlog(q):
    q = q / np.linalg.norm(q)
    if q[0] < 0:
        q = -q
    v = q[1:]
    s = np.linalg.norm(v)
    if s < 1e-9:
        return np.zeros(3)
    return 2 * np.arctan2(s, q[0]) * v / s


def qmirror(q):  # reflection x -> -x applied to a rotation
    return np.array([q[0], q[1], -q[2], -q[3]])


# ---------------------------------------------------------------- scene io
def read_pose(t):
    names = list(B.REST) + list(PARENT)
    r = asyncio.run(B.call("get_pose", dict(frame=t, objects=names)))["result"]
    pos, rot = {}, {}
    for o in r["objects"]:
        pos[o["name"]] = np.array(o["global_position"], float)
        gr = o.get("global_rotation")
        if isinstance(gr, dict) and "quaternion_wxyz" in gr:
            rot[o["name"]] = np.array(gr["quaternion_wxyz"], float)
    return pos, rot


def plan(t):
    ks = sorted(PLAN)
    return float(np.interp(t, ks, [PLAN[k] for k in ks]))


def keys_in_scene():
    r = asyncio.run(B.call("list_tracks", {}))["result"]
    body = [tr for tr in r["tracks"] if tr["name"] == "Body"][0]
    return sorted(body["keys"])


# ---------------------------------------------------------------- the blend
def to_local(pos, rot):
    """Every box relative to its parent box, every point in the frame of its own box."""
    lb, lp = {}, {}
    for b, par in PARENT.items():
        if par is None:
            continue
        lb[b] = (qrot(qconj(rot[par]), pos[b] - pos[par]), qmul(qconj(rot[par]), rot[b]))
    for n in B.REST:
        bx = point_box(n)
        lp[n] = qrot(qconj(rot[bx]), pos[n] - pos[bx])
    return lb, lp


def midpoint(t, a, b, A, Bp):
    (pa, ra), (pb, rb) = A, Bp
    u = (t - a) / (b - a)  # position of the new key inside the interval
    # root rotation: as an angle, in the planned direction
    rel = qlog(qmul(rb["pelvis_Box"], qconj(ra["pelvis_Box"])))
    want = np.radians(plan(b) - plan(a))
    if abs(rel[0] - want) > np.pi:  # the short way round is the wrong way: go the long way about X
        rel = rel + np.array([2 * np.pi * np.sign(want - rel[0]), 0, 0])
    f = (plan(t) - plan(a)) / (plan(b) - plan(a)) if abs(plan(b) - plan(a)) > 1e-6 else u
    root_rot = qmul(qexp(f * rel), ra["pelvis_Box"])
    if a >= 22 and b <= 42 and not (a == 22 and b == 22):  # airborne: quadratic through 22, 32, 42
        pts = {k: read_cache[k][0]["pelvis_Box"] for k in (22, 32, 42)}
        coef = np.polyfit([22, 32, 42], np.array([pts[22], pts[32], pts[42]]), 2)
        root_pos = np.array([np.polyval(coef[:, i], t) for i in range(3)])
    else:
        root_pos = (1 - u) * pa["pelvis_Box"] + u * pb["pelvis_Box"]
    la, lpa = to_local(pa, ra)
    lbb, lpb = to_local(pb, rb)
    wpos, wrot = {"pelvis_Box": root_pos}, {"pelvis_Box": root_rot}
    q0 = REST_ROT["pelvis_Box"]
    to_std_a = qmul(q0, qconj(ra["pelvis_Box"]))  # body frame of key a -> standing frame
    to_std_b = qmul(q0, qconj(rb["pelvis_Box"]))
    from_std = qmul(root_rot, qconj(q0))  # standing frame -> the new body frame
    for b_ in PARENT:  # parents come before children in PARENT's insertion order
        par = PARENT[b_]
        if par is None:
            continue
        lp_ = (1 - u) * la[b_][0] + u * lbb[b_][0]
        lr_ = slerp(la[b_][1], lbb[b_][1], u)
        wrot[b_] = qmul(wrot[par], lr_)
        swing = next((v for (s0, s1), v in SWING.items() if s0 <= a and b <= s1), 0)
        if b_.startswith("upperarm_Box") and swing:
            s_ = b_[-1]
            da = qrot(to_std_a, pa[f"hand_MainPoint_{s_}"] - pa[f"upperarm_MainPoint_{s_}"])
            db = qrot(to_std_b, pb[f"hand_MainPoint_{s_}"] - pb[f"upperarm_MainPoint_{s_}"])
            fa, fb = np.arctan2(da[2], -da[1]), np.arctan2(db[2], -db[1])  # 0 = down, +pi/2 = forward
            d = (fb - fa) % (2 * np.pi) if swing > 0 else -((fa - fb) % (2 * np.pi))
            turn = qexp(np.array([-u * d, 0.0, 0.0]))  # about the lateral axis, down -> forward -> up
            wrot[b_] = qmul(from_std, qmul(turn, qmul(to_std_a, ra[b_])))
        wpos[b_] = wpos[par] + qrot(wrot[par], lp_)
    pose = {n: wpos[point_box(n)] + qrot(wrot[point_box(n)], (1 - u) * lpa[n] + u * lpb[n]) for n in B.REST}
    for g0, g1 in GROUND:  # planted feet: world blend, then re-seat the knee
        if g0 <= a and b <= g1:
            for n in pose:
                if n.startswith(("foot_", "ball_")):
                    pose[n] = (1 - u) * pa[n] + u * pb[n]
            for s in "lr":
                for bx in (f"foot_Box_{s}", f"ball_Box_{s}"):
                    wpos[bx] = (1 - u) * pa[bx] + u * pb[bx]
                    wrot[bx] = slerp(ra[bx], rb[bx], u)
                hip, ank = pose[f"thigh_MainPoint_{s}"], pose[f"foot_MainPoint_{s}"]
                l1 = np.linalg.norm(B.REST[f"calf_MainPoint_{s}"] - B.REST[f"thigh_MainPoint_{s}"])
                l2 = np.linalg.norm(B.REST[f"foot_MainPoint_{s}"] - B.REST[f"calf_MainPoint_{s}"])
                old = pose[f"calf_MainPoint_{s}"]
                knee, _ = B.ik(hip, ank, l1, l2, old - hip)
                pose[f"calf_AdditionalPoint_{s}"] += knee - old
                pose[f"calf_MainPoint_{s}"] = knee
    for n in list(pose):  # exact symmetry
        if n.endswith("_l"):
            r = n[:-2] + "_r"
            m = (pose[n] + M @ pose[r]) / 2
            pose[n], pose[r] = m, M @ m
        elif not n.endswith("_r"):
            pose[n] = np.array([0.0, pose[n][1], pose[n][2]])
    for bx in list(wrot):
        if bx.endswith("_l"):
            r = bx[:-2] + "_r"
            # left/right boxes are not mirror images of each other: they differ by 180 deg about
            # their own X. C maps a mirrored right box into the left box's convention (from rest).
            C = qmul(qconj(qmirror(REST_ROT[r])), REST_ROT[bx])
            q = slerp(wrot[bx], qmul(qmirror(wrot[r]), C), 0.5)
            wrot[bx], wrot[r] = q, qmul(qmirror(q), qconj(C))
    return pose, wrot


read_cache = {}
REST_ROT = {}


def neighbours(t, keys):
    return max(k for k in keys if k < t), min(k for k in keys if k > t)


def build(frames):
    keys = keys_in_scene()
    if not REST_ROT:
        REST_ROT.update(read_pose(0)[1])
    out = {}
    for t in frames:
        a, b = neighbours(t, keys)
        for k in (a, b, 22, 32, 42):
            if k not in read_cache:
                read_cache[k] = read_pose(k)
        out[t] = (a, b) + midpoint(t, a, b, read_cache[a], read_cache[b])
    return out


if __name__ == "__main__":
    cmd, frames = sys.argv[1], [int(x) for x in sys.argv[2].split(",")]
    if cmd in ("dry", "write"):
        res = build(frames)
        for t, (a, b, pose, rot) in res.items():
            rep = F.limb_report(pose)
            left_ok = all(pose[k][0] > 0 for k in pose if k.endswith("_l") and not k.startswith(("pelvis", "spine")))
            print(t, f"between {a} and {b}:", "sides", "ok" if left_ok else "SWAPPED",
                  {k: (v["bend"], "ok" if v["ok"] else "BAD") for k, v in rep.items()},
                  "hits", F.collisions(pose, allow=0.5))
        if cmd == "write":
            kfs = []
            for t, (a, b, pose, rot) in res.items():
                tr = [dict(object=n, space="global", position=[round(float(x), 3) for x in v]) for n, v in pose.items()]
                tr += [dict(object=bx, space="global", rotation_quaternion_wxyz=[round(float(x), 6) for x in rot[bx]])
                       for bx in WRITE_BOXES]
                kfs.append(dict(frame=t, transforms=tr))
            print(asyncio.run(B.call("animate_transforms", dict(keyframes=kfs, interpolation="STEP")))["result"]["frames"])
    elif cmd == "check":
        for t in frames:
            sp = F.scene_pose(t)
            rep = F.limb_report(sp)
            sides = {k[:-2]: round(float(sp[k][0]), 1) for k in sp if k.endswith("_l") and sp[k][0] < 0}
            print(t, "SIDES SWAPPED " + json.dumps(sides) if sides else "sides ok",
                  {k: (v["bend"], "ok" if v["ok"] else "BAD") for k, v in rep.items()},
                  "hits", F.collisions(sp, allow=0.5))
