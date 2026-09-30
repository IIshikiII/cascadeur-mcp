"""Deterministic AutoPosing: explicit lock flags, set and verified through Object properties.

The Locked flag of an AutoPosing controller is not reachable from Cascadeur's Python API and the
panel follows the selection only between bridge calls, so this runs client side as a sequence of
bridge calls per frame: list the controllers (ap_tools), then per controller select it, read its
Locked flag (ap_panel) and set it when it differs (ap_set_locked), re-read to verify, then Update.

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


async def autopose_explicit(call, frames, anchors=None, character="", tool_seeds=None):
    """call: async (method, **params) -> result. anchors: controller names (hand_l,
    direction_controller_head, ...) or point names (hand_MainPoint_l, ...), without prefix."""
    character = character or ""
    anchors = list(anchors) if anchors else list(DEFAULT_ANCHORS)
    points = {character + a for a in anchors if "Point" in a}
    names = {a for a in anchors if "Point" not in a}
    scene = (await call("get_state"))["name"]
    report = []
    for frame in frames:
        tools = (await call("ap_tools", character=character, frame=frame, tool_seeds=tool_seeds))["tools"]
        locked, locked_points, changed, failed = [], [], [], []
        for tool in tools:
            kind = _kind(tool)
            await call("ap_select_tool", id=tool["id"])
            panel = await _panel(call, kind)
            if panel["locked"] is None:  # ankles: always active
                continue
            want = panel["name"] in names or tool["point"] in points
            if panel["locked"] != want:
                await call("ap_set_locked", locked=want, kind=kind)
                after = await _panel(call, kind)
                (changed if after["locked"] == want else failed).append(panel["name"])
            if want:
                locked.append(panel["name"])
                if tool["point"]:
                    locked_points.append(tool["point"])
        before = {}
        if locked_points:
            rows = (await call("get_pose", objects=locked_points, frame=frame))["objects"]
            before = {r["name"]: r["global_position"] for r in rows}
        if not failed:
            await call("call_action", action_id="AutoPosingTool.Update", expected_scene=scene)
        await call("set_mode", mode="autoposing", on=False)
        drift = 0.0
        if before:
            rows = (await call("get_pose", objects=list(before), frame=frame))["objects"]
            drift = max(
                sum((a - b) ** 2 for a, b in zip(r["global_position"], before[r["name"]])) ** 0.5 for r in rows
            )
        report.append(
            dict(
                frame=frame,
                status="FAILED to set locks: %s (not updated)" % failed if failed else "ok",
                locked=sorted(locked),
                changed=sorted(changed),
                anchor_drift_cm=round(drift, 2),
            )
        )
        if failed:
            break
    return report
