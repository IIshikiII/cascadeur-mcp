"""Cascadeur API operations. Imported only by the in-application bridge."""

from __future__ import annotations

import inspect
import math
import re
from pathlib import Path

from .app_bridge import json_value


def context():
    import csc

    app = csc.app.get_application()
    view = app.get_scene_manager().current_scene()
    if view is None:
        raise ValueError("Open or create a Cascadeur scene first.")
    return csc, app, view, view.domain_scene()


def optional_call(obj, name, default=None):
    """Call an API method that older Cascadeur builds (e.g. 2025.2) may lack."""
    method = getattr(obj, name, None)
    return method() if callable(method) else default


def file_path(value, state, *, exists=False, overwrite=False, suffix=None):
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raise ValueError("Use an absolute path inside the configured workspace.")
    path = raw.resolve()
    if not path.is_relative_to(state["workspace"].resolve()):
        raise ValueError("Path is outside the app bridge workspace.")
    if suffix and path.suffix.lower() not in suffix:
        raise ValueError("Expected file extension: " + ", ".join(suffix))
    if exists:
        if not path.is_file():
            raise ValueError("Input file does not exist.")
    else:
        if path.exists() and not overwrite:
            raise ValueError("File exists. Set overwrite=true explicitly.")
        if not path.parent.is_dir():
            raise ValueError("Output parent directory must already exist.")
    return path


def object_id(scene, value):
    mv = scene.model_viewer()
    # UUIDs and exact unambiguous names are accepted; never fuzzy-match edits.
    matches = [o for o in mv.get_objects() if str(o) == value]
    if not matches:
        matches = list(mv.get_objects(value))
    if len(matches) != 1:
        raise ValueError(
            "Expected one object for %r; found %d. Use an ID from list_objects."
            % (value, len(matches))
        )
    return matches[0]


def layer_ids(scene, values):
    lv = scene.layers_viewer()
    if values is None:
        raise ValueError("Specify layer IDs or exact layer names explicitly.")
    result = []
    for value in values:
        matches = [
            lid
            for lid in lv.all_layer_ids()
            if str(lid) == value or lv.header(lid).name == value
        ]
        if len(matches) != 1:
            raise ValueError(
                "Expected one animation track for %r; found %d." % (value, len(matches))
            )
        if lv.layer(matches[0]).is_locked:
            raise ValueError("Track is locked: " + value)
        result.append(matches[0])
    if not result:
        raise ValueError("Provide at least one track.")
    return result


def frame_number(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= 100000
    ):
        raise ValueError("Frame must be an integer from 0 to 100000.")
    return value


def vector(value, length=3):
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError("Expected a vector of length %d." % length)
    result = [float(n) for n in value]
    if not all(math.isfinite(n) for n in result):
        raise ValueError("Numbers must be finite.")
    return result


def transform_id(scene, oid, prop):
    bv = scene.behaviour_viewer()
    bh = bv.get_behaviour_by_name(oid, "Transform")
    if bh.is_null():
        raise ValueError("Object has no Transform behaviour.")
    did = bv.get_behaviour_data(bh, prop)
    if did.is_null():
        raise ValueError("Transform property is unavailable: " + prop)
    return did


def encode_data(value):
    if hasattr(value, "to_quaternion"):
        q = value.to_quaternion()
        return {
            "type": "rotation",
            "quaternion_wxyz": [q.w(), q.x(), q.y(), q.z()],
            "euler_radians": json_value(value.to_euler_angles()),
        }
    return json_value(value)


def read_data(dv, did, frame):
    import csc

    data = dv.get_data(did)
    return (
        dv.get_data_value(did)
        if data.mode == csc.model.DataMode.Static
        else dv.get_data_value(did, frame)
    )


def modify(scene, label, callback):
    errors = []

    def wrapped(*args):
        try:
            callback(*args)
        except Exception as exc:
            errors.append(exc)
            raise

    ok = scene.modify_update(label, wrapped)
    if errors:
        raise errors[0]
    if ok is False:
        raise RuntimeError(
            "Cascadeur rejected the edit. Inspect the event log and scene."
        )


def scene_path(view, current=True):
    """Scene file path. Builds without View.get_path_name (e.g. Windows 2025.2) fall back to
    the main window title "<path> - Cascadeur", which only describes the active tab."""
    path = optional_call(view, "get_path_name")
    if path or not current:
        return path or None
    gui = qt_gui({})
    if gui is None:
        return None
    for window in gui.QGuiApplication.topLevelWindows():
        if window.objectName() == "MainWindow":
            title = window.title().removesuffix(" - Cascadeur").lstrip("*")
            if title.lower().endswith(".casc") and Path(title).is_file():
                return str(Path(title))
    return None


def state_summary(scene, view):
    mv = scene.model_viewer()
    counts = {}
    for oid in mv.get_objects():
        name = mv.get_object_type_name(oid)
        counts[name] = counts.get(name, 0) + 1
    boundary = view.animation_boundary()
    return dict(
        name=view.name(),
        path=scene_path(view),
        frame=scene.get_current_frame(),
        first_frame=boundary.first_frame,
        last_frame=boundary.last_frame,
        object_count=sum(counts.values()),
        object_types=counts,
        selected_ids=[str(o) for o in scene.selector().selected().ids],
        track_count=len(scene.layers_viewer().all_layer_ids()),
    )


def inspect_api(root, path, limit=100):
    if path:
        for part in path.split("."):
            if part.startswith("_") or not part.isidentifier():
                raise ValueError("Only public attribute paths are allowed.")
            root = getattr(root, part)
    members = []
    for name in sorted(n for n in dir(root) if not n.startswith("_"))[:limit]:
        try:
            obj = getattr(root, name)
            members.append(
                dict(
                    name=name,
                    callable=callable(obj),
                    doc=(inspect.getdoc(obj) or "")[:2400],
                )
            )
        except Exception as exc:
            members.append(dict(name=name, error=str(exc)))
    return dict(
        type=type(root).__name__,
        doc=(inspect.getdoc(root) or "")[:6000],
        members=members,
    )


def qt_gui(bridge_state):
    """PySide6.QtGui bound to Cascadeur's own Qt, or None when unavailable.

    Cascadeur ships no Qt bindings. A PySide6 build for the same Qt version with its Qt DLLs
    removed (so Cascadeur's already-loaded ones are reused) can be pointed to with the bridge's
    pyside6_site option. See docs/FIELD_NOTES.md.
    """
    import os
    import sys

    try:
        from PySide6 import QtGui

        return QtGui
    except ImportError:
        pass
    site = bridge_state.get("pyside6_site")
    if not site or not Path(site).is_dir():
        return None
    try:
        os.add_dll_directory(site)
        os.add_dll_directory(str(Path(sys.executable).parent))
        if site not in sys.path:
            sys.path.insert(0, site)
        import PySide6
        from PySide6 import QtCore, QtGui

        # Bindings must target the Qt version Cascadeur has loaded (e.g. 6.5.1.1 on 6.5.1).
        return QtGui if PySide6.__version__.startswith(QtCore.qVersion()) else None
    except Exception:
        return None


def toolbar_states(bridge_state):
    """{action id: active} for toolbar buttons of the main window, or None without PySide6."""
    gui = qt_gui(bridge_state)
    if gui is None:
        return None
    windows = [
        w
        for w in gui.QGuiApplication.topLevelWindows()
        if w.objectName() == "MainWindow"
    ]
    if not windows:
        return None
    states = {}

    def walk(item):
        action = item.property("actionId")
        if action and item.property("visible"):
            states[action] = states.get(action, False) or bool(item.property("active"))
        for child in item.childItems():
            walk(child)

    walk(windows[0].contentItem())
    return states


def restore_minimized_window():
    """Un-minimize the Cascadeur window without focusing it (Windows only).

    Viewport renders are queued until the window repaints; a minimized window never does,
    so captures silently wait until the user restores it.
    """
    import os
    import sys

    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    pid, found = os.getpid(), []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsIconic(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(collect, 0)
    for hwnd in found:
        user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
    return bool(found)


AUTOPOSE_ANCHORS = (
    "hand_MainPoint_r",
    "hand_MainPoint_l",
    "foot_MainPoint_r",
    "foot_MainPoint_l",
    "toe_MainPoint_r",
    "toe_MainPoint_l",
    "toe_DirectionPoint_r",
    "toe_DirectionPoint_l",
    "pelvis_MainPoint",
    "chest_MainPoint",
    "head_MainPoint",
)


def autopose(scene, view, app, p, bridge_state):
    """Re-solve key poses with AutoPosing: anchors become active (blue), the rest is predicted.

    Verified mechanics: controllers are Tool_object_ids found via Select all in the AutoPosing
    viewport; switching the mode on syncs them to the rig pose; SwitchLock toggles selected
    controllers blue/green; Update regenerates the green ones from the blue ones.
    The API exposes neither the mode nor lock state, so the bridge assumes the mode is off
    between calls and remembers locked frames in <workspace>/.autopose_locks.json. A frame whose
    anchors drift after Update is restored from a snapshot and reported as failed.
    """
    import json

    import csc
    import numpy as np

    mv, dv = scene.model_viewer(), scene.data_viewer()
    lv = scene.layers_viewer()
    am = app.get_action_manager()
    dvp = view.active_viewport().domain_viewport()
    VM = csc.view.ViewportMode
    null = csc.model.ObjectId.null()
    anchors = list(p.get("anchors") or AUTOPOSE_ANCHORS)
    frames = [frame_number(f) for f in p["frames"]]
    if not frames or len(frames) > 200:
        raise ValueError("Provide 1 to 200 key frames.")
    points = {
        mv.get_object_name(o): transform_id(scene, o, "global_position")
        for o in mv.get_objects()
        if mv.get_object_type_name(o) == "Point"
    }
    unknown = [n for n in anchors if n not in points]
    if unknown:
        raise ValueError("Unknown anchor points: " + ", ".join(unknown))
    for f in frames:
        for name in anchors:
            lid = lv.layer_id_by_obj_id_or_null(object_id(scene, name))
            if not lid.is_null() and not lv.layer(lid).is_key(f):
                raise ValueError(
                    "Frame %d is not a key on the track of %s." % (f, name)
                )
    registry_path = bridge_state["workspace"] / ".autopose_locks.json"
    try:
        registry = json.loads(registry_path.read_text())
    except (OSError, ValueError):
        registry = {}
    scene_key = view.name()
    locked = set(registry.get(scene_key, []))

    def read(name, f):
        return np.array(dv.get_data_value(points[name], f), dtype=float).ravel()

    def restore(snapshot, f):
        def edit(me, ue, su, session):
            for name, v in snapshot.items():
                me.data_editor().set_data_value(points[name], f, v)
            su.run_update(set(points.values()), f)

        scene.modify_update_with_session("MCP autopose restore", edit)

    def select(tool_ids):
        tool_ids = set(tool_ids)
        first = next(iter(tool_ids)) if tool_ids else null

        def edit(model, update, sc, session):
            session.take_selector().select(tool_ids, first)

        scene.modify_with_session("MCP autopose select", edit)

    def controllers(f):
        dvp.set_mode_visualizers(VM.AutoPosing)
        am.call_action("Application.Select all")
        seeds = {
            i
            for i in scene.selector().selected().ids
            if isinstance(i, csc.domain.Tool_object_id)
        }
        tools = set()
        for group in csc.domain.get_all_visible_ids_by_proc(scene, seeds, f):
            tools |= {i for i in group if isinstance(i, csc.domain.Tool_object_id)}
        pivot = scene.selector().pivot()
        pose = {n: read(n, f) for n in points}
        by_name, directions = {}, []
        for t in tools:
            pivot.select(t)
            pos = np.array(pivot.position(), dtype=float).ravel()
            best = min(pose, key=lambda n: np.linalg.norm(pose[n] - pos))
            if np.linalg.norm(pose[best] - pos) < 1.0:
                by_name[best] = t
            else:
                directions.append(t)
        return tools, by_name, directions

    report = []
    ui = toolbar_states(bridge_state)
    mode_checked = ui is not None and "AutoPosingTool.AutoPosing" in ui
    if mode_checked and ui["AutoPosingTool.AutoPosing"]:
        am.call_action(
            "AutoPosingTool.AutoPosing"
        )  # the recipe needs the mode off first
    try:
        for f in frames:
            scene.set_current_frame(f)
            before = {n: read(n, f) for n in points}
            am.call_action(
                "AutoPosingTool.AutoPosing"
            )  # on: controllers sync to the rig pose
            status = "ok"
            try:
                tools, by_name, directions = controllers(f)
                if not tools:
                    raise RuntimeError("No AutoPosing controllers found for this rig.")
                missing = [n for n in anchors if n not in by_name]
                lock = set()
                if f not in locked:
                    lock = {by_name[n] for n in anchors if n in by_name}
                    if p.get("include_directions", True):
                        lock |= set(directions)
                    select(lock)
                    am.call_action("AutoPosingTool.SwitchLock")
                am.call_action("AutoPosingTool.Update")
                select(set())
            finally:
                am.call_action(
                    "AutoPosingTool.AutoPosing"
                )  # off: the solved pose stays in the rig
            after = {n: read(n, f) for n in points}
            moved = {n: float(np.linalg.norm(after[n] - before[n])) for n in points}
            drift = max(moved[n] for n in anchors)
            if lock:  # SwitchLock toggled them whatever happens next
                locked.add(f)
            if drift > float(p.get("max_anchor_drift", 3.0)):
                restore(before, f)
                status = (
                    "restored: anchors drifted %.1f cm (lock state out of sync?)"
                    % drift
                )
            report.append(
                dict(
                    frame=f,
                    status=status,
                    controllers=len(tools),
                    newly_locked=len(lock),
                    missing_anchors=missing,
                    anchor_drift_cm=round(drift, 2),
                    moved_cm={
                        n: round(v, 1)
                        for n, v in sorted(moved.items(), key=lambda x: -x[1])
                        if v >= 0.5
                    },
                )
            )
    finally:
        dvp.set_mode_visualizers(VM.View)
        registry[scene_key] = sorted(locked)
        registry_path.write_text(json.dumps(registry, indent=1))
    ui = toolbar_states(bridge_state)
    return dict(
        frames=report,
        mode_state_checked=mode_checked,
        autoposing_mode_on_after=None
        if ui is None
        else ui.get("AutoPosingTool.AutoPosing"),
        note="AutoPosing mode is left off; anchors stay active (blue) on processed frames. Render to verify.",
    )


def dispatch(method, p, bridge_state):
    import csc

    app = csc.app.get_application()
    if method == "new_scene":
        app.get_scene_manager().create_application_scene()
        _, _, view, scene = context()
        return state_summary(scene, view)
    if method == "open_scene":
        path = file_path(p["path"], bridge_state, exists=True, suffix={".casc"})
        if not app.get_data_source_manager().load_scene(str(path)):
            raise RuntimeError("Cascadeur could not open the scene.")
        return {"opened": str(path)}
    if method == "list_scenes":
        current = app.get_scene_manager().current_scene()
        return {
            "scenes": [
                dict(
                    index=i,
                    name=v.name(),
                    path=scene_path(v, current=v == current),
                    active=v == current,
                )
                for i, v in enumerate(app.get_scene_manager().scenes())
            ]
        }
    if method == "activate_scene":
        scenes = app.get_scene_manager().scenes()
        if not 0 <= p["index"] < len(scenes):
            raise ValueError("Invalid scene index; call list_scenes again.")
        app.get_scene_manager().set_current_scene(scenes[p["index"]])
        return {"active": scenes[p["index"]].name()}
    if method == "inspect_api" and p.get("root", "csc") == "csc":
        return inspect_api(csc, p.get("path", ""), p.get("limit", 80))
    if method == "capabilities":
        view = app.get_scene_manager().current_scene()
        items = []
        for t in app.get_tools_manager().tools():
            name = t.name() if hasattr(t, "name") else type(t).__name__
            item = dict(name=name, methods=[x for x in dir(t) if not x.startswith("_")])
            if view and hasattr(t, "editor"):
                try:
                    editor = t.editor(view)
                    item["editor_type"] = type(editor).__name__
                    item["editor_methods"] = [
                        x for x in dir(editor) if not x.startswith("_")
                    ]
                except Exception as exc:
                    item["editor_error"] = str(exc)
            items.append(item)
        return dict(
            api_version=getattr(csc, "__version__", "unknown"),
            tools=items,
            export_available=optional_call(app, "is_export_available"),
            pro_features_available=optional_call(app, "is_pro_features_available"),
            scripting_enabled=bridge_state["allow_scripts"],
            note="Available API members are discovered live. Presence does not prove successful execution or animation quality.",
        )
    csc, app, view, scene = context()
    mv, bv, dv, lv = (
        scene.model_viewer(),
        scene.behaviour_viewer(),
        scene.data_viewer(),
        scene.layers_viewer(),
    )
    if method == "get_state":
        return state_summary(scene, view)
    if method == "inspect_api":
        roots = {"scene": scene, "view": view, "app": app, "model": mv, "layers": lv}
        if p["root"] not in roots:
            raise ValueError("Unknown API root.")
        return inspect_api(roots[p["root"]], p.get("path", ""), p.get("limit", 80))
    if method == "inspect_tool":
        tool = app.get_tools_manager().get_tool(p["name"])
        if tool is None:
            raise ValueError("Tool not available; use capabilities.")
        if p.get("editor", True) and hasattr(tool, "editor"):
            tool = tool.editor(view)
        return inspect_api(tool, p.get("path", ""), 100)
    if method == "save_scene":
        path = file_path(
            p["path"],
            bridge_state,
            overwrite=p.get("overwrite", False),
            suffix={".casc"},
        )
        view.save(str(path))
        return {
            "path": str(path),
            "exists": path.is_file(),
            "bytes": path.stat().st_size if path.is_file() else 0,
        }
    if method in ("list_objects", "rig_summary"):
        items = []
        for oid in mv.get_objects():
            name, typ = mv.get_object_name(oid), mv.get_object_type_name(oid)
            if method == "rig_summary" and typ not in (
                "Joint",
                "Point",
                "Box",
                "Rigid Body",
                "AutoPosing",
            ):
                continue
            if p.get("query", "").lower() not in name.lower() or (
                p.get("object_type") and p["object_type"] != typ
            ):
                continue
            items.append(dict(id=str(oid), name=name, type=typ))
        if method == "rig_summary":
            return dict(
                count=len(items),
                controls=items[:2000],
                finger_controls=[
                    o
                    for o in items
                    if o["type"] == "Box"
                    and re.search(
                        r"finger|thumb|index|middle|ring|pinky|little|^f_",
                        o["name"],
                        re.I,
                    )
                ],
                advice="Animate rig Point/Box controllers. Joint output may be overwritten by rig solving. Calibrate finger local axes per rig.",
            )
        offset, limit = p.get("offset", 0), p.get("limit", 100)
        return dict(total=len(items), objects=items[offset : offset + limit])
    if method == "get_object":
        oid = object_id(scene, p["object"])
        frame = frame_number(p.get("frame", scene.get_current_frame()))
        props = []
        for did in dv.get_all_data_id(oid):
            row = dict(
                id=str(did),
                name=getattr(dv.get_data(did), "name", None),
                mode=str(dv.get_data(did).mode),
            )
            try:
                row["value"] = encode_data(read_data(dv, did, frame))
            except Exception as exc:
                row["unavailable"] = str(exc)
            props.append(row)
        return dict(
            id=str(oid),
            name=mv.get_object_name(oid),
            type=mv.get_object_type_name(oid),
            frame=frame,
            behaviours=[
                dict(
                    name=bv.get_behaviour_name(b),
                    properties=bv.get_behaviour_property_names(b),
                )
                for b in bv.get_behaviours(oid)
            ],
            data=props,
        )
    if method == "get_pose":
        frame = frame_number(p.get("frame", scene.get_current_frame()))
        rows = []
        for value in p["objects"]:
            oid = object_id(scene, value)
            row = dict(id=str(oid), name=mv.get_object_name(oid))
            for prop in (
                "global_position",
                "global_rotation",
                "local_position",
                "local_rotation",
                "local_scale",
            ):
                try:
                    row[prop] = encode_data(
                        read_data(dv, transform_id(scene, oid, prop), frame)
                    )
                except Exception as exc:
                    row[prop] = {"unavailable": str(exc)}
            rows.append(row)
        return dict(frame=frame, objects=rows)
    if method == "set_frame":
        scene.set_current_frame(frame_number(p["frame"]))
        return {"frame": scene.get_current_frame()}
    if method == "set_range":
        first, last = frame_number(p["first"]), frame_number(p["last"])
        if last < first:
            raise ValueError("Last frame must be >= first.")
        b = view.animation_boundary()
        b.last_frame = max(last, b.last_frame)
        b.first_frame = first
        b.last_frame = last
        return {"first": b.first_frame, "last": b.last_frame}
    if method == "select_objects":
        ids = {object_id(scene, x) for x in p["objects"]}
        scene.selector().select(
            ids,
            csc.model.ObjectId.null(),
            csc.domain.SelectorFilter.Free,
            csc.domain.SelectorMode.NewSelection,
        )
        return {"selected_ids": [str(o) for o in scene.selector().selected().ids]}
    if method == "list_tracks":
        return {
            "tracks": [
                dict(
                    id=str(lid),
                    name=lv.header(lid).name,
                    locked=lv.layer(lid).is_locked,
                    visible=lv.layer(lid).is_visible,
                    object_count=len(lv.layer(lid).obj_ids),
                    keys=list(lv.layer(lid).key_frame_indices()),
                    sections={
                        str(f): s.interval.interpolation.name
                        for f, s in lv.layer(lid).sections.items()
                    },
                )
                for lid in lv.all_layer_ids()
            ]
        }
    if method == "select_frames":
        ids = layer_ids(scene, p["tracks"])
        first, last = frame_number(p["first"]), frame_number(p["last"])
        if last < first:
            raise ValueError("Last frame must be >= first.")
        scene.get_layers_selector().set_full_selection_by_parts(ids, first, last)
        return dict(tracks=[str(x) for x in ids], first=first, last=last)
    if method in ("set_keys", "set_interpolation", "remove_keys"):
        ids = layer_ids(scene, p["tracks"])
        frames = sorted({frame_number(f) for f in p["frames"]})
        if not frames:
            raise ValueError("Provide at least one frame.")
        mode = p.get("interpolation", "BEZIER")
        if mode not in csc.layers.layer.Interpolation.__members__:
            raise ValueError("Unknown interpolation.")
        if method == "set_interpolation" and any(
            not lv.layer(lid).is_key(f) for lid in ids for f in frames
        ):
            raise ValueError(
                "Interpolation edits require existing keys at every requested frame."
            )
        if method == "remove_keys" and 0 in frames:
            raise ValueError("The initial frame 0 is protected.")

        def edit(me, ue, su):
            le = me.layers_editor()
            for lid in ids:
                for f in frames:
                    if method == "remove_keys":
                        le.unset_section(f, lid)
                    else:
                        le.set_fixed_interpolation_or_key_if_need(lid, f, True)

                        def change(section):
                            section.interval.interpolation = (
                                csc.layers.layer.Interpolation.__members__[mode]
                            )

                        le.change_section(f, lid, change)
            le.normalize_sections(scene)
            me.fit_animation_size_by_layers()

        modify(scene, "MCP " + method, edit)
        return dispatch("list_tracks", {}, bridge_state)
    if method in ("set_pose", "animate_transforms"):
        keys = (
            p["keyframes"]
            if method == "animate_transforms"
            else [dict(frame=p["frame"], transforms=p["transforms"])]
        )
        if not keys or len(keys) > 500:
            raise ValueError("Provide 1 to 500 keyframes per call.")
        prepared = []
        for key in keys:
            f = frame_number(key["frame"])
            updates = []
            if not key["transforms"]:
                raise ValueError("Each frame requires transforms.")
            for tr in key["transforms"]:
                oid = object_id(scene, tr["object"])
                lid = lv.layer_id_by_obj_id_or_null(oid)
                if lid.is_null() or lv.layer(lid).is_locked:
                    raise ValueError("Object has no editable track: " + tr["object"])
                if tr.get("space", "local") not in ("local", "global"):
                    raise ValueError("Space must be local or global.")
                space = tr.get("space", "local")
                props = []
                if tr.get("position") is not None:
                    props.append((space + "_position", vector(tr["position"])))
                if tr.get("rotation_quaternion_wxyz") is not None:
                    q = vector(tr["rotation_quaternion_wxyz"], 4)
                    norm = math.sqrt(sum(x * x for x in q))
                    if norm < 1e-8:
                        raise ValueError("Quaternion cannot be zero.")
                    props.append(
                        (
                            space + "_rotation",
                            csc.math.Rotation.from_quaternion(*[x / norm for x in q]),
                        )
                    )
                if tr.get("rotation_delta_degrees") is not None:
                    base_f = frame_number(tr.get("reference_frame", f))
                    did = transform_id(scene, oid, space + "_rotation")
                    base = read_data(dv, did, base_f)
                    delta = csc.math.Rotation.from_euler(
                        *[math.radians(x) for x in vector(tr["rotation_delta_degrees"])]
                    )
                    props.append(
                        (
                            space + "_rotation",
                            csc.math.Rotation.from_rotation_matrix(
                                base.to_rotation_matrix() @ delta.to_rotation_matrix()
                            ),
                        )
                    )
                if (
                    tr.get("rotation_delta_degrees") is not None
                    and tr.get("rotation_quaternion_wxyz") is not None
                ):
                    raise ValueError(
                        "Specify either an absolute rotation or a delta, not both."
                    )
                if not props:
                    raise ValueError("No transform values supplied.")
                updates.extend(
                    (lid, transform_id(scene, oid, prop), value)
                    for prop, value in props
                )
            prepared.append((f, updates))
        interpolation = p.get("interpolation", "BEZIER")
        if interpolation not in (
            "BEZIER",
            "CLAMPED_BEZIER",
            "LINEAR",
            "STEP",
            "FIXED",
            "LOW_AMPLITUDE_BEZIER",
        ):
            raise ValueError("Unsupported interpolation for transform authoring.")

        def edit(me, ue, su):
            le = me.layers_editor()
            de = me.data_editor()
            for f, updates in prepared:
                for lid in {x[0] for x in updates}:
                    le.set_fixed_interpolation_or_key_if_need(lid, f, True)

                    def change(section):
                        section.interval.interpolation = (
                            csc.layers.layer.Interpolation.__members__[interpolation]
                        )

                    le.change_section(f, lid, change)
            le.normalize_sections(scene)
            me.fit_animation_size_by_layers()
            for f, updates in prepared:
                for _lid, did, value in updates:
                    de.set_data_value(did, f, value)
                su.run_update({x[1] for x in updates}, f)

        modify(scene, "MCP animate transforms", edit)
        return dict(
            frames=[f for f, _ in prepared],
            updated_values=sum(len(u) for _, u in prepared),
            note="Rig solving can alter requested values. Read poses and render frames to verify.",
        )
    if method == "set_properties":
        f = frame_number(p["frame"])
        changes = []
        for row in p["properties"]:
            oid = object_id(scene, row["object"])
            did = dv.get_data_id(oid, row["name"])
            if did.is_null():
                raise ValueError("Unknown data property: " + row["name"])
            old = read_data(dv, did, f)
            value = row["value"]
            if isinstance(old, bool):
                if not isinstance(value, bool):
                    raise ValueError("Expected a boolean.")
            elif isinstance(old, (int, float)):
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise ValueError("Expected a finite number.")
                value = type(old)(value)
            elif hasattr(old, "shape") and old.shape in ((3,), (3, 1)):
                value = vector(value)
            else:
                raise ValueError(
                    "This property type requires an explicit script; use get_object to inspect it."
                )
            changes.append((did, value))
        if not changes:
            raise ValueError("No properties supplied.")

        def edit(me, ue, su):
            for did, value in changes:
                if dv.get_data(did).mode == csc.model.DataMode.Static:
                    me.data_editor().set_data_value(did, value)
                else:
                    me.data_editor().set_data_value(did, f, value)
            su.run_update({x[0] for x in changes}, f)

        modify(scene, "MCP set data properties", edit)
        return {"updated": len(changes), "frame": f}
    if method == "sample_motion":
        first, last, step = (
            frame_number(p["first"]),
            frame_number(p["last"]),
            p.get("step", 1),
        )
        if step < 1 or last < first or (last - first) // step > 2000:
            raise ValueError("Invalid range or more than 2001 samples.")
        frames = list(range(first, last + 1, step))
        rows = []
        for value in p["objects"]:
            oid = object_id(scene, value)
            did = transform_id(scene, oid, "global_position")
            positions = [vector(json_value(read_data(dv, did, f))) for f in frames]
            distances = [
                math.dist(a, b) for a, b in zip(positions, positions[1:], strict=False)
            ]
            rows.append(
                dict(
                    id=str(oid),
                    name=mv.get_object_name(oid),
                    positions=positions,
                    max_step_distance=max(distances, default=0),
                    path_length=sum(distances),
                )
            )
        return dict(
            frames=frames,
            objects=rows,
            note="Distances are scene units per sample, not a quality score. Inspect contacts, silhouette and timing visually.",
        )
    if method == "mirror":
        ids = {object_id(scene, v) for v in p["objects"]}
        if not ids:
            raise ValueError("Select objects explicitly.")
        core = app.get_tools_manager().get_tool("MirrorTool").editor(view).core()
        if p.get("interval", False):
            core.mirror_interval(ids)
        else:
            core.mirror_frame(ids)
        return {"mirrored_ids": [str(x) for x in ids]}
    if method == "set_view_mode":
        if p["mode"] not in (
            "View",
            "AutoPosing",
            "PointController",
            "Controller",
            "Joint",
            "Mesh",
        ):
            raise ValueError("Unsupported viewport mode.")
        view.active_viewport().domain_viewport().set_mode_visualizers(
            csc.view.ViewportMode.__members__[p["mode"]]
        )
        return {"mode": p["mode"]}
    if method == "get_camera":
        camera = view.active_viewport().domain_viewport().camera_struct()
        return dict(
            position=json_value(camera.position),
            target=json_value(camera.target),
            type=camera.type.name,
        )
    if method == "set_camera":
        domain = view.active_viewport().domain_viewport()
        camera = domain.camera_struct()
        if p.get("position") is not None:
            camera.position = vector(p["position"])
        if p.get("target") is not None:
            camera.target = vector(p["target"])
        domain.set_camera_struct(camera)
        return dispatch("get_camera", {}, bridge_state)
    if method == "frame_objects":
        points = [
            read_data(
                dv,
                transform_id(scene, object_id(scene, v), "global_position"),
                scene.get_current_frame(),
            )
            for v in p["objects"]
        ]
        if not points:
            raise ValueError("Specify objects to frame.")
        view.active_viewport().domain_viewport().camera().zoom_to_points(points)
        return dispatch("get_camera", {}, bridge_state)
    if method == "capture_viewport":
        suffix = {".png"}
        path = file_path(
            p["path"], bridge_state, overwrite=p.get("overwrite", False), suffix=suffix
        )
        rp = csc.tools.RenderParameters()
        rp.width = p.get("width", 1280)
        rp.height = p.get("height", 720)
        rp.samples = 1
        if not 64 <= rp.width <= 3840 or not 64 <= rp.height <= 2160:
            raise ValueError("Render size out of bounds.")
        restored = restore_minimized_window()
        tool = app.get_tools_manager().get_tool("RenderToFile")
        tool.take_image(view, rp, str(path))
        return dict(
            path=str(path),
            exists=path.is_file(),
            restored_minimized_window=restored,
            note="A render can finish asynchronously; verify the output file.",
        )
    if method in ("import_fbx", "export_fbx"):
        if (
            method == "export_fbx"
            and optional_call(app, "is_export_available", True) is False
        ):
            raise PermissionError(
                "Export is unavailable under the current Cascadeur license."
            )
        path = file_path(
            p["path"],
            bridge_state,
            exists=method == "import_fbx",
            overwrite=p.get("overwrite", False),
            suffix={".fbx"},
        )
        loader = app.get_tools_manager().get_tool("FbxSceneLoader").get_fbx_loader(view)
        mapping = (
            {
                "scene": "import_scene",
                "animation": "import_animation",
                "model": "add_model",
            }
            if method == "import_fbx"
            else {
                "scene": "export_all_objects",
                "animation": "export_joints",
                "selected": "export_joints_selected",
            }
        )
        if p.get("mode", "scene") not in mapping:
            raise ValueError("Unknown FBX mode.")
        getattr(loader, mapping[p.get("mode", "scene")])(str(path))
        return dict(path=str(path), exists=path.is_file())
    if method == "autopose":
        return autopose(scene, view, app, p, bridge_state)
    if method == "ui_state":
        states = toolbar_states(bridge_state)
        if states is None:
            return dict(
                available=False,
                note="Needs PySide6 matching Cascadeur's Qt; see docs/FIELD_NOTES.md (bridge pyside6_site).",
            )
        query = p.get("query", "").lower()
        return dict(
            available=True,
            buttons={k: v for k, v in sorted(states.items()) if query in k.lower()},
        )
    if method == "list_actions":
        from .actions import ACTIONS

        return {
            "actions": [
                dict(
                    name=k,
                    action_id=v["id"],
                    category=v["category"],
                    verification=v.get(
                        "verification", "documented; outcome unverified"
                    ),
                )
                for k, v in ACTIONS.items()
                if p.get("query", "").lower() in (k + " " + v["category"]).lower()
            ]
        }
    if method == "run_action":
        from .actions import ACTIONS

        if p["name"] not in ACTIONS:
            raise ValueError("Use a name returned by list_actions.")
        item = ACTIONS[p["name"]]
        if p.get("expected_scene") and p["expected_scene"] != view.name():
            raise ValueError("Active scene changed; inspect before editing.")
        app.get_action_manager().call_action(item["id"])
        return dict(
            dispatched=True,
            action=item["id"],
            verification="Action API has no completion/result signal. Inspect event log, poses and preview before claiming success or retrying.",
        )
    raise ValueError("Unknown bridge operation: " + method)
