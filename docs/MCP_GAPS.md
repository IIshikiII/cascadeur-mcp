# MCP gaps found while posing a punch (2026-09-30) and their status

Each entry: what was needed -> what the MCP offers now.

1. **Close a scene** (closing an unsaved tab opens a modal "save?" dialog that has crashed
   Cascadeur) -> `cascadeur_close_scene(save_as | discard=true)` saves first, then closes. DONE
2. **Open a bundled character** (`<Cascadeur>/samples`, outside the workspace) ->
   `cascadeur_list_samples`, `cascadeur_open_sample(name, save_as)` (the sample stays untouched). DONE
3. **Add a second character** ("File > Import > Scene to current" + a native file dialog) ->
   `cascadeur_import_scene(sample name | workspace .casc)` fills the dialog through Win32, waits for
   the objects and returns the new prefix ("character1:"). Windows only. DONE
4. **Place / turn a character** -> `cascadeur_place_character(offset, character, frames)` (translates
   all Point/Box controllers) and `cascadeur_turn_character(yaw_degrees, character, frame, offset,
   solve=true)` (rotates hand/foot targets about the pelvis, then explicit-lock autopose). DONE
5. **AutoPosing controllers of a non-first character** -> still needs one user click in AutoPosing
   mode + `cascadeur_autopose_seed` (cached in the workspace). Select all reaches only the first
   character and the Python API cannot enumerate the tool model. OPEN
6. **Mailbox file locked by Windows** (`PermissionError` on the response file) -> `bridge.call`
   retries reading/removing locked files. DONE
7. **Noisy get_pose** -> `cascadeur_get_pose(compact=true)` (default) drops transforms an object does
   not have. DONE
8. **Lock verification flake** -> `autopose_flow` retries a click once before failing. DONE
9. **Undo rolls back more than the last edit** -> `cascadeur_checkpoint(name)` /
   `cascadeur_restore_checkpoint(name)` (<workspace>/.checkpoints, the working file name is kept,
   the replaced state goes to .trash). DONE
10. **Finger poses** -> `cascadeur_hand_pose(preset)` / `cascadeur_save_hand_preset(name)`
    ("open", "fist"; one preset fits both UE hands). A generic `box_axes` query is not needed for
    that and was not added. DONE
11. **Body intersections** -> `cascadeur_check_collisions(frames)` (rig CapsuleCollision bodies +
    fist capsules). DONE
12. **A Locked toggle re-solves the pose** -> `autopose_flow` records the pose before the lock pass
    and writes it back before Update. DONE
13. **Torso anchors are not held against hands/feet/head** -> not a tool problem; the user's recipe
    for a hit recoil (lock `neck_01`, push it back, move the defender toward the attacker) is in
    AI_GUIDE. DOCUMENTED
14. **Hand/foot direction points** -> anchor only `hand_l/r`, `toe_l/r` to release them (AI_GUIDE).
    DOCUMENTED
15. **Cascadeur's main window disappearing** (destroyed inside Python's cyclic GC) -> the bridge
    runs `diag.protect()` (DEBUG_SAVEALL + a sweep that keeps live Python-owned Qt objects). DONE
