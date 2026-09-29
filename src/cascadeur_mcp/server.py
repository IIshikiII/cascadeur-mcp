from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ImageContent, TextContent, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .bridge import Bridge, BridgeError

Frame = Annotated[int, Field(ge=0, le=100000)]
Names = Annotated[list[str], Field(min_length=1, max_length=200)]
Frames = Annotated[list[Frame], Field(min_length=1, max_length=500)]
Vector = tuple[float, float, float]
Interpolation = Literal[
    "BEZIER", "CLAMPED_BEZIER", "LOW_AMPLITUDE_BEZIER", "LINEAR", "STEP", "FIXED"
]


class Transform(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    object: str = Field(
        description="Exact object ID or unique name. Prefer Point/Box rig controls."
    )
    space: Literal["local", "global"] = "local"
    position: Vector | None = None
    rotation_quaternion_wxyz: tuple[float, float, float, float] | None = None
    rotation_delta_degrees: Vector | None = Field(
        default=None,
        description="Post-multiply reference rotation by local XYZ delta, in degrees.",
    )
    reference_frame: Frame = 0

    @model_validator(mode="after")
    def check(self):
        if (
            self.rotation_quaternion_wxyz is not None
            and self.rotation_delta_degrees is not None
        ):
            raise ValueError("Provide an absolute rotation or a delta, not both.")
        if (
            self.position is None
            and self.rotation_quaternion_wxyz is None
            and self.rotation_delta_degrees is None
        ):
            raise ValueError("Provide a position or rotation.")
        return self


class Keyframe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frame: Frame
    transforms: Annotated[list[Transform], Field(min_length=1, max_length=200)]


class PropertyChange(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    object: str
    name: str
    value: bool | int | float | list[float]


def create_server(bridge: Bridge):
    server = MCPServer(
        "Cascadeur",
        version="0.1.0",
        instructions=(
            "Read cascadeur://guide before editing. Discover capabilities, inspect the rig and save a checkpoint. "
            "Animate Point/Box controllers; inspect finger local axes. Never infer animation quality from successful calls. "
            "Read poses, sample inbetweens, render body and hand views. Menu actions report dispatch only and can fail or open dialogs. "
            "A timeout has an uncertain outcome: inspect before retrying. Script execution is opt-in."
        ),
    )
    read = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    edit = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    )

    async def call(method, **params):
        try:
            value = await bridge.call(method, params)
            if value.get("log") or value.get("messages"):
                return value
            return value["result"]
        except (BridgeError, ValueError, OSError) as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(annotations=read)
    async def cascadeur_status() -> dict:
        """Check app heartbeat, workspace, bridge version and scripting opt-in without changing the scene."""
        try:
            return bridge.status()
        except BridgeError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(annotations=read)
    async def cascadeur_capabilities() -> dict:
        """Discover installed app tools, actual editor methods, license flags and limitations. Presence is not proof of execution."""
        return await call("capabilities")

    @server.tool(annotations=read)
    async def cascadeur_get_state() -> dict:
        """Inspect current scene, frame range, selection and object counts."""
        return await call("get_state")

    @server.tool(annotations=read)
    async def cascadeur_list_scenes() -> dict:
        """List open scene tabs with current indices and names."""
        return await call("list_scenes")

    @server.tool(annotations=edit)
    async def cascadeur_activate_scene(index: Annotated[int, Field(ge=0)]) -> dict:
        """Activate a scene index returned by list_scenes. Refresh indices before use."""
        return await call("activate_scene", index=index)

    @server.tool(annotations=edit)
    async def cascadeur_new_scene() -> dict:
        """Create a new scene tab. Existing tabs are preserved."""
        return await call("new_scene")

    @server.tool(annotations=edit)
    async def cascadeur_open_scene(path: str) -> dict:
        """Open a .casc scene from an absolute path inside the workspace."""
        return await call("open_scene", path=path)

    @server.tool(annotations=edit)
    async def cascadeur_save_scene(path: str, overwrite: bool = False) -> dict:
        """Save a .casc checkpoint inside the workspace; requires overwrite=true to replace an existing file."""
        previous = bridge.file_stamp(path)
        result = await call("save_scene", path=path, overwrite=overwrite)
        try:
            await bridge.wait_file(path, previous_stamp=previous)
        except BridgeError as exc:
            raise ToolError(str(exc)) from exc
        return result

    @server.tool(annotations=read)
    async def cascadeur_list_objects(
        query: str = "",
        object_type: str | None = None,
        offset: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
    ) -> dict:
        """Find objects by name substring and exact type, with stable IDs and pagination."""
        return await call(
            "list_objects",
            query=query,
            object_type=object_type,
            offset=offset,
            limit=limit,
        )

    @server.tool(annotations=read)
    async def cascadeur_rig_summary() -> dict:
        """Inspect body, Point and Box controls, joints and finger controller candidates. Names alone do not establish axes."""
        return await call("rig_summary")

    @server.tool(annotations=read)
    async def cascadeur_get_object(object: str, frame: Frame = 0) -> dict:
        """Inspect an exact object's behaviours and data channels, including unavailable values. Read before editing properties."""
        return await call("get_object", object=object, frame=frame)

    @server.tool(annotations=read)
    async def cascadeur_get_pose(objects: Names, frame: Frame = 0) -> dict:
        """Read local/global transforms at a frame. Rotations include WXYZ quaternions and Euler radians."""
        return await call("get_pose", objects=objects, frame=frame)

    @server.tool(annotations=edit)
    async def cascadeur_select_objects(objects: list[str]) -> dict:
        """Select exact objects for context-sensitive actions. An empty list clears selection."""
        return await call("select_objects", objects=objects)

    @server.tool(annotations=edit)
    async def cascadeur_set_frame(frame: Frame) -> dict:
        """Move the timeline cursor. Read the returned frame because Cascadeur can clamp it."""
        return await call("set_frame", frame=frame)

    @server.tool(annotations=edit)
    async def cascadeur_set_range(first: Frame, last: Frame) -> dict:
        """Set playback boundaries. This does not allocate animation data or add keyframes."""
        return await call("set_range", first=first, last=last)

    @server.tool(annotations=read)
    async def cascadeur_list_tracks() -> dict:
        """List animation tracks, locks, visibility, keys and interpolation. Tracks differ from additive animation layers."""
        return await call("list_tracks")

    @server.tool(annotations=edit)
    async def cascadeur_select_frames(tracks: Names, first: Frame, last: Frame) -> dict:
        """Select an explicit track interval before physics, mirror, clipboard or timeline actions."""
        return await call("select_frames", tracks=tracks, first=first, last=last)

    @server.tool(annotations=edit)
    async def cascadeur_set_keys(
        tracks: Names, frames: Frames, interpolation: Interpolation = "BEZIER"
    ) -> dict:
        """Add or update keys and allocate animation data on explicit unlocked tracks."""
        return await call(
            "set_keys", tracks=tracks, frames=frames, interpolation=interpolation
        )

    @server.tool(annotations=edit)
    async def cascadeur_remove_keys(tracks: Names, frames: Frames) -> dict:
        """Remove keys from explicit tracks. Frame 0 is protected; save a checkpoint first."""
        return await call("remove_keys", tracks=tracks, frames=frames)

    @server.tool(annotations=edit)
    async def cascadeur_set_interpolation(
        tracks: Names, frames: Frames, interpolation: Interpolation
    ) -> dict:
        """Set outgoing interpolation at existing keys. Verify overshoot and intermediate poses after changing it."""
        return await call(
            "set_interpolation",
            tracks=tracks,
            frames=frames,
            interpolation=interpolation,
        )

    @server.tool(annotations=edit)
    async def cascadeur_set_pose(
        frame: Frame,
        transforms: Annotated[list[Transform], Field(min_length=1, max_length=200)],
        interpolation: Interpolation = "BEZIER",
    ) -> dict:
        """Key body or finger controls in one edit. Position uses scene units, delta rotation uses degrees; rig solving can adjust values."""
        return await call(
            "set_pose",
            frame=frame,
            transforms=[t.model_dump(exclude_none=True) for t in transforms],
            interpolation=interpolation,
        )

    @server.tool(annotations=edit)
    async def cascadeur_animate_transforms(
        keyframes: Annotated[list[Keyframe], Field(min_length=1, max_length=500)],
        interpolation: Interpolation = "BEZIER",
    ) -> dict:
        """Author body and finger animation in a batch. Delta rotations reference a pre-edit frame, default 0. Read poses and render to verify."""
        return await call(
            "animate_transforms",
            keyframes=[k.model_dump(exclude_none=True) for k in keyframes],
            interpolation=interpolation,
        )

    @server.tool(annotations=edit)
    async def cascadeur_set_properties(
        frame: Frame,
        properties: Annotated[
            list[PropertyChange], Field(min_length=1, max_length=200)
        ],
    ) -> dict:
        """Edit discovered scalar/vector data channels. Advanced: can change rig/physics behavior. Read get_object first; no guessed names."""
        return await call(
            "set_properties",
            frame=frame,
            properties=[x.model_dump() for x in properties],
        )

    @server.tool(annotations=read)
    async def cascadeur_sample_motion(
        objects: Names,
        first: Frame,
        last: Frame,
        step: Annotated[int, Field(ge=1, le=1000)] = 1,
    ) -> dict:
        """Sample global trajectories, path lengths and maximum step distances. Useful for drift/jumps; not an artistic quality score."""
        return await call(
            "sample_motion", objects=objects, first=first, last=last, step=step
        )

    @server.tool(annotations=edit)
    async def cascadeur_mirror(objects: Names, interval: bool = False) -> dict:
        """Mirror explicit controls at the current frame or selected interval. Requires valid mirror mappings on the rig."""
        return await call("mirror", objects=objects, interval=interval)

    @server.tool(annotations=edit)
    async def cascadeur_autopose(
        frames: Frames,
        anchors: Annotated[list[str], Field(max_length=40)] | None = None,
        include_directions: bool = True,
        release: Annotated[list[str], Field(max_length=40)] | None = None,
    ) -> dict:
        """Re-solve existing key poses with Cascadeur AutoPosing. Anchor points (default: hands, feet, toes, pelvis, chest, head) are locked as active controllers; knees, elbows, shoulders and spine are predicted by the network. Frames must already be keys. Returns per-frame displacements; render to verify."""
        return await call(
            "autopose",
            frames=frames,
            anchors=anchors,
            include_directions=include_directions,
            release=release,
        )

    @server.tool(annotations=edit)
    async def cascadeur_call_action(
        action_id: str, expected_scene: str, answer: str | None = None
    ) -> dict:
        """Run any catalogued Cascadeur action by ID (see cascadeur_list_actions with catalog=true): interpolation/IK-FK/fulcrum keys on current frame or interval, tween machine, copier, mirror, ghosts, ballistic, cycles, trajectories, visibility. Set frame/selection first. `answer` presses a button (e.g. "Yes") in a modal dialog the action opens (PySide6 bridge)."""
        return await call(
            "call_action",
            action_id=action_id,
            expected_scene=expected_scene,
            answer=answer,
        )

    @server.tool(annotations=edit)
    async def cascadeur_set_mode(
        mode: Literal[
            "autoposing",
            "physics",
            "physics_frozen",
            "fulcrum_points",
            "autoposing_fingers",
            "autoposing_additional_points",
            "auto_interpolation_keys",
            "auto_interpolation_intervals",
        ],
        on: bool,
    ) -> dict:
        """Set a toolbar mode (AutoPosing, AutoPhysics preview, frozen physics, ...) to an explicit state, verified through the UI. Unlike menu toggles this is idempotent. Requires the PySide6 bridge."""
        return await call("set_mode", mode=mode, on=on)

    @server.tool(annotations=edit)
    async def cascadeur_physics_settings(set: dict[str, bool] | None = None) -> dict:
        """Read the Physics Settings panel (gravity, Physics corrector, smooth trajectory/rotation, compensation/separation/secondary motion, ragdoll ...) and optionally flip On/Off switches, e.g. {"Secondary motion": false}. Writes go through the UI (PySide6 bridge) and are verified."""
        return await call("physics_settings", set=set or {})

    @server.tool(annotations=edit)
    async def cascadeur_physics_snap(answer: str = "Yes") -> dict:
        """Enable AutoPhysics if needed and snap the animation to the physics result. With secondary features on, Cascadeur asks whether to disable them (they apply once): `answer` is pressed automatically ("Yes" disables them, "No" keeps them). Mark contacts and priority frames first; sample motion before/after and render to verify."""
        return await call("physics_snap", answer=answer)

    @server.tool(annotations=edit)
    async def cascadeur_set_contacts(
        points: Annotated[list[str], Field(min_length=1, max_length=40)],
        intervals: Annotated[
            list[tuple[Frame, Frame]], Field(min_length=1, max_length=50)
        ],
        point_state: Literal["enforce", "auto", "never"] = "enforce",
    ) -> dict:
        """Mark ground contacts for AutoPhysics: fulcrum key+interval fixation on the tracks of the given points over each interval, and the points' Fulcrum State (enforce/auto/never) at interval ends. Pass toe/heel points (e.g. toe_MainPoint_l, foot_Self0Point_l): every point's whole track becomes a fulcrum track."""
        return await call(
            "set_contacts",
            points=points,
            intervals=[list(i) for i in intervals],
            point_state=point_state,
        )

    @server.tool(annotations=edit)
    async def cascadeur_physics_priority_frames(
        frames: Frames, on: bool = True
    ) -> dict:
        """Mark key frames whose pose AutoPhysics must preserve (priority frames) or clear them. Few priority frames only; too many make the solve inaccurate."""
        return await call("physics_priority_frames", frames=frames, on=on)

    @server.tool(annotations=edit)
    async def cascadeur_inbetween(
        first: Frame,
        last: Frame,
        tracks: Annotated[list[str], Field(max_length=200)] | None = None,
        wait_seconds: Annotated[int, Field(ge=0, le=300)] = 60,
    ) -> dict:
        """Generate the in-betweens of an interval with Cascadeur's AI Inbetweening (toolbar "Inbetweening", action View.MotionGeneration_Run). Needs >= 2 keys, <= 120 frames apart. The interval becomes FIXED interpolation holding generated poses. Save first; render to verify."""
        import asyncio as _asyncio

        track_names = tracks or [
            t["name"] for t in (await call("list_tracks"))["tracks"] if not t["locked"]
        ]
        await call("select_frames", tracks=track_names, first=first, last=last)
        state = await call("get_state")
        await call(
            "call_action",
            action_id="View.MotionGeneration_Run",
            expected_scene=state["name"],
        )
        deadline = _asyncio.get_running_loop().time() + wait_seconds
        sections = {}
        while True:
            tracks_now = (await call("list_tracks"))["tracks"]
            sections = {
                t["name"]: {
                    k: v for k, v in t["sections"].items() if first <= int(k) < last
                }
                for t in tracks_now
                if t["name"] in track_names
            }
            done = any("FIXED" in s.values() for s in sections.values())
            if done or _asyncio.get_running_loop().time() > deadline:
                break
            await _asyncio.sleep(2)
        return dict(generated=done, interval=[first, last], sections=sections)

    @server.tool(annotations=edit)
    async def cascadeur_answer_dialog(button: str) -> dict:
        """Press a button (e.g. "Yes", "No", "OK") in an open modal Cascadeur dialog; cascadeur_ui_state lists open dialogs. Requires the PySide6 bridge."""
        return await call("answer_dialog", button=button)

    @server.tool(annotations=read)
    async def cascadeur_ui_screenshot(path: str) -> list[TextContent | ImageContent]:
        """Capture the whole Cascadeur UI (menus, timeline, panels, physics ghost, dialogs) as PNG, not just the viewport. Requires the PySide6 bridge."""
        result = await call("ui_screenshot", path=path)
        main = [w for w in result["windows"] if w["main"]]
        if not main:
            raise ToolError("Main window not captured: %s" % result)
        data = Path(main[0]["path"]).read_bytes()
        return [
            TextContent(type="text", text=json.dumps(result["windows"])),
            ImageContent(
                type="image",
                mimeType="image/png",
                data=base64.b64encode(data).decode(),
            ),
        ]

    @server.tool(annotations=read)
    async def cascadeur_ui_state(query: str = "") -> dict:
        """Read toolbar toggle states from Cascadeur's UI (e.g. AutoPosing mode, Physics Assistant), keyed by action ID. Requires the optional PySide6 bridge setup; returns available=false otherwise."""
        return await call("ui_state", query=query)

    @server.tool(annotations=edit)
    async def cascadeur_set_view_mode(
        mode: Literal[
            "View", "AutoPosing", "PointController", "Controller", "Joint", "Mesh"
        ],
    ) -> dict:
        """Choose clean mesh review or a rig controller display mode for the active viewport."""
        return await call("set_view_mode", mode=mode)

    @server.tool(annotations=read)
    async def cascadeur_get_camera() -> dict:
        """Read the active viewport camera for restoring a view after hand/body closeups."""
        return await call("get_camera")

    @server.tool(annotations=edit)
    async def cascadeur_set_camera(
        position: Vector | None = None, target: Vector | None = None
    ) -> dict:
        """Set the active viewport camera position/target in scene units."""
        return await call("set_camera", position=position, target=target)

    @server.tool(annotations=edit)
    async def cascadeur_frame_objects(objects: Names) -> dict:
        """Frame body or finger controls in the viewport for visual inspection."""
        return await call("frame_objects", objects=objects)

    @server.tool(annotations=edit)
    async def cascadeur_capture_viewport(
        path: str,
        width: Annotated[int, Field(ge=64, le=3840)] = 1280,
        height: Annotated[int, Field(ge=64, le=2160)] = 720,
        overwrite: bool = False,
    ) -> list[TextContent | ImageContent]:
        """Render a PNG of the active viewport and return it as an MCP image. Use distinct filenames per pose."""
        previous = bridge.file_stamp(path)
        await call(
            "capture_viewport",
            path=path,
            width=width,
            height=height,
            overwrite=overwrite,
        )
        try:
            file = await bridge.wait_file(path, previous_stamp=previous)
            if file.stat().st_size > 16 * 1024 * 1024:
                raise BridgeError("Image exceeds 16 MiB; reduce capture dimensions.")
            return [
                TextContent(type="text", text=str(file)),
                ImageContent(
                    type="image",
                    mimeType="image/png",
                    data=base64.b64encode(file.read_bytes()).decode(),
                ),
            ]
        except (BridgeError, OSError) as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(annotations=edit)
    async def cascadeur_import_fbx(
        path: str, mode: Literal["scene", "animation", "model"] = "scene"
    ) -> dict:
        """Import an FBX from the workspace. Animation replaces matching rig data; save a checkpoint and inspect skeleton mappings."""
        return await call("import_fbx", path=path, mode=mode)

    @server.tool(annotations=edit)
    async def cascadeur_export_fbx(
        path: str,
        mode: Literal["scene", "animation", "selected"] = "animation",
        overwrite: bool = False,
    ) -> dict:
        """Export FBX after checking app license. Verify the exported skeleton, frame range and axes in the receiving app."""
        previous = bridge.file_stamp(path)
        result = await call("export_fbx", path=path, mode=mode, overwrite=overwrite)
        try:
            await bridge.wait_file(path, previous_stamp=previous)
        except BridgeError as exc:
            raise ToolError(str(exc)) from exc
        return result

    @server.tool(annotations=read)
    async def cascadeur_list_actions(query: str = "", catalog: bool = False) -> dict:
        """List curated menu actions (for cascadeur_run_action), or with catalog=true the full catalog of ~220 Cascadeur action IDs by category (for cascadeur_call_action). Filter with query."""
        return await call("list_actions", query=query, catalog=catalog)

    @server.tool(annotations=edit)
    async def cascadeur_run_action(name: str, expected_scene: str) -> dict:
        """Dispatch a named action from list_actions on an explicitly named scene. Many are toggles or depend on selection/license. Dispatch is not verified success."""
        return await call("run_action", name=name, expected_scene=expected_scene)

    @server.tool(annotations=read)
    async def cascadeur_inspect_api(
        root: Literal["csc", "scene", "view", "app", "model", "layers"] = "csc",
        path: str = "",
        limit: Annotated[int, Field(ge=1, le=150)] = 80,
    ) -> dict:
        """Read live Python API member names/signatures/docs without executing methods. Prefer this over guessing from stale stubs."""
        return await call("inspect_api", root=root, path=path, limit=limit)

    @server.tool(annotations=read)
    async def cascadeur_inspect_tool(
        name: str, editor: bool = True, path: str = ""
    ) -> dict:
        """Inspect a discovered tool/editor and optional public attribute path. Exposes actual signatures for advanced scripts."""
        return await call("inspect_tool", name=name, editor=editor, path=path)

    if bridge.allow_scripts:

        @server.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False, destructiveHint=True, openWorldHint=True
            )
        )
        async def cascadeur_run_script(
            code: Annotated[str, Field(min_length=1, max_length=200000)],
        ) -> dict:
            """Advanced opt-in Python execution inside Cascadeur. Has full user privileges, outside workspace restrictions. Available: csc, app, view, scene. Assign JSON-compatible result; use scene.modify_update for undoable edits."""
            return await call("run_script", code=code)

    guide = Path(__file__).with_name("AI_GUIDE.md")

    @server.resource("cascadeur://guide")
    def ai_guide() -> str:
        """Verified workflow, tool selection, finger calibration and limitations for AI agents."""
        return guide.read_text()

    @server.resource("cascadeur://scene")
    async def scene_resource() -> str:
        return json.dumps(await call("get_state"))

    @server.prompt()
    def animate_character(brief: str) -> str:
        """Start an animation task with inspection, checkpoints and visual verification."""
        return f"Read cascadeur://guide. Discover capabilities and inspect the rig, tracks and frame rate. Save a new checkpoint. Plan key poses for: {brief}. Animate body controls first, then hands/fingers after local-axis calibration. Check intermediate poses, contacts and silhouette; render full-body and hand closeups. Save and export only after verification. Report tested behavior and remaining limitations honestly."

    return server
