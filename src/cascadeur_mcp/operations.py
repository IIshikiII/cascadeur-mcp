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
        from PySide6 import QtGui, QtQuick  # noqa: F401

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
        from PySide6 import QtCore, QtGui, QtQuick  # noqa: F401

        # Bindings must target the Qt version Cascadeur has loaded (e.g. 6.5.1.1 on 6.5.1).
        return QtGui if PySide6.__version__.startswith(QtCore.qVersion()) else None
    except Exception:
        return None


def live_windows(gui):
    """Visible QQuickWindows; stale PySide wrappers of deleted popups are skipped."""
    windows = []
    for window in gui.QGuiApplication.topLevelWindows():
        try:
            if window.isVisible() and hasattr(window, "contentItem"):
                windows.append(window)
        except RuntimeError:
            continue
    return windows


def main_window(gui):
    for window in live_windows(gui):
        if window.objectName() == "MainWindow":
            return window
    return None


def toolbar_states(bridge_state):
    """{action id: active} for toolbar buttons of the main window, or None without PySide6."""
    gui = qt_gui(bridge_state)
    window = None if gui is None else main_window(gui)
    if window is None:
        return None
    states = {}

    def walk(item):
        action = item.property("actionId")
        if action and item.property("visible"):
            states[action] = states.get(action, False) or bool(item.property("active"))
        for child in item.childItems():
            walk(child)

    walk(window.contentItem())
    return states


def ui_messages(bridge_state):
    """Visible status/notification texts, e.g. 'AutoPhysics status: ... CONVERGENCE'."""
    import re

    gui = qt_gui(bridge_state)
    window = None if gui is None else main_window(gui)
    if window is None:
        return []
    pattern = re.compile(r"status:|: done|error|warning|failed|not possible", re.I)
    found = []

    def walk(item):
        text = item.property("text")
        if isinstance(text, str) and item.property("visible") and pattern.search(text):
            found.append(text.strip()[:300])
        for child in item.childItems():
            walk(child)

    walk(window.contentItem())
    return sorted(set(found))


def _collect_texts(item, texts, buttons):
    text = item.property("text")
    if isinstance(text, str) and text.strip() and item.property("visible"):
        if "Button" in item.metaObject().className():
            buttons.setdefault(text.strip(), item)
        elif text.strip() not in texts:
            texts.append(text.strip())
    for child in item.childItems():
        _collect_texts(child, texts, buttons)


def open_dialogs(bridge_state):
    """Visible modal QML dialogs with their texts and buttons (e.g. the Snap warning)."""
    gui = qt_gui(bridge_state)
    if gui is None:
        return []
    dialogs = []
    for window in live_windows(gui):
        modality = str(window.modality()).split(".")[-1]
        if window.objectName() == "MainWindow" or modality == "NonModal":
            continue
        texts, buttons = [], {}
        _collect_texts(window.contentItem(), texts, buttons)
        dialogs.append(
            dict(window=window, title=window.title(), texts=texts, buttons=buttons)
        )
    return dialogs


def click_item(item):
    """Synthetic left click on a QML item (move + press + release; the move is required)."""
    from PySide6 import QtCore, QtGui

    window = item.window()
    local = item.mapToScene(QtCore.QPointF(item.width() / 2, item.height() / 2))
    global_pos = QtCore.QPointF(window.mapToGlobal(local.toPoint()))
    for kind, button, buttons in (
        (QtCore.QEvent.MouseMove, QtCore.Qt.NoButton, QtCore.Qt.NoButton),
        (QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton),
        (QtCore.QEvent.MouseButtonRelease, QtCore.Qt.LeftButton, QtCore.Qt.NoButton),
    ):
        event = QtGui.QMouseEvent(
            kind, local, global_pos, button, buttons, QtCore.Qt.NoModifier
        )
        QtCore.QCoreApplication.sendEvent(window, event)


def answer_dialog(bridge_state, button):
    for dialog in open_dialogs(bridge_state):
        for label, item in dialog["buttons"].items():
            if label.lower() == button.lower():
                click_item(item)
                return dict(title=dialog["title"], texts=dialog["texts"], clicked=label)
    raise ValueError(
        "No open dialog with button %r. Open dialogs: %s"
        % (
            button,
            [(d["title"], list(d["buttons"])) for d in open_dialogs(bridge_state)],
        )
    )


def schedule_dialog_answer(bridge_state, button, delay_ms=1500, attempts=8):
    """Answer a modal dialog that an action is about to open. Timers keep running inside the
    dialog's nested event loop, so a single-shot QTimer can press the button."""
    import builtins

    from PySide6 import QtCore

    state = {"left": attempts}

    def tick():
        try:
            answer_dialog(bridge_state, button)
            return
        except Exception:
            state["left"] -= 1
            if state["left"] > 0:
                QtCore.QTimer.singleShot(delay_ms, tick)

    builtins._cascadeur_mcp_dialog_tick = tick  # keep the callable alive
    QtCore.QTimer.singleShot(delay_ms, tick)


def set_mode(app, bridge_state, action_id, on):
    """Switch a toolbar toggle to an explicit state instead of blindly toggling it."""
    before = (toolbar_states(bridge_state) or {}).get(action_id)
    if before is None:
        raise RuntimeError(
            "Toggle state is not readable (needs the PySide6 bridge and a visible toolbar button)."
        )
    if before != on:
        app.get_action_manager().call_action(action_id)
    after = (toolbar_states(bridge_state) or {}).get(action_id)
    return dict(action=action_id, before=before, after=after, changed=before != after)


# Physics Settings panel values (Cascadeur_tools.ini) readable through View.get_setting_handler.
PHYSICS_SETTINGS = {
    ("Physics", "Gravity"): float,
    ("Physics", "Work on interval"): bool,
    ("AutoPhysics", "Physics corrector"): bool,
    ("AutoPhysics", "Physics Alpha"): float,
    ("AutoPhysics", "Smooth trajectory"): bool,
    ("AutoPhysics", "Trajectory alpha"): float,
    ("AutoPhysics", "Smooth rotation"): bool,
    ("AutoPhysics", "Rotation alpha"): float,
    ("AutoPhysics", "Compensation motion"): bool,
    ("AutoPhysics", "Compensation alpha"): float,
    ("AutoPhysics", "Separation of motion"): bool,
    ("AutoPhysics", "Separation alpha"): float,
    ("AutoPhysics", "Secondary motion"): bool,
    ("AutoPhysics", "Secondary alpha"): float,
    ("Ragdoll", "Ragdoll"): bool,
    ("Secondary motion", "With gravity"): bool,
    ("Secondary motion", "Floor collision"): bool,
}


def physics_settings(view):
    handler = view.get_setting_handler()
    values = {}
    for (group, key), kind in PHYSICS_SETTINGS.items():
        getters = (
            [handler.get_bool_value]
            if kind is bool
            else [handler.get_float_value, handler.get_int_value]
        )
        for getter in getters:
            try:
                values["%s/%s" % (group, key)] = getter(group, key)
                break
            except Exception:
                continue
    return values


def _find_items(item, predicate, out, limit=50):
    if len(out) >= limit:
        return out
    if predicate(item):
        out.append(item)
    for child in item.childItems():
        _find_items(child, predicate, out, limit)
    return out


def scroll_into_view(item):
    """Scroll the nearest Flickable so the item is visible (clicks outside the viewport miss)."""
    from PySide6 import QtCore

    flick = item.parentItem()
    while flick is not None and flick.property("contentY") is None:
        flick = flick.parentItem()
    if flick is None:
        return
    pos = item.mapToItem(flick, QtCore.QPointF(0, item.height() / 2)).y()
    if pos < 0 or pos > flick.height():
        flick.setProperty(
            "contentY", max(0.0, flick.property("contentY") + pos - flick.height() / 2)
        )


def set_physics_setting(view, bridge_state, name, on):
    """Flip an On/Off switch of the Physics Settings panel through the UI (no API setter exists)."""
    group, key = name.split("/", 1) if "/" in name else ("AutoPhysics", name)
    if PHYSICS_SETTINGS.get((group, key)) is not bool:
        raise ValueError(
            "Only On/Off physics settings are supported: "
            + ", ".join("%s/%s" % k for k, v in PHYSICS_SETTINGS.items() if v is bool)
        )
    handler = view.get_setting_handler()
    before = handler.get_bool_value(group, key)
    if before == on:
        return dict(setting=name, before=before, after=before, changed=False)
    gui = qt_gui(bridge_state)
    window = None if gui is None else main_window(gui)
    if window is None:
        raise RuntimeError("Needs the PySide6 bridge.")

    def rows():
        found = []
        for win in live_windows(gui):
            for label in _find_items(
                win.contentItem(),
                lambda i: (
                    i.property("text") == key
                    and i.property("visible")
                    and i.metaObject().className().startswith("Text")
                ),
                [],
            ):
                buttons = _find_items(
                    label.parentItem(),
                    lambda i: i.metaObject().className().startswith("CheckButton"),
                    [],
                )
                if len(buttons) == 2:
                    found.append(buttons)
        return found

    found = rows()
    if not found:  # the panel is a tab next to the Outliner, or a closed window
        tabs = _find_items(
            window.contentItem(),
            lambda i: (
                i.property("text") == "Physics settings"
                and "TabButton" in i.metaObject().className()
            ),
            [],
        )
        if tabs:
            click_item(tabs[0])
        else:
            app_ = __import__("csc").app.get_application()
            app_.get_action_manager().call_action("Window.Physics settings")
        found = rows()
    if not found:
        raise RuntimeError("Physics Settings row %r not found in the UI." % key)
    target = [
        b
        for b in found[0]
        if str(b.property("text")).lower() == ("on" if on else "off")
    ]
    scroll_into_view(target[0])
    click_item(target[0])
    after = handler.get_bool_value(group, key)
    return dict(setting=name, before=before, after=after, changed=before != after)


def ui_screenshot(bridge_state, path):
    gui = qt_gui(bridge_state)
    if gui is None:
        raise RuntimeError("Needs the PySide6 bridge (pyside6_site).")
    shots = []
    for i, window in enumerate(live_windows(gui)):
        target = (
            path
            if window.objectName() == "MainWindow"
            else path.with_name("%s_window%d%s" % (path.stem, i, path.suffix))
        )
        if window.objectName() == "MainWindow" or window.width() > 200:
            window.grabWindow().save(str(target))
            shots.append(
                dict(
                    path=str(target),
                    title=window.title(),
                    main=window.objectName() == "MainWindow",
                )
            )
    return shots


# Point "Fulcrum State" channel (Object Properties > Fulcrum): automatic detection, forced, never.
FULCRUM_STATES = {"auto": 0, "enforce": 1, "never": 2}


def set_contacts(scene, p):
    """Mark foot/hand contacts: fulcrum key+interval fixation on tracks and the point fulcrum state."""
    import csc

    L = csc.layers.layer
    lv = scene.layers_viewer()
    state = FULCRUM_STATES[p.get("point_state", "enforce")]
    points = [object_id(scene, name) for name in p["points"]]
    layers = {}
    for oid in points:
        lid = lv.layer_id_by_obj_id_or_null(oid)
        if lid.is_null():
            raise ValueError(
                "Point has no animation track: %s"
                % scene.model_viewer().get_object_name(oid)
            )
        layers[str(lid)] = lid
    intervals = [(frame_number(a), frame_number(b)) for a, b in p["intervals"]]
    for a, b in intervals:
        if b < a:
            raise ValueError("Interval end must be >= start.")
    bv = scene.behaviour_viewer()
    state_ids = []
    for oid in points:
        beh = bv.get_behaviour_by_name(oid, "FulcrumPoint")
        did = bv.get_behaviour_data(beh, "fulcrum_state") if not beh.is_null() else None
        if did is not None and not did.is_null():
            state_ids.append(did)
    report = []

    def edit(me, ue, su):
        le = me.layers_editor()
        de = me.data_editor()
        for lid in layers.values():
            layer = lv.layer(lid)
            keys = set(layer.key_frame_indices())
            for a, b in intervals:
                for f in (a, b):
                    if f not in keys:
                        le.set_fixed_interpolation_or_key_if_need(lid, f, True)
                inside = sorted(
                    k
                    for k in set(lv.layer(lid).key_frame_indices()) | {a, b}
                    if a <= k <= b
                )
                for f in inside:

                    def change(section, f=f, b=b):
                        section.key.common.fixation = L.Fixation.Fulcrum
                        section.interval.common.fixation = (
                            L.Fixation.Fulcrum if f < b else L.Fixation.Free
                        )

                    le.change_section(f, lid, change)
                report.append(
                    dict(track=lv.header(lid).name, interval=[a, b], keys=inside)
                )
        le.normalize_sections(scene)
        me.fit_animation_size_by_layers()
        for a, b in intervals:
            for f in sorted({a, b}):
                for did in state_ids:
                    de.set_data_value(did, f, state)

    modify(scene, "MCP set contacts", edit)
    return dict(
        contacts=report, point_state=p.get("point_state", "enforce"), points=len(points)
    )


def physics_snap(scene, app, bridge_state, p):
    """Snap the animation to the AutoPhysics result and report how much it moved.

    Snap is dispatched asynchronously; when Secondary/Compensation/Separation motion or
    smoothing are enabled Cascadeur opens a modal "apply only once" warning. `answer` ("Yes"
    disables those features after snapping, "No" keeps them) is pressed automatically.
    The measurement is returned by a follow-up call: `cascadeur_sample_motion`.
    """
    if qt_gui(bridge_state) is None:
        raise RuntimeError(
            "Needs the PySide6 bridge to verify the physics state and dialogs."
        )
    mode = set_mode(app, bridge_state, "AutoPhysicsTool.Switch Auto Physics", True)
    if not mode["after"]:
        raise RuntimeError("Could not enable AutoPhysics.")
    answer = p.get("answer", "Yes")
    if answer:
        schedule_dialog_answer(bridge_state, answer)
    app.get_action_manager().call_action("AutoPhysicsTool.Snap to Auto Physics")
    return dict(
        physics_enabled_now=mode["changed"],
        dialog_answer=answer,
        note="Snap runs asynchronously. Compare cascadeur_sample_motion before/after, render, "
        "and read cascadeur_ui_state (messages/dialogs) to confirm.",
    )


def physics_priority_frames(scene, p):
    """Set or clear AutoPhysics priority frames (animated `priority_frame` on the Center of Mass)."""
    bv, dv, mv = scene.behaviour_viewer(), scene.data_viewer(), scene.model_viewer()
    targets = []
    for oid in mv.get_objects():
        beh = bv.get_behaviour_by_name(oid, "AutoPhysics")
        if not beh.is_null():
            targets.append(
                (mv.get_object_name(oid), bv.get_behaviour_data(beh, "priority_frame"))
            )
    if not targets:
        raise ValueError(
            "No Center of Mass with an AutoPhysics behaviour in this scene."
        )
    frames = [frame_number(f) for f in p["frames"]]
    on = bool(p.get("on", True))

    def edit(me, ue, su):
        for _, did in targets:
            for f in frames:
                me.data_editor().set_data_value(did, f, on)

    modify(scene, "MCP physics priority frames", edit)
    return dict(
        centers=[n for n, _ in targets],
        frames={
            f: [bool(dv.get_data_value(did, f)) for _, did in targets] for f in frames
        },
        note="Values on non-key frames are overwritten by interpolation; use key frames.",
    )


def restore_minimized_window():
    """Restore a minimized Cascadeur main window (Windows only).

    Viewport renders are queued until the window repaints; a minimized window never does,
    so captures silently wait until the user restores it. Only the visible, titled main window
    is touched. SW_SHOWNOACTIVATE was tried first and left the window "visible" but parked at
    the minimized position (-25600, -25600 at 125% DPI), i.e. invisible to the user; a plain
    SW_RESTORE is used instead, also for a window stuck at such coordinates.
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
        if (
            owner.value == pid
            and user32.IsWindowVisible(hwnd)
            and user32.GetWindowTextLengthW(hwnd) > 0
            and user32.GetParent(hwnd) == 0
        ):
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            if user32.IsIconic(hwnd) or rect.left < -10000 or rect.top < -10000:
                found.append(hwnd)
        return True

    user32.EnumWindows(collect, 0)
    for hwnd in found:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
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
    """Re-solve key poses with AutoPosing: anchors are active (blue), the rest is predicted.

    Verified mechanics: controllers are Tool_object_ids found via Select all in the AutoPosing
    viewport; switching the mode on syncs them to the rig pose; SwitchLock toggles selected
    controllers blue/green; Update regenerates the green ones from the blue ones.
    Lock state is not exposed and is inherited by keys created between locked keys, so each
    frame is probed: Update without toggling; anchors that stay are already locked, anchors that
    move are locked and Update runs again. Frames are restored from a snapshot when anchors drift.
    """
    import csc
    import numpy as np

    mv, dv = scene.model_viewer(), scene.data_viewer()
    lv = scene.layers_viewer()
    am = app.get_action_manager()
    dvp = view.active_viewport().domain_viewport()
    VM = csc.view.ViewportMode
    null = csc.model.ObjectId.null()
    anchors = list(p.get("anchors") or AUTOPOSE_ANCHORS)
    release = [n for n in (p.get("release") or []) if n not in anchors]
    limit = float(p.get("max_anchor_drift", 3.0))
    include_directions = bool(p.get("include_directions", True))
    frames = [frame_number(f) for f in p["frames"]]
    if not frames or len(frames) > 200:
        raise ValueError("Provide 1 to 200 key frames.")
    points = {
        mv.get_object_name(o): transform_id(scene, o, "global_position")
        for o in mv.get_objects()
        if mv.get_object_type_name(o) == "Point"
    }
    unknown = [n for n in anchors + release if n not in points]
    if unknown:
        raise ValueError("Unknown anchor points: " + ", ".join(unknown))
    for f in frames:
        for name in anchors:
            lid = lv.layer_id_by_obj_id_or_null(object_id(scene, name))
            if not lid.is_null() and not lv.layer(lid).is_key(f):
                raise ValueError(
                    "Frame %d is not a key on the track of %s." % (f, name)
                )

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

    def tool_positions(tool_ids):
        pivot = scene.selector().pivot()
        out = {}
        for t in tool_ids:
            pivot.select(t)
            out[t] = np.array(pivot.position(), dtype=float).ravel()
        return out

    def attempt(f, toggle_names, toggle_directions, update=True):
        """Mode on -> SwitchLock the named controllers -> Update -> mode off.

        toggle_directions: True = every direction controller, or a set of their indices (sorted
        by position) to toggle. Returns the indices of direction controllers that moved in Update
        (those are green: predicted by the network)."""
        am.call_action("AutoPosingTool.AutoPosing")  # on: controllers sync to the rig
        try:
            tools, by_name, directions = controllers(f)
            if not tools:
                raise RuntimeError("No AutoPosing controllers found for this rig.")
            directions = sorted(directions, key=lambda t: tuple(np.round(tool_positions([t])[t], 1)))
            toggle = {by_name[n] for n in toggle_names if n in by_name}
            if toggle_directions is True:
                toggle |= set(directions)
            elif toggle_directions:
                toggle |= {directions[i] for i in toggle_directions if i < len(directions)}
            if toggle:
                select(toggle)
                am.call_action("AutoPosingTool.SwitchLock")
            before_dirs = tool_positions(directions)
            if update:
                am.call_action("AutoPosingTool.Update")
            after_dirs = tool_positions(directions)
            moved_dirs = {
                i for i, t in enumerate(directions)
                if np.linalg.norm(after_dirs[t] - before_dirs[t]) > 0.5
            }
            select(set())
            return len(tools), [n for n in anchors if n not in by_name], len(toggle), moved_dirs
        finally:
            am.call_action(
                "AutoPosingTool.AutoPosing"
            )  # off: the pose stays in the rig

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
            count, missing, _, green_dirs = attempt(
                f, [], False
            )  # probe: which anchors (and direction controllers) are active?
            moved = {
                n: float(np.linalg.norm(read(n, f) - before[n]))
                for n in set(anchors) | set(release)
            }
            green = [n for n in anchors if moved[n] > limit]
            # An active controller does not move at all during Update; release those.
            blue_released = [n for n in release if moved[n] < 0.01]
            # Orientation of pelvis/chest/head/hands/feet lives on direction controllers; left
            # green, the network may turn a body part 180 degrees about its own axis.
            lock_dirs = green_dirs if include_directions else set()
            status, toggled = "ok (anchors already active)", 0
            if green or blue_released or lock_dirs:
                restore(before, f)
                mostly_green = len(green) > len(anchors) // 2
                count, missing, toggled, _ = attempt(
                    f, green + blue_released, True if mostly_green and not include_directions else lock_dirs
                )
                if max(np.linalg.norm(read(n, f) - before[n]) for n in anchors) > limit:
                    restore(before, f)
                    attempt(
                        f, green + blue_released,
                        True if mostly_green and not include_directions else lock_dirs, update=False
                    )  # undo the lock toggle
                    status = "restored: anchors still drift after locking"
                else:
                    status = "ok (toggled %d controllers incl. %d directions, released %s)" % (
                        toggled,
                        len(lock_dirs),
                        blue_released,
                    )
            after = {n: read(n, f) for n in points}
            moved = {n: float(np.linalg.norm(after[n] - before[n])) for n in points}
            report.append(
                dict(
                    frame=f,
                    status=status,
                    controllers=count,
                    missing_anchors=missing,
                    anchor_drift_cm=round(max(moved[n] for n in anchors), 2),
                    moved_cm={
                        n: round(v, 1)
                        for n, v in sorted(moved.items(), key=lambda x: -x[1])
                        if v >= 0.5
                    },
                )
            )
    finally:
        dvp.set_mode_visualizers(VM.View)
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
    if method == "call_action":
        from .actions import CATALOG, MODES

        action_id = p["action_id"]
        if action_id not in CATALOG:
            raise ValueError(
                "Unknown or excluded action ID; see cascadeur_list_actions."
            )
        if p.get("expected_scene") and p["expected_scene"] != view.name():
            raise ValueError("Active scene changed; inspect before editing.")
        watched = action_id in MODES.values()
        before = (
            (toolbar_states(bridge_state) or {}).get(action_id) if watched else None
        )
        if p.get("answer"):
            if qt_gui(bridge_state) is None:
                raise RuntimeError("Answering dialogs needs the PySide6 bridge.")
            schedule_dialog_answer(bridge_state, p["answer"])
        app.get_action_manager().call_action(action_id)
        after = (toolbar_states(bridge_state) or {}).get(action_id) if watched else None
        return dict(
            dispatched=True,
            action=action_id,
            toggle_before=before,
            toggle_after=after,
            note="Actions report no result; verify poses/renders (selection and frame interval matter).",
        )
    if method == "set_mode":
        from .actions import MODES

        if p["mode"] not in MODES:
            raise ValueError("Unknown mode. Known: " + ", ".join(sorted(MODES)))
        return set_mode(app, bridge_state, MODES[p["mode"]], bool(p["on"]))
    if method == "physics_settings":
        changes = [
            set_physics_setting(view, bridge_state, name, bool(value))
            for name, value in (p.get("set") or {}).items()
        ]
        return dict(changes=changes, values=physics_settings(view))
    if method == "answer_dialog":
        if qt_gui(bridge_state) is None:
            raise RuntimeError("Needs the PySide6 bridge.")
        return answer_dialog(bridge_state, p["button"])
    if method == "physics_snap":
        return physics_snap(scene, app, bridge_state, p)
    if method == "ui_screenshot":
        path = file_path(p["path"], bridge_state, overwrite=True, suffix={".png"})
        restore_minimized_window()
        return dict(windows=ui_screenshot(bridge_state, path))
    if method == "set_contacts":
        return set_contacts(scene, p)
    if method == "physics_priority_frames":
        return physics_priority_frames(scene, p)
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
            messages=ui_messages(bridge_state),
            dialogs=[
                dict(title=d["title"], texts=d["texts"], buttons=list(d["buttons"]))
                for d in open_dialogs(bridge_state)
            ],
        )
    if method == "list_actions":
        from .actions import ACTIONS, CATALOG

        if p.get("catalog"):
            query = p.get("query", "").lower()
            grouped = {}
            for action_id, category in sorted(CATALOG.items()):
                if query in (action_id + " " + category).lower():
                    grouped.setdefault(category, []).append(action_id)
            return {"catalog": grouped, "count": sum(map(len, grouped.values()))}
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
