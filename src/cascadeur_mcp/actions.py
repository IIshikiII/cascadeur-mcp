"""Curated animation actions from Cascadeur's published action ID reference.
These commands have no completion acknowledgement; always verify their result.
https://cascadeur.com/help/category/301
"""

ACTIONS = {}


def group(category, values):
    for name, action_id in values.items():
        ACTIONS[name] = {"id": action_id, "category": category}


group("history", {"undo": "Scene.Undo", "redo": "Scene.Redo"})
group(
    "physics",
    {
        "physics_preview_toggle": "AutoPhysicsTool.Switch Auto Physics",
        "physics_snap": "AutoPhysicsTool.Snap to Auto Physics",
        "physics_priority_frame": "AutoPhysicsTool.Set priority frame",
        "physics_freeze_toggle": "AutoPhysicsTool.Switch Frozen Auto Physics",
        "show_fulcrum_points": "AutoPhysicsTool.Show all fucrum points",
        "clean_foot_contacts": "View.FixFoot",
        "clean_foot_contacts_keep_keys": "View.FixFoot_KeepKeyFrames",
        "add_ballistic_trajectory": "BallisticTrajectoryTool.Add ballistic trajectory",
        "snap_centers_of_mass": "BallisticTrajectoryTool.Snap centers of mass to selected trajectory",
        "ballistic_ghosts_toggle": "BallisticTrajectoryTool.Switch ballistic ghosts",
    },
)
group(
    "posing",
    {
        "autoposing_toggle": "AutoPosingTool.AutoPosing",
        "autoposing_update": "AutoPosingTool.Update",
        "autoposing_unlock": "AutoPosingTool.AutoUnlock",
        "autoposing_lock_toggle": "AutoPosingTool.SwitchLock",
        "show_fingers_toggle": "AutoPosingTool.SwitchFingersDrawing",
        "edit_current_frame": "Scene.Edit mode.Current frame",
        "edit_selected_interval": "Scene.Edit mode.Selection",
        "set_key_on_change": "Scene.Set key on change",
    },
)
group(
    "animation",
    {
        "unbake_animation": "View.Animation unbaking",
        "auto_interpolation_keys": "View.AutoInterpolation_Keys",
        "auto_interpolation_intervals": "View.AutoInterpolation_Interpolations",
        "retarget_copy": "View.Retargeting_Copy",
        "retarget_paste": "View.Retargeting_Paste",
        "play_toggle": "Timeline.Play",
        "next_key": "Timeline.Next key frame",
        "previous_key": "Timeline.Previous key frame",
        "create_cycle": "Timeline.Create cycle",
        "create_cycle_with_offsets": "Timeline.Create cycle with position and rotation offsets",
        "remove_cycles": "Timeline.Remove cycles",
        "key_fk": "Timeline.Change to FK key",
        "key_ik": "Timeline.Change to IK key",
        "key_fulcrum": "Timeline.Change to fulcrum key",
        "copy_pose": "Copier.Copy",
        "paste_pose": "Copier.Paste",
        "copy_interval": "Copier.Copy interval",
        "paste_interval": "Copier.Paste interval",
    },
)
group(
    "review",
    {
        "center_camera": "View.Center camera",
        "silhouette_toggle": "View.Silhouette mode",
        "ghost_keyframes": "GhostTool.Keyframe ghosts",
        "ghost_neighbors": "GhostTool.Neighbor frame ghosts",
        "ghost_disable": "GhostTool.Disable ghost",
        "show_graph_editor": "Window.Graph editor",
        "show_event_log": "Window.Event log",
        "show_physics_settings": "Window.Physics settings",
    },
)


# Full action catalog from https://cascadeur.com/help/category/301 (Cascadeur 2025.x/2026.x).
# Excluded on purpose: File.* (modal file dialogs), Help.*, Settings.* resets, Application.Exit/Home,
# HomeScreen.* and hotkey/settings windows - they can block the app or leave the scene.
CATALOG = {}


def catalog(category, ids):
    for action_id in ids:
        CATALOG[action_id] = category


INTERPOLATIONS = (
    ("Bezier", "Bezier"),
    ("Bezier clamped", "Bezier clamped"),
    ("Bezier viscous", "Bezier viscous"),
    ("Linear", "Linear"),
    ("Step", "Step"),
    ("Fixed", "Fixed"),
)
TWEEN_TARGETS = (
    "average",
    "inertial",
    "interpolation",
    "inverse inertial",
    "next",
    "previous",
)
TWEEN_SCOPES = (
    "Current frame",
    "Current frame (hard)",
    "Selected frames",
    "Selected frames (hard)",
)

catalog(
    "autophysics",
    [
        "AutoPhysicsTool.Set priority frame",
        "AutoPhysicsTool.Snap to Auto Physics",
        "AutoPhysicsTool.Switch Auto Physics",
        "AutoPhysicsTool.Switch Frozen Auto Physics",
        "AutoPhysicsTool.Show all fucrum points",
        "View.FixFoot",
        "View.FixFoot_KeepKeyFrames",
    ],
)
catalog(
    "autoposing",
    [
        "AutoPosingTool.AutoPosing",
        "AutoPosingTool.AutoUnlock",
        "AutoPosingTool.AutoUnlock_MuteCertainErrors",
        "AutoPosingTool.SwitchAdditionalPointsDrawing",
        "AutoPosingTool.SwitchFingersDrawing",
        "AutoPosingTool.SwitchLock",
        "AutoPosingTool.SwitchLockOnInterval",
        "AutoPosingTool.Update",
    ],
)
catalog(
    "ballistic",
    [
        "BallisticTrajectoryTool.Add ballistic trajectory",
        "BallisticTrajectoryTool.Set fixation frame for free rotation",
        "BallisticTrajectoryTool.Snap centers of mass to selected trajectory",
        "BallisticTrajectoryTool.Snap orientation to the ghosts of free rotation",
        "BallisticTrajectoryTool.Switch ballistic ghosts",
    ],
)
catalog(
    "ai",
    [
        "View.MotionGeneration_Run",
        "Scene.Inbetween interpolation switcher",
        "View.Animation unbaking",
        "View.AutoInterpolation_Keys",
        "View.AutoInterpolation_Interpolations",
        "View.MocapTool",
    ],
)
catalog(
    "ghosts",
    [
        "GhostTool.Disable ghost",
        "GhostTool.Disable ghost outline",
        "GhostTool.Ghosts for selected frames",
        "GhostTool.Keyframe ghosts",
        "GhostTool.Neighbor frame ghosts",
        "GhostTool.Next frames ghosts",
        "GhostTool.Previous frames ghosts",
    ],
)
catalog(
    "mirror",
    [
        "MirrorTool.Mirror on current frame",
        "MirrorTool.Mirror on interval",
        "MirrorTool.Mirror pelvis position",
        "MirrorTool.Planes.XY",
        "MirrorTool.Planes.XZ",
        "MirrorTool.Planes.YZ",
    ],
)
catalog(
    "scene",
    [
        "Application.Select all",
        "Application.Repeat last action",
        "Scene.Change fix in objects",
        "Scene.Undo",
        "Scene.Redo",
        "Scene.Edit mode.Change",
        "Scene.Edit mode.Current frame",
        "Scene.Edit mode.Neighbors",
        "Scene.Edit mode.Selection",
        "Scene.Fixing interpolation on change interval",
        "Scene.Pivot mode.Change",
        "Scene.Pivot mode.Fixed pivot",
        "Scene.Pivot mode.Moving pivot",
        "Scene.Set fixed interpolation on change",
        "Scene.Set key on change",
    ],
)
catalog(
    "trajectory",
    [
        "TrajectoryTool.All trajectories",
        "TrajectoryTool.Edge trajectories",
        "TrajectoryTool.Object and edge trajectories",
        "TrajectoryTool.Parent trajectories",
        "TrajectoryTool.Set left border trajectory interval",
        "TrajectoryTool.Set right border trajectory interval",
        "TrajectoryTool.Set trajectory interval",
        "TrajectoryTool.Show fixed set of trajectories",
        "TrajectoryTool.Switch trajectory activity",
        "TrajectoryTool.Switch trajectory fixed mode",
        "TrajectoryTool.Trajectory edit mode",
        "TrajectoryTool.Using only key frames",
        "TrajectoryTool.Translate mode",
        "TrajectoryTool.Rotate mode",
        "TrajectoryTool.Direction mode",
        "TrajectoryTool.Reset Selected Tangents",
    ],
)
catalog(
    "tween_machine",
    [
        "TweenMachine.Attract to %s position.%s" % (target, scope)
        for target in TWEEN_TARGETS
        for scope in TWEEN_SCOPES
    ],
)
catalog(
    "view",
    [
        "View.Center camera",
        "View.Composition",
        "View.Hide not selected",
        "View.Hide selected",
        "View.Make all visible",
        "View.Silhouette mode",
        "View.Retargeting_Copy",
        "View.Retargeting_Paste",
        "Timeline.Clear custom tangents on current frame",
        "Timeline.Clear custom tangents on selected interval",
        "CameraOrientationTool.Look from above",
        "CameraOrientationTool.Look from below",
        "CameraOrientationTool.Look from left",
        "CameraOrientationTool.Look from right",
        "CameraOrientationTool.Switch projection",
        "ObjectWatchingTool.Track selection with camera",
    ],
)
catalog(
    "copier",
    [
        "Copier.Copy",
        "Copier.Copy interval",
        "Copier.Copy timeline interval",
        "Copier.Copy tracks hierarchy",
        "Copier.Paste",
        "Copier.Paste interval",
        "Copier.Paste into interval",
        "Copier.Paste timeline interval",
        "Copier.Paste tracks hierarchy",
    ],
)
catalog(
    "timeline",
    [
        "Timeline.Add frame(s)",
        "Timeline.Add|Remove key",
        "Timeline.Add|Remove key on Interval",
        "Timeline.Add|Remove key on all tracks",
        "Timeline.Change IK|FK key",
        "Timeline.Change IK|FK key on interval",
        "Timeline.Change fulcrum",
        "Timeline.Change to FK key",
        "Timeline.Change to FK key on interval",
        "Timeline.Change to GR key",
        "Timeline.Change to GR key on interval",
        "Timeline.Change to IK key",
        "Timeline.Change to IK key on interval",
        "Timeline.Change to fulcrum key",
        "Timeline.Change to fulcrum key on interval",
        "Timeline.Create cycle",
        "Timeline.Create cycle with position and rotation offsets",
        "Timeline.Create cycle with position offset",
        "Timeline.Remove cycles",
        "Timeline.Resize cycles",
        "Timeline.Set cycle inactive frames",
        "Timeline.Loop mode",
        "Timeline.Merge tracks",
        "Timeline.Move frames left",
        "Timeline.Move frames right",
        "Timeline.Remove frames",
        "Timeline.Next frame",
        "Timeline.Previous frame",
        "Timeline.Next key frame",
        "Timeline.Previous key frame",
        "Timeline.To first frame",
        "Timeline.To last frame",
        "Timeline.Play",
        "Timeline.Keyframe play",
        "Timeline.Select all tracks",
        "Timeline.Set timeline by selected",
        "Timeline.Tracks stretching mode",
        "Timeline.Resize interval",
        "Timeline.Expand selection left",
        "Timeline.Expand selection right",
        "Timeline.Narrow selection left",
        "Timeline.Narrow selection right",
    ]
    + [
        "Timeline.%s.%s on %s" % (group, name, scope)
        for group, name in INTERPOLATIONS
        for scope in ("current frame", "selected interval")
    ]
    + [
        "Timeline.IK FK type.%s on %s" % (kind, scope)
        for kind in ("FK type", "GR type", "IK FK type", "IK type")
        for scope in ("current frame", "selected interval")
    ],
)
catalog(
    "visibility",
    [
        "Visible." + name
        for name in (
            "Always show selected objects",
            "Auto Posing",
            "AutoPhysics Fulcrum Points",
            "AutoPhysics Ghosts",
            "AutoPhysics Trajectories Center Mass",
            "Ballistic Trajectories",
            "Boxes",
            "Centers of Mass",
            "Centers of Mass Grounder",
            "Colliders",
            "Edges",
            "Joints",
            "Manipulators",
            "Objects Trajectories",
            "Pivot",
            "Points",
            "Rigid Bodies",
            "Shaded Meshes",
            "Wireframe Meshes",
            "X-Ray",
        )
    ]
    + [
        "VisualizerStateController.AllModes." + mode
        for mode in (
            "AutoPosing mode",
            "Box controller mode",
            "Joint mode",
            "Mesh mode",
            "Point controller mode",
            "View mode",
        )
    ],
)
catalog(
    "windows",
    [
        "Window." + name
        for name in (
            "Node editor",
            "Control picker",
            "Event log",
            "Graph editor",
            "Object properties",
            "Outliner",
            "Physics settings",
            "Tween Machine",
            "Python console",
            "Scene settings",
            "Timeline",
        )
    ],
)
for _item in ACTIONS.values():
    CATALOG.setdefault(_item["id"], _item["category"])

# Toolbar toggles whose real state is readable through the PySide6 UI bridge (button `active`).
MODES = {
    "autoposing": "AutoPosingTool.AutoPosing",
    "physics": "AutoPhysicsTool.Switch Auto Physics",
    "physics_frozen": "AutoPhysicsTool.Switch Frozen Auto Physics",
    "fulcrum_points": "AutoPhysicsTool.Show all fucrum points",
    "autoposing_fingers": "AutoPosingTool.SwitchFingersDrawing",
    "autoposing_additional_points": "AutoPosingTool.SwitchAdditionalPointsDrawing",
    "auto_interpolation_keys": "View.AutoInterpolation_Keys",
    "auto_interpolation_intervals": "View.AutoInterpolation_Interpolations",
}
