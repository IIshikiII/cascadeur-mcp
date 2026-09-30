"""Deterministic AutoPosing: explicit lock flags, set and verified through Object properties.

The Locked flag of an AutoPosing controller is not reachable from Cascadeur's Python API and the
panel follows the selection only between bridge calls, so this runs client side as a sequence of
bridge calls per frame: list the controllers (ap_tools), then per controller select it, read its
Locked flag (ap_panel) and set it when it differs (ap_set_locked), re-read to verify, then Update.

Toggling a Locked flag makes Cascadeur re-solve the pose at once, which moves points that are not
locked yet (a written chest lean was undone that way). So the pose is recorded before the lock
pass and written back after it, the mode is switched on again (controllers sync to the pose) and
only then Update runs.

Default anchors are hands and feet only (user rule): everything else - pelvis, spine, chest,
neck, head, shoulders and the pelvis/chest/head direction controllers - is left to the network.
"""

# AutoPosing controller names (Object properties -> Name) of the default anchors.
DEFAULT_ANCHORS = tuple(
    "%s_%s" % (n, s) for s in "lr" for n in ("hand", "hand_dir", "hand_add", "toe", "toe_dir", "toe_add")
)


def _kind(tool):
    return "input" if tool["point"] else "direction"


async def _panel(call, kind):
    panel = await call("ap_panel", kind=kind)
    if panel.get("unfolded"):
        panel = await call("ap_panel", kind=kind)
    return panel


async def _set_lock(call, tool, want):
    """Set one controller's lock; returns (name, before, ok). One retry: a click can be missed."""
    kind = _kind(tool)
    await call("ap_select_tool", id=tool["id"])
    panel = await _panel(call, kind)
    if panel["locked"] is None:  # ankles: always active
        return panel["name"], None, True
    before = panel["locked"]
    for _ in range(2):
        if panel["locked"] == want:
            return panel["name"], before, True
        await call("ap_set_locked", locked=want, kind=kind)
        panel = await _panel(call, kind)
    return panel["name"], before, panel["locked"] == want


async def _character_points(call, character):
    controls = (await call("rig_summary"))["controls"]
    own = (lambda n: n.startswith(character)) if character else (lambda n: ":" not in n)
    return [c["name"] for c in controls if c["type"] == "Point" and own(c["name"])]


async def autopose_explicit(call, frames, anchors=None, character="", tool_seeds=None):
    """call: async (method, **params) -> result. anchors: controller names (hand_l,
    direction_controller_head, ...) or point names (hand_MainPoint_l, ...), without prefix."""
    character = character or ""
    anchors = list(anchors) if anchors else list(DEFAULT_ANCHORS)
    points = {character + a for a in anchors if "Point" in a}
    names = {a for a in anchors if "Point" not in a}
    scene = (await call("get_state"))["name"]
    all_points = await _character_points(call, character)
    report = []
    for frame in frames:
        rows = (await call("get_pose", objects=all_points, frame=frame))["objects"]
        pose = {r["name"]: r["global_position"] for r in rows}
        tools = (await call("ap_tools", character=character, frame=frame, tool_seeds=tool_seeds))["tools"]
        locked, locked_points, changed, failed = [], [], [], []
        # anchors first, then the releases (each toggle re-solves the free points)
        for pass_want in (True, False):
            for tool in tools:
                kind = _kind(tool)
                await call("ap_select_tool", id=tool["id"])
                panel = await _panel(call, kind)
                if panel["locked"] is None:
                    continue
                want = panel["name"] in names or tool["point"] in points
                if want != pass_want:
                    continue
                name, before, ok = await _set_lock(call, tool, want)
                if before is not None and before != want:
                    (changed if ok else failed).append(name)
                if want:
                    locked.append(name)
                    if tool["point"]:
                        locked_points.append(tool["point"])
        await call("set_mode", mode="autoposing", on=False)
        if failed:
            report.append(dict(frame=frame, status="FAILED to set locks: %s (not updated)" % failed,
                               locked=sorted(locked), changed=sorted(changed)))
            break
        # put the pose back (the lock toggles re-solved free points), sync, then solve
        transforms = [dict(object=n, space="global", position=[float(x) for x in v]) for n, v in pose.items()]
        for i in range(0, len(transforms), 200):
            await call("animate_transforms", keyframes=[dict(frame=frame, transforms=transforms[i:i + 200])],
                       interpolation="STEP")
        await call("ap_tools", character=character, frame=frame, tool_seeds=tool_seeds)
        before = {n: pose[n] for n in locked_points if n in pose}
        await call("call_action", action_id="AutoPosingTool.Update", expected_scene=scene)
        await call("set_mode", mode="autoposing", on=False)
        drift = 0.0
        if before:
            rows = (await call("get_pose", objects=list(before), frame=frame))["objects"]
            drift = max(
                sum((a - b) ** 2 for a, b in zip(r["global_position"], before[r["name"]])) ** 0.5 for r in rows
            )
        report.append(dict(frame=frame, status="ok", locked=sorted(locked), changed=sorted(changed),
                           anchor_drift_cm=round(drift, 2)))
    return report
