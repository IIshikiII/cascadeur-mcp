"""Standing back tuck (backflip) key poses for the UE5 Manny rig, looping into the start pose.

Scene conventions: Y up, character faces +Z, its right side is -X, cm, 30 fps assumed.
Only key poses are produced; knees/elbows/spine are refined afterwards with AutoPosing,
in-betweens with AI Inbetweening and the flight with AutoPhysics.
"""
import math
import sys

import numpy as np

sys.path.insert(0, r"C:\Users\IshikiI\Desktop\Coding\Cascadeur\VibeAnimating\cascadeur-work")
from mcp_call import call  # noqa: E402

REST = {k: np.array(v, float) for k, v in {
    "ball_AdditionalPoint_l": [24.36, 0.75, 13.16], "ball_AdditionalPoint_r": [-24.35, 0.75, 13.17],
    "ball_DirectionPoint_l": [16.25, 0.75, 22.88], "ball_DirectionPoint_r": [-16.23, 0.75, 22.89],
    "ball_MainPoint_l": [15.44, 0.75, 13.96], "ball_MainPoint_r": [-15.43, 0.75, 13.97],
    "calf_AdditionalPoint_l": [27.47, 50.33, 6.19], "calf_AdditionalPoint_r": [-27.46, 50.33, 6.21],
    "calf_MainPoint_l": [12.71, 49.56, 7.53], "calf_MainPoint_r": [-12.71, 49.57, 7.54],
    "clavicle_AdditionalPoint_l": [18.13, 151.5, -0.67], "clavicle_AdditionalPoint_r": [-18.12, 151.51, -0.66],
    "clavicle_MainPoint_l": [1.43, 145.75, 1.63], "clavicle_MainPoint_r": [-1.42, 145.75, 1.63],
    "foot_MainPoint_l": [14.09, 8.24, -0.99], "foot_MainPoint_r": [-14.09, 8.24, -0.98],
    "foot_Self0Point_l": [13.82, 0.75, -3.99], "foot_Self0Point_r": [-13.82, 0.75, -3.98],
    "hand_AdditionalPoint_l": [24.54, 84.05, 13.27], "hand_AdditionalPoint_r": [-24.53, 84.06, 13.29],
    "hand_DirectionPoint_l": [27.38, 82.45, 7.47], "hand_DirectionPoint_r": [-27.38, 82.45, 7.49],
    "hand_MainPoint_l": [25.23, 91.07, 7.84], "hand_MainPoint_r": [-25.22, 91.08, 7.86],
    "head_AdditionalPoint": [0.01, 161.45, 11.52], "head_DirectionPoint": [0.01, 176.62, 6.75],
    "head_MainPoint": [0.01, 161.59, 6.34],
    "lowerarm_AdditionalPoint_l": [32.55, 117.21, -1.86], "lowerarm_AdditionalPoint_r": [-32.55, 117.21, -1.84],
    "lowerarm_MainPoint_l": [23.34, 115.91, -3.21], "lowerarm_MainPoint_r": [-23.34, 115.92, -3.19],
    "neck_01_AdditionalPoint": [0.0, 152.21, 0.03], "neck_01_MainPoint": [0.0, 151.98, 3.48],
    "pelvis_AdditionalPoint": [0.0, 93.02, 5.38], "pelvis_MainPoint": [0.0, 92.44, 1.85],
    "spine_02_AdditionalPoint": [0.0, 105.24, 5.99], "spine_02_MainPoint": [0.0, 105.1, 0.58],
    "spine_04_AdditionalPoint": [0.01, 117.99, 11.01], "spine_04_MainPoint": [0.0, 120.79, 0.58],
    "thigh_MainPoint_l": [9.97, 92.44, 1.84], "thigh_MainPoint_r": [-9.97, 92.44, 1.85],
    "upperarm_MainPoint_l": [19.0, 143.11, 0.35], "upperarm_MainPoint_r": [-18.99, 143.11, 0.36],
}.items()}

PELVIS = ["pelvis_MainPoint", "pelvis_AdditionalPoint", "thigh_MainPoint_l", "thigh_MainPoint_r"]
LOW = ["spine_02_MainPoint", "spine_02_AdditionalPoint"]
UP = ["spine_04_MainPoint", "spine_04_AdditionalPoint", "clavicle_MainPoint_l", "clavicle_MainPoint_r",
      "clavicle_AdditionalPoint_l", "clavicle_AdditionalPoint_r", "upperarm_MainPoint_l", "upperarm_MainPoint_r",
      "neck_01_MainPoint", "neck_01_AdditionalPoint"]
HEAD = ["head_MainPoint", "head_DirectionPoint", "head_AdditionalPoint"]
FOOT = ["foot_MainPoint", "foot_Self0Point", "ball_MainPoint", "ball_DirectionPoint", "ball_AdditionalPoint"]
C0 = REST["pelvis_MainPoint"].copy()
X, Y, Z = np.eye(3)
G = 981.0 / 900.0  # cm / frame^2 at 30 fps
TAKEOFF, LANDING, LAST = 22, 42, 72
KEYS = [0, 8, 16, 22, 26, 28, 30, 31, 35, 39, 42, 47, 60, 72]


def unit(v):
    return v / np.linalg.norm(v)


def rot(axis, deg):
    axis = unit(np.asarray(axis, float))
    a = math.radians(deg)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + math.sin(a) * k + (1 - math.cos(a)) * k @ k


def frame_from(up, forward):
    u = unit(up)
    f = unit(forward - (forward @ u) * u)
    return np.column_stack([np.cross(u, f), u, f])


def ik(root, target, l1, l2, pole):
    span = target - root
    dist = min(np.linalg.norm(span), l1 + l2 - 0.05)
    axis = unit(span)
    a = (l1 * l1 - l2 * l2 + dist * dist) / (2 * dist)
    h = math.sqrt(max(l1 * l1 - a * a, 0.0))
    return root + a * axis + h * unit(pole - (pole @ axis) * axis), root + dist * axis


# ------------------------------------------------------------------ key poses
# pitch: whole-body rotation about the lateral axis through the pelvis (negative = backward).
# lean: extra forward bend of the upper body at the hips; curl: spine/head tuck.
# hands/ankles: offsets from shoulder/hip in the body frame; None = rest (arms) / planted (feet).
POSES = {
    0: dict(pitch=0, lean=0, curl=0, pelvis=[0, 0, 0], hands=None, ankles=None, heel=0),
    8: dict(pitch=0, lean=-3, curl=0, pelvis=[0, 2, 0], hands=[4, 5, 55], ankles=None, heel=10),
    16: dict(pitch=0, lean=32, curl=0, pelvis=[0, -30, -14], hands=[3, -40, -38], ankles=None, heel=0),
    22: dict(pitch=-14, lean=0, curl=-5, pelvis=[0, 6, -2], hands=[3, 58, 4], ankles=None, heel=40),
    26: dict(pitch=-60, lean=8, curl=5, pelvis=None, hands=[4, 45, 22], ankles=[0, -70, 18], heel=0),
    28: dict(pitch=-100, lean=20, curl=14, pelvis=None, hands=[0, 16, 36], ankles=[0, -46, 28], heel=0),
    30: dict(pitch=-135, lean=30, curl=21, pelvis=None, hands=[-3, -4, 40], ankles=[0, -28, 31], heel=0),
    31: dict(pitch=-160, lean=35, curl=25, pelvis=None, hands=[-4, -12, 40], ankles=[0, -20, 30], heel=0),
    35: dict(pitch=-250, lean=35, curl=25, pelvis=None, hands=[-4, -12, 40], ankles=[0, -20, 30], heel=0),
    39: dict(pitch=-322, lean=15, curl=8, pelvis=None, hands=[18, 5, 38], ankles=[0, -62, 20], heel=0),
    42: dict(pitch=-360, lean=18, curl=0, pelvis=[0, -10, -3], hands=[10, -10, 42], ankles=None, heel=25),
    47: dict(pitch=-360, lean=30, curl=0, pelvis=[0, -30, -10], hands=[6, -22, 42], ankles=None, heel=0),
    60: dict(pitch=-360, lean=8, curl=0, pelvis=[0, -7, -3], hands=[2, -38, 14], ankles=None, heel=0),
    72: dict(pitch=-360, lean=0, curl=0, pelvis=[0, 0, 0], hands=None, ankles=None, heel=0),
}
Y_TO = POSES[22]["pelvis"][1]
Y_LD = POSES[42]["pelvis"][1]
V0 = (Y_LD - Y_TO + 0.5 * G * (LANDING - TAKEOFF) ** 2) / (LANDING - TAKEOFF)


def pelvis_offset(t, pose):
    if pose["pelvis"] is not None:
        return np.array(pose["pelvis"], float)
    tau = t - TAKEOFF  # ballistic flight, in place (loop needs zero travel)
    return np.array([0.0, Y_TO + V0 * tau - 0.5 * G * tau * tau, 0.0])


def foot_contact(side, heel):
    """Planted foot, heel lifted `heel` degrees around the ball of the foot."""
    ball = REST["ball_MainPoint_" + side]
    r = rot(X, heel)
    return {k: ball + r @ (REST[k + "_" + side] - ball) for k in FOOT}


def natural_spline(xs, ys, rest_start=True):
    """C2 cubic spline through (xs, ys); ys may be vectors. Returns f(t).
    rest_start clamps zero velocity at xs[0] (the loop starts from standing still)."""
    xs = np.asarray(xs, float)
    ys = np.asarray(ys, float).reshape(len(xs), -1)
    n = len(xs) - 1
    h = np.diff(xs)
    A = np.zeros((n + 1, n + 1))
    B = np.zeros((n + 1, ys.shape[1]))
    A[0, 0] = A[n, n] = 1.0
    if rest_start:
        A[0, 0], A[0, 1] = 2 * h[0], h[0]
        B[0] = 3 * (ys[1] - ys[0]) / h[0]
    for i in range(1, n):
        A[i, i - 1], A[i, i], A[i, i + 1] = h[i - 1], 2 * (h[i - 1] + h[i]), h[i]
        B[i] = 3 * ((ys[i + 1] - ys[i]) / h[i] - (ys[i] - ys[i - 1]) / h[i - 1])
    c = np.linalg.solve(A, B)
    b = np.array([(ys[i + 1] - ys[i]) / h[i] - h[i] * (2 * c[i] + c[i + 1]) / 3 for i in range(n)])
    dd = np.array([(c[i + 1] - c[i]) / (3 * h[i]) for i in range(n)])

    def f(t):
        i = int(np.clip(np.searchsorted(xs, t, side="right") - 1, 0, n - 1))
        s = t - xs[i]
        v = ys[i] + b[i] * s + c[i] * s * s + dd[i] * s ** 3
        return v if v.size > 1 else float(v[0])

    return f


def hermite(t, t0, t1, p0, p1, v0, v1):
    s = (t - t0) / (t1 - t0)
    dt = t1 - t0
    return ((2 * s ** 3 - 3 * s ** 2 + 1) * p0 + (s ** 3 - 2 * s ** 2 + s) * v0 * dt
            + (-2 * s ** 3 + 3 * s ** 2) * p1 + (s ** 3 - s ** 2) * v1 * dt)


REST_HANDS = [float(REST["hand_MainPoint_l"][0] - REST["upperarm_MainPoint_l"][0]),
              float(REST["hand_MainPoint_l"][1] - REST["upperarm_MainPoint_l"][1]),
              float(REST["hand_MainPoint_l"][2] - REST["upperarm_MainPoint_l"][2])]
_K = sorted(k for k in POSES if k <= LANDING)
PITCH = natural_spline(_K, [POSES[k]["pitch"] for k in _K])
LEAN = natural_spline(_K, [POSES[k]["lean"] for k in _K])
CURL = natural_spline(_K, [POSES[k]["curl"] for k in _K])
HANDS = natural_spline(_K, [POSES[k]["hands"] or REST_HANDS for k in _K])
_GROUND = [k for k in _K if k <= TAKEOFF]
HEEL = natural_spline(_GROUND, [POSES[k]["heel"] for k in _GROUND])
PELVIS_Z = natural_spline(_GROUND, [POSES[k]["pelvis"][2] for k in _GROUND])


def _contact_ankle_body(t):
    """Planted ankle at key t as a body-frame offset from the left hip (for flight continuity)."""
    pose = dict(POSES[t])
    body = rot(X, pose["pitch"])
    hip = C0 + np.array(pose["pelvis"], float) + body @ (REST["thigh_MainPoint_l"] - C0)
    return body.T @ (foot_contact("l", pose["heel"])["foot_MainPoint"] - hip)


_AIR = [TAKEOFF] + [k for k in _K if TAKEOFF < k < LANDING] + [LANDING]
ANKLES = natural_spline(_AIR, [_contact_ankle_body(k) if k in (TAKEOFF, LANDING) else POSES[k]["ankles"] for k in _AIR], rest_start=False)


def pelvis_height(t):
    ys = {k: POSES[k]["pelvis"][1] for k in _GROUND}
    if t <= 16:
        return natural_spline([0, 8, 16], [ys[0], ys[8], ys[16]])(t)
    if t <= TAKEOFF:  # push-off accelerates into the flight's take-off velocity
        return hermite(t, 16, TAKEOFF, ys[16], Y_TO, 0.0, V0)
    tau = t - TAKEOFF
    return Y_TO + V0 * tau - 0.5 * G * tau * tau


def arc_hands(t):
    """Arm swing 16->22 (behind-low to overhead) as an arc around the shoulder: a straight-line
    spline passes the hand next to the shoulder and folds the arm (chicken-wing elbows)."""
    if not 16 < t < TAKEOFF:
        return HANDS(t)
    a, b = np.array(HANDS(16)), np.array(HANDS(TAKEOFF))
    u = (t - 16) / (TAKEOFF - 16)
    w = u * u * (3 - 2 * u)
    # angle in the sagittal (y up, z forward) plane; swing down past the hips and forward (through +z)
    ta, tb = math.atan2(a[2], a[1]), math.atan2(b[2], b[1])
    while tb > ta:
        tb -= 2 * math.pi
    th = (1 - w) * ta + w * tb
    ra, rb = math.hypot(a[1], a[2]), math.hypot(b[1], b[2])
    r = (1 - w) * ra + w * rb
    return np.array([(1 - w) * a[0] + w * b[0], r * math.cos(th), r * math.sin(th)])


def continuous_pose(t):
    """Pose parameters at any frame 0..LANDING from smooth curves through the key poses."""
    air = TAKEOFF < t < LANDING
    return dict(
        pitch=PITCH(t), lean=LEAN(t), curl=CURL(t),
        pelvis=[0.0, pelvis_height(t), PELVIS_Z(t) if t <= TAKEOFF else 0.0],
        hands=list(arc_hands(t)),
        ankles=list(ANKLES(t)) if air else None,
        heel=HEEL(t) if t <= TAKEOFF else POSES[LANDING]["heel"],
    )


def pose_at(t, pose=None):
    pose = pose or POSES[t]
    body = rot(X, pose["pitch"])
    d = pelvis_offset(t, pose)

    def world(x):
        return C0 + d + body @ (x - C0)

    p = {k: world(REST[k]) for k in PELVIS}
    lean, curl = pose["lean"], pose["curl"]
    r_low, r_up = rot(X, lean * 0.45), rot(X, lean * 0.55 + curl * 0.4)
    if "spine" in pose:  # (lumbar, thoracic, neck) flexion in degrees: a rounded back, not a hinge
        r_low, r_up = rot(X, pose["spine"][0]), rot(X, pose["spine"][1])
    piv = REST["pelvis_MainPoint"]
    loc = {k: piv + r_low @ (REST[k] - piv) for k in LOW + UP + HEAD}
    piv2 = loc["spine_02_MainPoint"].copy()
    for k in UP + HEAD:
        loc[k] = piv2 + r_up @ (loc[k] - piv2)
    neck = loc["neck_01_MainPoint"].copy()
    r_head = rot(X, pose["spine"][2] if "spine" in pose else curl * 0.6)
    for k in HEAD:
        loc[k] = neck + r_head @ (loc[k] - neck)
    for k, v in loc.items():
        p[k] = world(v)
    upper = body @ r_up @ r_low

    for s in "rl":  # arms
        sh, e0, w0 = p["upperarm_MainPoint_" + s], REST["lowerarm_MainPoint_" + s], REST["hand_MainPoint_" + s]
        l1 = np.linalg.norm(e0 - REST["upperarm_MainPoint_" + s])
        l2 = np.linalg.norm(w0 - e0)
        if pose["hands"] is None:
            offset = upper @ (w0 - REST["upperarm_MainPoint_" + s])
        else:
            hx, hy, hz = pose["hands"]
            offset = upper @ np.array([hx if s == "l" else -hx, hy, hz], float)
        # Elbows point outward and slightly back in the body frame: always perpendicular to a
        # sagittal arm swing, so the IK plane never degenerates (the rest-bend pole flipped).
        outward = X if s == "l" else -X
        sh0 = REST["upperarm_MainPoint_" + s]
        line = unit(w0 - sh0)
        rest_bend = unit((e0 - sh0) - ((e0 - sh0) @ line) * line)
        blend = min(max((t - 1) / 7.0, 0.0), 1.0)  # rest bend at the start, outward once arms swing
        blend = blend * blend * (3 - 2 * blend)
        pole = unit((1 - blend) * rest_bend + blend * unit(outward - 0.6 * Z - 0.2 * Y))
        e, w = ik(sh, sh + offset, l1, l2, upper @ pole)
        p["lowerarm_MainPoint_" + s], p["hand_MainPoint_" + s] = e, w
        axis = REST["lowerarm_AdditionalPoint_" + s] - e0  # hinge helper follows the real bend plane
        # hinge normal of the IK plane (shoulder, wrist, pole): continuous even for a straight arm
        rest_hinge = unit(np.cross(line, rest_bend))
        sign = 1.0 if rest_hinge @ unit(axis) >= 0 else -1.0
        hinge = sign * unit(np.cross(unit(w - sh), upper @ pole))
        along = unit(w - e)
        a_rest = unit(axis)
        # keep the rest helper's tilt along the forearm, rotate the rest about the hinge
        k_along = a_rest @ unit(w0 - e0)
        p["lowerarm_AdditionalPoint_" + s] = e + np.linalg.norm(axis) * unit(
            k_along * along + math.sqrt(max(1 - k_along ** 2, 0.0)) * unit(hinge - (hinge @ along) * along))
        a = unit(upper @ (w0 - e0))
        b = unit(w - e)
        cr = np.cross(a, b)
        rr = rot(cr, math.degrees(math.atan2(np.linalg.norm(cr), a @ b))) if np.linalg.norm(cr) > 1e-8 else np.eye(3)
        for k in ("hand_DirectionPoint_", "hand_AdditionalPoint_"):
            p[k + s] = w + rr @ upper @ (REST[k + s] - w0)

    for s in "rl":  # legs
        hip, k0, a0 = p["thigh_MainPoint_" + s], REST["calf_MainPoint_" + s], REST["foot_MainPoint_" + s]
        l1 = np.linalg.norm(k0 - REST["thigh_MainPoint_" + s])
        l2 = np.linalg.norm(a0 - k0)
        side = X if s == "l" else -X
        pole = body @ unit(Z + pose.get("knees_out", 0.0) * side)  # knees forward (and apart)
        if pose["ankles"] is None:
            feet = foot_contact(s, pose["heel"])
        else:
            ax, ay, az = pose["ankles"]
            target = hip + body @ np.array([ax if s == "l" else -ax, ay, az], float)
            knee, ankle = ik(hip, target, l1, l2, pole)
            r_foot = frame_from(knee - ankle, body @ (Z + 0.3 * Y)) @ frame_from(k0 - a0, Z).T
            r_foot = rot(r_foot @ X, 35) @ r_foot  # pointed toes in the air
            feet = {k: ankle + r_foot @ (REST[k + "_" + s] - a0) for k in FOOT}
        knee, _ = ik(hip, feet["foot_MainPoint"], l1, l2, pole)
        for k in FOOT:
            p[k + "_" + s] = feet[k]
        p["calf_MainPoint_" + s] = knee
        p["calf_AdditionalPoint_" + s] = knee + body @ (REST["calf_AdditionalPoint_" + s] - k0)
    return p


def keyframes(only=None):
    out = []
    for t in only or KEYS:
        if t == 0:
            continue  # the scene's own rest key
        pts = dict(REST) if t == LAST else pose_at(t)  # exact loop: last frame == rest pose
        out.append(dict(frame=t, transforms=[
            dict(object=k, space="global", position=[round(float(x), 3) for x in v]) for k, v in pts.items()]))
    return out


if __name__ == "__main__":
    import asyncio

    if "--dense-dry" in sys.argv or "--dense" in sys.argv:
        frames = list(range(1, LANDING + 1))
        poses = {t: pose_at(t, continuous_pose(t)) for t in frames}
        poses[0] = dict(REST)
        names = ["pelvis_MainPoint", "head_MainPoint", "hand_MainPoint_r", "calf_MainPoint_l", "foot_MainPoint_l"]
        for n in names:
            Xs = np.array([poses[t][n] for t in range(0, LANDING + 1)])
            j = np.linalg.norm(Xs[3:] - 3 * Xs[2:-1] + 3 * Xs[1:-2] - Xs[:-3], axis=1)
            print(f"{n:18s} jerk max {j.max():6.2f} at {int(j.argmax()) + 1}")
        for t in (22, 26, 28, 30, 31, 35, 39, 42):
            print(t, "pitch %.0f" % continuous_pose(t)["pitch"], "pelvis y %.1f" % poses[t]["pelvis_MainPoint"][1])
        if "--dense" in sys.argv:
            kfs = [dict(frame=t, transforms=[dict(object=k, space="global", position=[round(float(x), 3) for x in v])
                                             for k, v in poses[t].items()]) for t in frames]
            print(asyncio.run(call("animate_transforms", dict(keyframes=kfs, interpolation="BEZIER")))["result"])
    elif "--dry" in sys.argv:
        for t in KEYS:
            p = pose_at(t)
            print(t, "pelvis", np.round(p["pelvis_MainPoint"], 1), "head", np.round(p["head_MainPoint"], 1),
                  "footR", np.round(p["foot_MainPoint_r"], 1), "handR", np.round(p["hand_MainPoint_r"], 1))
        gap = max(np.linalg.norm(pose_at(0)[k] - pose_at(LAST)[k]) for k in REST)
        err = max(np.linalg.norm(pose_at(0)[k] - REST[k]) for k in REST)
        print("loop gap", round(gap, 4), "rest error", round(err, 4), "V0", round(V0, 2))
    else:
        only = [int(x) for x in sys.argv[1].split(",")] if len(sys.argv) > 1 else None
        r = asyncio.run(call("animate_transforms", dict(keyframes=keyframes(only), interpolation="BEZIER")))
        print(r["result"])
