# What the MCP could not do (punch scene, 2026-09-30)

Each entry: what was needed, what I used instead, what the MCP should offer.

1. **Close a scene** - no tool. Used `run_script`: `view.save(scratch)` then
   `app.get_data_source_manager().close_scene(view)` (closing an unsaved tab opens a modal
   "save?" dialog that has crashed Cascadeur). Needed: `close_scene(save_as=None|path, discard=bool)`.
2. **Open a bundled character** (`<Cascadeur>/samples/UE5_Manny.casc`) - `open_scene` accepts only
   workspace paths. Copied the sample into the workspace with the shell. Needed: `list_samples` +
   `open_sample(name)` (read-only source, save-as into the workspace).
3. **Add a second character** - "File > Import > Scene to current" is not in the `call_action`
   catalog and opens a native file dialog. Used `run_script`: the action plus a QTimer that finds
   the Win32 dialog (#32770), types the path into its Edit and posts IDOK. Needed:
   `import_scene(path)` (merge a .casc into the current scene; report the new prefix).
4. **Place a character** (translate / turn it as a whole) - no tool. Two identical imported
   characters stand in the same spot, so nothing can tell their AutoPosing controllers apart.
   Used a client script over `get_pose` + `animate_transforms`: all 112 Points/Boxes of
   `character1:` shifted +90 cm Z (pure translation). Needed: `place_character(prefix, offset,
   yaw_degrees)`; the turn itself should go through hands/feet + autopose.
5. **AutoPosing controllers of a second character** - an imported copy gets new controller ids,
   Select all reaches only the first character, and the Python API has no way to enumerate the
   second one's controllers. Needed the user's click in AutoPosing mode + `autopose_seed`.
   (Also fixed: a cached seed from another scene raised instead of being skipped.)
6. **Bridge file race in the MCP server** - `cascadeur_autopose` (many bridge calls) failed once with
   `PermissionError [Errno 13]` on a response file (Windows file lock). `mcp_call.py` retries such
   errors, the server's `call` does not. Needed: the same retry in `bridge.call` / server `call`.
7. **get_pose output** - every Point carries four "unavailable" rotation/scale entries; a compact
   `positions` mode would keep responses small.
8. **Lock verification flake** - once a Locked click on `head` did not show up in the re-read and
   `cascadeur_autopose` stopped ("FAILED to set locks", no Update); a second call worked.
   Needed: retry the click/verify once inside `autopose_flow` before failing.
9. **Undo is not an undo of "my last edit"** - `call_action("Scene.Undo")` after an
   `animate_transforms` finger edit rolled back more than that edit (the AutoPosing solve
   before it). Went back to the saved checkpoint instead. Needed: `checkpoint()` / `restore()`
   (named in-memory snapshots) or edits that return an undo token.
10. **Finger calibration** - no tool tells a Box's local axes; curling a fist means probing axes
   with renders. Needed: `finger_pose(hand, curl=0..1, spread)` or at least `box_axes(name)` in
   world space.
11. **Body intersections** - there was no check. Added `cascadeur_check_collisions(frames)`: the
    rig's CapsuleCollision bodies (17 per UE character; axis = local Z of body * capsule rotation)
    plus fist capsules; reports depth between characters and within one character. It found the
    attacker's guard hand 8.5 cm inside his own head.
12. **A Locked toggle re-solves the pose** - every Locked click makes Cascadeur re-pose the free
    points, which undid a written chest lean. `autopose_flow` now records the pose before the lock
    pass, writes it back after it, re-syncs and only then runs Update (not yet enough for a torso
    anchor: see 13).
13. **Torso anchors are not held** - with hands, feet and head locked, a locked `chest` still
    moved ~13 cm in Update (the network compromises). A strong recoil (defender rocked back) could
    not be posed; hands-driven recoil left the hands 13 cm off. Open question: how Cascadeur users
    pose a hit reaction (probably AutoPhysics over an animation, not a single pose).
14. **Direction points of hands/feet** - releasing them (anchors = hand_l/r, toe_l/r only) gave
    natural wrists on the defender, as the user suggested; the punching hand keeps its fist
    orientation from the fingers pose.
