# Cascadeur MCP — field notes

Practical knowledge collected while animating real shots (hand wave, jump spinning kick) with this server
on Windows, Cascadeur 2025.x (Qt 6.5.1, embedded Python 3.11). Everything marked **verified** was
measured in the live app; **unverified** means observed once or inferred. Read this before animating.

## 1. Session setup

- Start the bridge inside Cascadeur after every launch: **Window → Python Console**, run
  `exec(open(r"<...>\cascadeur-setup\start_bridge.py").read())`. Re-running is safe (it stops the old bridge).
- `run_script` needs both switches: `allow_scripts=True` in `start_bridge.py` **and** `--allow-scripts`
  in the server args. `cascadeur_status` shows `allow_scripts`.
- Registering in PowerShell: the `claude.ps1` shim swallows a bare `--`, giving
  `error: unknown option '-m'`. Quote it: `claude mcp add cascadeur -s user '--' "<python.exe>" -m cascadeur_mcp ...`.
- Windows file-lock race: occasional `PermissionError` on `session\response-*.json` / `status.json`
  ("bridge is not connected"). Retrying the call works (the operation itself is fine).
- `save_scene` to a new path **renames the open tab** to that file name. `run_action(expected_scene=...)`
  must use the current tab name (`cascadeur_get_state` → `name`).
- A scene opened from disk has `path: null` in `get_state`; always save explicitly with an absolute path
  inside the workspace.

## 2. Driving the app from Python (bypassing MCP payload limits)

For dense edits (hundreds of transforms) call the bridge directly from the server venv instead of
pasting huge JSON into tool calls:

```python
import asyncio, sys
sys.path.insert(0, r"<repo>\src")
from cascadeur_mcp.bridge import Bridge
b = Bridge(r"<work>\session", r"<work>\animations", timeout=300)
asyncio.run(b.call("animate_transforms", dict(keyframes=[...], interpolation="BEZIER")))
```

Method names/params are the same as the MCP tools without the `cascadeur_` prefix. Wrap calls in a
retry on `PermissionError` (see §1).

Inside `run_script` you get `csc, app, view, scene`. Useful, verified entry points:

| Need | Call |
| --- | --- |
| Undoable edit with selection access | `scene.modify_update_with_session(label, cb)`; `cb(model_editor, update, scene_updater, session)` |
| Write animated value | `model_editor.data_editor().set_data_value(data_id, frame, value)` |
| Transform data id | `bv.get_behaviour_data(bv.get_behaviour_by_name(obj, 'Transform'), 'global_position')` |
| Object by name | `list(scene.model_viewer().get_objects('hand_MainPoint_r'))[0]` |
| Select anything (incl. tool objects) | `session.take_selector().select(ids_set, first_id)` |
| Read selection | `scene.selector().selected().ids` (may contain `csc.domain.Tool_object_id`) |
| Position of a (tool) object | `pv = scene.selector().pivot(); pv.select(id); pv.position()` |
| Any menu command | `app.get_action_manager().call_action('<Action ID>')` (IDs: https://cascadeur.com/help/category/301) |
| Settings (not animated) | `dv.get_setting_value(bv.get_behaviour_setting(beh, 'fixed'))` |

Offline API reference shipped with the app: `<Cascadeur>\resources\scripts\python\samples\api_document.py`.
Shipped scripts in `resources\scripts\python\` are good examples (e.g. `commands\animation_scripts\invert_selection.py`).
Online docs: https://cascadeur.com/help/introduction (AutoPosing page: `/help/tools/animation_tools/autoposing`).

## 3. The Cascy rig (bundled `Cascy.casc`)

- Y up, character faces **+Z**, its right side is **−X**, units ≈ cm, rest pelvis at y≈91, head top ≈175.
- 12 tracks (layers): `Body, Head, Arm_R/L, Hand_R/L, Leg_R/L, Foot_R/L, Fingers_R/L`. Keying one object keys
  the **whole track** at that frame.
- **Animate Point controllers with global positions.** Box rotations on the body are derived from points;
  writing `chest_Box`/`head_Box` rotation deltas gave inconsistent, non-local results. Only finger Boxes
  respond predictably to rotation deltas.
- Limb points: `arm_MainPoint` = shoulder, `forearm_MainPoint` = elbow, `hand_MainPoint` = wrist;
  `thigh_MainPoint` = hip, `calf_MainPoint` = knee, `foot_MainPoint` = ankle, `toe_MainPoint` = ball.
  `*_AdditionalPoint` of forearm/calf sit ~8/15 cm to the side of the elbow/knee (hinge-axis helpers).
  Hand orientation = `hand_DirectionPoint` (along fingers) + `hand_AdditionalPoint`.
- Fingers: local X curls. **Right hand +X curls, left hand −X curls** (mirrored axes, verified on index1).
  Thumb1 folds on +Z both sides. Other segments were NOT calibrated — a guessed fist looked broken on
  most frames. Leave fingers un-keyed (the rest pose is a natural relaxed hand) unless you calibrate every
  box with closeup renders.

## 4. Keys, interpolation and hidden pitfalls

- **Writing a value on a non-key frame is overwritten by interpolation.** Create the key first
  (`set_keys`/`animate_transforms` do that). Several "the edit did nothing" results were this.
- **Stale data in old keys:** channels you never write keep whatever was stored when a key was created.
  A leftover key from an early experiment produced a knee pop on one frame. Fix: remove that key on all
  tracks and recreate it (untouched channels then take interpolated values).
- Removing keys: frame 0 is protected by the server; list tracks first.
- The rig solver drags "planted" feet by 0.1–0.4 cm when the pelvis moves. If you correct it by shifting
  the body, make the correction **smooth in time**; per-key independent corrections caused whole-body pops.
- Bezier on dense keys is smooth, but the result is effectively baked: Cascadeur tools can't improve it.
  Prefer ~10–20 animator key poses and let interpolation/AutoPosing/AutoPhysics work (user preference).

## 5. Hand-made IK: what went wrong (if you must compute poses yourself)

- Knee/elbow pole straight "forward" makes knees collapse inward (valgus) in wide stances. Use the
  **rest-pose bend direction**, yawed with the foot, opening slightly outward as the joint bends.
- Orient air feet from the shin and knee direction (toes follow the kneecap). "Minimal rotation from
  rest" accumulates twist and flips feet.
- A kicking leg sweeping backward almost parallel to the pole flips the IK plane; lift the pole upward.
- Better: don't hand-solve knees/elbows at all — use AutoPosing (§7) with anchors only.

## 6. Contacts (fulcrums) and AutoPhysics

Two independent contact mechanisms (both set by `cascadeur_set_contacts`):

- **Fulcrum keys** — key/interval property of a track (the timeline's "fulcrum key"):
  ```python
  L = csc.layers.layer
  def change(section):
      section.key.common.fixation = L.Fixation.Fulcrum        # key is a contact
      section.interval.common.fixation = L.Fixation.Fulcrum   # stays planted until next key (Free on take-off)
  model_editor.layers_editor().change_section(frame, layer_id, change)
  ```
  A whole track becomes fulcrum: pass toe/heel points only (`foot_MainPoint_*` lives on `Leg_*`, so the knee
  would become a fulcrum too).
- **Point `Fulcrum State`** (Object Properties > Fulcrum): 0 = automatic detection (point near the floor and
  nearly still), 1 = Enforce, 2 = NotFulcrum. (An earlier note here claimed it did nothing — wrong; the check
  used an API that only reports during a solve.)
- With AutoPhysics on, the timeline shows a coloured strip: green = strong support, yellow = weak,
  orange = ballistic (no fulcrums), grey = unused. Recognised fulcrums get green circles in the viewport.
- `Timeline.Change to fulcrum key` via `run_action` needs a timeline key selection; prefer the tool.

AutoPhysics (all verified 2026-09-29):

- Toggle state is readable through the PySide6 bridge; `cascadeur_set_mode("physics", on)` is idempotent.
- `cascadeur_physics_snap` works. With Secondary/Compensation/Separation motion or smoothing enabled,
  Snap opens an **application-modal "Warning" QQuickView** ("...are intended to be applied only once...")
  with Yes/No. Modal dialogs do not block the bridge: Qt timers keep firing inside the dialog's nested event
  loop, so a single-shot QTimer (or a later MCP call) can press the button. "Yes" disables those features
  after snapping. Measured on the kick: pelvis moved up to 23.6 cm in flight, planted foot ≤ 0.5 cm.
- Physics Settings values live in the app settings (`%LOCALAPPDATA%\Nekki Limited\Cascadeur\Cascadeur_tools.ini`,
  sections `[Physics]`, `[AutoPhysics]`, `[Secondary motion]`, ...). Read with
  `view.get_setting_handler().get_bool_value(group, key)` / `get_float_value`; there is **no API setter**.
  `cascadeur_physics_settings(set={...})` flips On/Off switches through the UI: switch the right panel to the
  "Physics settings" tab, find the row's `BoolSwitcher` → two `CheckButton`s (Off/On), scroll the enclosing
  `Flickable` so the button is in its viewport (clicks outside it hit nothing), click, re-read the setting.
  Invoking `clicked()`/`accessiblePressAction()` does not update the setting; only a real (synthetic) click does.
- Priority frames = animated `priority_frame` on the Center of Mass `AutoPhysics` behaviour (also
  `frame_weight`, `rotation_blending`, `vertical_jerk`, `horizontal_jerk`); `cascadeur_physics_priority_frames`.
- **Secondary Motion** rewrites values in existing keys. On dense keys it moved the whole wave amplitude
  into the wrist ("floppy sausage arm"). Use sparse keys; it is applied once by Snap.

## 7. AutoPosing from a script — verified recipe

Semantics (docs + tests): in AutoPosing mode, **blue** controllers are active and define the pose,
**green** ones are predicted by the network. `SwitchLock` (Shift+Z) toggles selected controllers
blue↔green. `Update` regenerates green controllers from the blue ones. Anchors stay exact.

1. On a **key frame**, write the rough pose into rig points with AutoPosing mode **off**.
2. `call_action('AutoPosingTool.AutoPosing')` → mode on; controllers sync to the rig pose.
3. Find controller ids (33 `Tool_object_id`s, different per scene/session, no user click needed):
   ```python
   # view mode must be AutoPosing (cascadeur_set_view_mode "AutoPosing")
   app.get_action_manager().call_action('Application.Select all')        # yields 2 seed tool ids
   seeds = {i for i in scene.selector().selected().ids if isinstance(i, csc.domain.Tool_object_id)}
   ids = set().union(*csc.domain.get_all_visible_ids_by_proc(scene, seeds, frame))
   ```
   Map each to a rig point with `pivot.select(t); pivot.position()` (30 coincide with points exactly; the
   remaining 3 are pelvis/chest/head direction controllers ~13–20 cm away).
4. Select anchors (hands, feet, toes, toe directions, pelvis, chest, head + the 3 direction controllers)
   through the session selector and call `AutoPosingTool.SwitchLock` → blue.
5. `call_action('AutoPosingTool.Update')` → knees, elbows, shoulders, spine are re-solved.
   Measured on the kick: anchors moved 0.0 cm, an inverted knee moved 37 cm into a natural position.

Pitfalls: lock state is not readable from the API (visual only) and `SwitchLock` toggles, so start from
all-green controllers; `AutoPosingTool.AutoUnlock` is not "unlock all"; the editor methods
`activate()` (returns False) and `add()` are not needed; controller positions come from the rig only when
the mode is switched on, and a lock remembers the position at lock time.
**Update with no blue controllers regenerates the whole pose** (everything moved 40–58 cm) — never call it
before anchors are locked. Right after switching the mode on, writes to green points still stick, so a
"does a write snap back" probe is not a reliable mode/lock test.

**Lock state is inherited:** a key created between keys whose anchors are blue is blue too. A blind
`SwitchLock` then unlocks them. `cascadeur_autopose` therefore probes every frame: Update without
toggling; anchors that do not move are already active, anchors that move are locked and Update runs
again; frames whose anchors still drift are restored. `release=[...]` makes points green (an active
controller does not move at all during the probe Update) — e.g. release toe points on flight frames so
the network orients the feet.

Pitfall seen on the kick: per-frame network choices can disagree. A foot was twisted 177° around the
shin on one key (toe direction flipped between neighbours). Check continuity numerically (toe direction
in the pelvis frame per frame); fix the outlier by rotating the foot points around the shin axis toward
the neighbours' direction, then lock it with `autopose`.

### `cascadeur_autopose` (server tool)

`cascadeur_autopose(frames=[...], anchors=None, include_directions=True)` automates steps 2–5 per key frame
and leaves the mode off. Safety: takes a snapshot of all points and restores the frame if any anchor
drifts more than 3 cm; remembers frames whose anchors it locked in `<workspace>/.autopose_locks.json`
(keyed by tab name) so reruns do not toggle them back to green. If the user locks/unlocks controllers
by hand, edit or delete that file. With the PySide6 bridge (§9) it reads the real AutoPosing button
state and switches the mode off first if needed.
Result on the kick (13 key frames): anchors moved ≤1.06 cm, elbows up to 18 cm, knees 7–15 cm; the
inverted knees on frames 36/39 became natural.

After editing `src/cascadeur_mcp/operations.py`, copy it to the generated app package
(`<setup>/app/cascadeur_mcp/`) — the running bridge hot-reloads `operations.py`/`actions.py` from there.
`app_bridge.py` changes need the bridge restarted from the Cascadeur console.

## 7b. AI Inbetweening and the action catalog

- In Cascadeur 2025.2 the toolbar button with tooltip **"Inbetweening"** is bound to action
  `View.MotionGeneration_Run`. With a timeline interval selected on the tracks (keys ≤ 120 frames apart)
  it generates the in-betweens locally in a few seconds; the interval becomes **FIXED** interpolation
  (per-frame generated poses). `Scene.Inbetween interpolation switcher` only switches the interpolation
  selector mode; it generates nothing by itself. `cascadeur_inbetween(first, last)` selects, runs and
  waits for the FIXED sections. No Motion Generation (trajectory-driven) settings exist in this build's
  Scene Settings — only an Inbetweening group.
- AI in-betweens can add small head nods (≈7° dips between keys on the kick's recovery). In a FIXED
  interval every frame holds its own pose, so per-frame edits without keys are possible: we re-set the
  head's chest-relative orientation on each frame (`set_data_value` per frame) to remove the nod.
- A 1-frame interval between adjacent keys reports STEP interpolation and cannot be changed; harmless.
- `cascadeur_call_action` runs any of ~220 catalogued action IDs (interpolation and IK/FK/GR/fulcrum key
  types on current frame or interval, Tween Machine attract filters, copier, mirror, ghosts, ballistic
  trajectory, cycles, trajectory tool, visibility). File dialogs, exit, help and settings resets are
  excluded because modal file dialogs can block the app. `cascadeur_list_actions(catalog=true)` lists them.

## 7c. UI automation rules (learned the hard way)

- `QQuickWindow.grabWindow()` screenshots the whole UI (`cascadeur_ui_screenshot`): menus, panels,
  timeline colours, physics status line ("AutoPhysics status: Iterations: 176, Termination: CONVERGENCE").
- Synthetic click = `MouseMove` + `MouseButtonPress` + `MouseButtonRelease` sent to the item's window at
  the item centre (`operations.click_item`). Without the move event the click is ignored.
- Never call `QGuiApplication.processEvents()` from bridge code: nested event processing inside the bridge
  timer was followed by a hung Cascadeur (main window vanished, process had to be killed).
- Only one PySide wrapper per window survives; popups get deleted — skip `RuntimeError` when iterating
  `topLevelWindows()`. Import `PySide6.QtQuick` before touching windows, otherwise they are typed as plain
  `QWindow` without `contentItem()`.
- Right-panel tabs (Outliner / Scene settings / Physics settings / Tween machine / Event log) only
  instantiate their content when active — click the `TabButton` first.

## 8. Viewport capture

- **Renders are queued until the window repaints. A minimized Cascadeur window never repaints**, so
  `capture_viewport` returns "has not produced the output yet" and the PNGs appear later, all at once,
  when someone restores the window. `capture_viewport` now un-minimizes the window without focusing it
  (`ShowWindow(SW_SHOWNOACTIVATE)`) and reports `restored_minimized_window`.
- Use `View` mode for clean renders, `Controller` / `AutoPosing` to see controllers.
- The user may move the camera in the UI at the same time — set the camera right before each capture.

## 9. Qt / PySide6

- Cascadeur ships Qt 6.5.1 (Core/Gui/Qml/Quick; UI is QML). Its Python has **no** PySide6/shiboken.
- **Verified: PySide6 6.5.1.1 runs inside Cascadeur bound to Cascadeur's own Qt** (`Qt6Core.dll` resolved
  from the Cascadeur folder, `QCoreApplication.applicationName() == "Cascadeur"`). No crash.
- Preparation (Windows, once; versions must match `QtCore.qVersion()` of your Cascadeur build):
  ```
  uvx --python 3.11 pip download "PySide6-Essentials==6.5.1.1" "shiboken6==6.5.1.1" --no-deps --only-binary=:all: --platform win_amd64 -d wheels
  # unzip both wheels into <dir>\site
  # delete site\PySide6\Qt6*.dll, msvcp140*.dll, concrt140.dll, vcruntime140*.dll, opengl32sw.dll
  # delete the same runtime DLLs from site\shiboken6
  # copy python3.dll from any CPython 3.11 install into <dir>\site  (abi3 wheels need it; Cascadeur lacks it)
  ```
  Then pass `pyside6_site=r"<dir>\site"` to `app_bridge.start(...)` (or `--pyside6-site` to `--setup`).
- What it gives: the whole QML UI. Toolbar buttons are `ToolbarButton_QMLTYPE_*` items with properties
  `actionId`, `toolTip`, `active` (the toggle state!), `visible`, `enabled`. The main window is the
  top-level window with `objectName() == "MainWindow"`; walk `contentItem().childItems()` (~23k items).
  `active` on `AutoPosingTool.AutoPosing` / `AutoPhysicsTool.Switch Auto Physics` reliably reflects the
  modes (verified by toggling). UI notification texts ("Auto posing.Auto unlock: done") are readable too.
  Exposed as `cascadeur_ui_state`.
- Not tried yet: synthesizing mouse input on the viewport, pressing QML buttons directly.
- Settings panels are exposed as `view::ViewSettingsList` / `QSortFilterProxyModel` models (roles
  `settingsName`, `settingsGroup`, ...) — a way to read tool settings (e.g. physics) later.
  Some item models are custom C++ types without a PySide converter (`view::TreeToListModel*`); wrap
  `item.property('model')` in try/except.

### Upstream (gprethesh/cascadeur-mcp) vs this fork

Upstream used PySide6 only for the bridge `QTimer`, and captured app messages with
`events.event_message_manager`. The Windows 2025.2 build has neither, so commit `fd7235d` switched to a
Win32 `SetTimer` and made several API calls optional. Status now:

| Upstream feature | Windows 2025.2 | Restored |
| --- | --- | --- |
| Qt main-thread timer | no PySide6 | yes, when `pyside6_site` is set (`_QtTimer` is preferred; Win32 timer is the fallback) |
| App error/info message capture (`events.event_message_manager`) | module absent in Cascadeur itself | no; `scene.get_event_log_or_null()` is an opaque `IMessageHandler` |
| `View.get_path_name` (scene path) | method absent | yes for the active tab, parsed from the main window title |
| `is_export_available`, `is_pro_features_available` | methods absent | no (reported as null) |
| `DataViewer.get_data_name` | method absent | replaced by `get_data(id).name` |

## 10a. Coverage of the Cascadeur feature set (docs: https://cascadeur.com/help)

| Pipeline stage / feature | MCP route | Status |
| --- | --- | --- |
| Key poses (points/boxes) | `set_pose`, `animate_transforms` | verified |
| AutoPosing (network re-solve of knees/elbows/spine) | `autopose`, `set_mode("autoposing")` | verified |
| AutoPosing for fingers | `set_mode("autoposing_fingers")` | needs a 5-finger rig; Cascy's simplified hands are unsupported (docs) |
| Interpolation types, IK/FK/GR keys, double keys | `set_interpolation`, `call_action(Timeline.*)` | verified via API; key-type actions dispatch only |
| AI Inbetweening | `inbetween` | verified (local, seconds) |
| Motion Generation (trajectory-driven) | — | not present in this 2025.2 build |
| Tween Machine filters, Easing | `call_action(TweenMachine.*)`; easing is timeline UI only | dispatch only / not exposed |
| Contacts: fulcrum keys + point fulcrum state | `set_contacts` | verified |
| AutoPhysics preview, freeze, snap, priority frames | `set_mode`, `physics_snap`, `physics_priority_frames` | verified |
| Physics corrector, smooth trajectory/rotation, compensation/separation/secondary motion | `physics_settings(set=...)` then `physics_snap` | verified (UI-driven) |
| Ballistic trajectory / ghosts | `call_action(BallisticTrajectoryTool.*)` | dispatch only (tool hidden on the toolbar by default) |
| Fulcrum motion cleaning (foot sliding) | `call_action("View.FixFoot")` | dispatch only |
| Mirror, copy/paste, cycles | `mirror`, `call_action(Copier.*/Timeline.*cycle*)` | mirror verified; rest dispatch only |
| Additive layers, graph editor, node editor, retargeting, mocap | windows/actions only | not automated |
| Review: silhouette, ghosts, trajectories, full-UI screenshots | `call_action`, `ui_screenshot`, `capture_viewport` | verified |

"Dispatch only" = the action runs, but its result must be checked with poses/renders.

## 10b. Recommended pipeline for a high-quality shot

1. `open_scene` a clean rig → `save_scene` a new name. Plan 10–20 key poses and contact intervals.
2. Block key poses with `animate_transforms` (points, global positions; fingers only if calibrated).
3. `autopose(frames=...)` on every key pose → natural knees/elbows/spine. Render key poses.
4. `set_contacts` for feet (toe/heel points) over ground intervals; `physics_priority_frames` for 1–3
   poses that must not change (e.g. the hit).
5. `inbetween(first, last)` on intervals that need organic in-betweens (optional; makes them FIXED).
6. `physics_settings` → choose corrector/smoothing/compensation/secondary; `set_mode("physics", true)`;
   `ui_screenshot` to inspect the timeline strip and status; `physics_snap(answer="Yes")`.
7. `sample_motion` before/after, check planted feet, render several frames; `save_scene`.

## 10. Log of experiments

- Hand wave: dense procedural keys + smooth foot-drift correction; Secondary Motion made the arm floppy;
  a stale early key caused a knee pop (fixed by recreating the key).
- Jump spinning kick v1/v2: hand-made IK produced valgus knees and flipped feet; guessed finger fist broke
  hands → v2 keeps fingers un-keyed, 16 key poses, fulcrum via layer fixation.
- AutoPosing research: tool ids via user box-select → then fully programmatic (Select all + processor
  expansion); lock semantics from docs; full recipe verified; `cascadeur_autopose` added.
- Minimized window explained the "stuck" viewport captures.
- PySide6 6.5.1.1 loaded into Cascadeur's Qt; toolbar `active` states readable; `cascadeur_ui_state` added.
- Docs crawl (~35 animation pages + full action ID list) → coverage table §10a. Added the action catalog,
  idempotent modes, contacts, priority frames, physics settings writes via UI, physics snap with modal
  dialog handling, AI inbetweening and full-UI screenshots; all verified live on the kick scene.
- A Cascadeur hang (main window vanished) followed experiments that called `processEvents()` from the
  bridge; the rule in §7c avoids it.
