"""Turn a character 180 deg about its pelvis on one frame by moving only hands and feet:
python turn_ends.py FRAME [prefix]  (then aplock.py solves the rest)"""
import asyncio, sys
import numpy as np
sys.path.insert(0, "..")
from mcp_call import call
rpc = lambda m, **p: asyncio.run(call(m, p))["result"]
frame = int(sys.argv[1]); Q = sys.argv[2] if len(sys.argv) > 2 else ""
ENDS = [f"{n}_{s}" for s in "lr" for n in ("hand_MainPoint", "hand_DirectionPoint", "hand_AdditionalPoint",
                                           "foot_MainPoint", "ball_MainPoint", "ball_DirectionPoint", "ball_AdditionalPoint")]
rows = rpc("get_pose", objects=[Q + "pelvis_MainPoint"] + [Q + n for n in ENDS], frame=frame)["objects"]
pos = {r["name"]: np.array(r["global_position"]) for r in rows}
c = pos.pop(Q + "pelvis_MainPoint")
tr = [dict(object=n, space="global", position=[float(2 * c[0] - v[0]), float(v[1]), float(2 * c[2] - v[2])]) for n, v in pos.items()]
print(rpc("animate_transforms", keyframes=[dict(frame=frame, transforms=tr)], interpolation="STEP")["frames"])
