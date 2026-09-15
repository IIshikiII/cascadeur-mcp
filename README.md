# Cascadeur MCP

An independent local MCP server for controlling Cascadeur from **Codex, Claude Desktop, Claude Code, Cursor**, and other stdio MCP clients.

It provides **36 named tools** for scene and rig inspection, body/finger posing, keyframes, interpolation, timeline selection, camera controls, PNG previews and FBX import/export. A curated action catalog exposes physics, AutoPosing, retargeting, cycles and review commands with explicit verification limits. An optional 37th tool enables advanced Python scripting.

**Start with the [AI operating guide](docs/AI_GUIDE.md).** It explains which controls to use, how to verify body and finger animation, and which APIs to avoid. The guide is also served to agents as `cascadeur://guide`.

## What was tested

The server was tested against a real Apple silicon Mac installation of Cascadeur reporting `inHouse` / Python API `dev`, with embedded Python 3.11. The supplied [live test](examples/live_smoke.py) used the locally installed Cascy sample to animate the torso, arm and all 15 right-hand finger controls. It checked interpolated poses, rendered body/hand views, saved and reopened the `.casc`, and exported animation FBX. See the [test report and capability limits](docs/TESTING.md).

This is a functional animation integration, not a guarantee of finished artistic quality. Cascadeur's API coverage is uneven. Physics/menu commands and advanced systems are labeled separately from operations verified in the live test. Windows and Linux are unverified; Claude and Cursor configuration is provided but their UIs were not tested directly.

## Install

Use Python 3.11 or newer in your normal operating-system environment:

```sh
git clone https://github.com/gprethesh/cascadeur-mcp.git
cd cascadeur-mcp
python3 -m venv .venv
.venv/bin/python -m pip install .
```

On Windows, use `.venv\Scripts\python.exe` in place of `.venv/bin/python`.

The server needs no API key. It uses your AI client's model and your installed/licensed Cascadeur application. It does not use Cascadeur's built-in MCP server, patch the app, or install Python packages into the app's embedded Python.

## 1. Generate your bridge and client settings

Choose absolute paths for the connection folder, animation workspace, and generated setup folder. Keep these folders local to your machine.

```sh
.venv/bin/python -m cascadeur_mcp \
  --bridge-dir "/absolute/path/cascadeur-session" \
  --workspace "/absolute/path/animation-projects" \
  --setup "/absolute/path/cascadeur-setup"
```

This writes:

- `start_bridge.py`: a script to run in Cascadeur.
- `app/cascadeur_mcp/`: a standalone copy of the app bridge.
- `codex.toml`, `claude-desktop.json`, and `cursor.json`: ready-to-merge client settings using the actual Python executable and paths.

Keep the generated `app` folder beside the startup script. Re-run setup after upgrading this server, then restart Cascadeur to load the new bridge code.

## 2. Start the bridge inside Cascadeur

Open **Window → Python Console** and execute this line, using the generated script's actual path:

```python
exec(open("/absolute/path/cascadeur-setup/start_bridge.py").read())
```

Leave Cascadeur open. Start the bridge again after each app restart. The console can be closed after execution. A compatible Cascadeur build must supply `csc`, `PySide6`, the event-message manager and `ModelEditor.fit_animation_size_by_layers`.

Do not start Cascadeur's built-in MCP server for this integration.

Check the connection from a terminal:

```sh
.venv/bin/python -m cascadeur_mcp \
  --bridge-dir "/absolute/path/cascadeur-session" \
  --workspace "/absolute/path/animation-projects" \
  --doctor
```

## 3. Connect your AI client

Merge the generated settings into the client's existing configuration, preserving other servers. Use the same bridge directory and workspace in every client. Use literal absolute paths in JSON and TOML; do not leave `~`, environment placeholders, or example paths.

### Codex

Merge generated `codex.toml` into `~/.codex/config.toml`, then restart the MCP connection in Codex settings. Example:

```toml
[mcp_servers.cascadeur]
command = "/absolute/path/cascadeur-mcp/.venv/bin/python"
args = ["-m", "cascadeur_mcp", "--bridge-dir", "/absolute/path/cascadeur-session", "--workspace", "/absolute/path/animation-projects"]
startup_timeout_sec = 30
tool_timeout_sec = 120
```

[Official Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

### Claude Desktop

Use **Settings → Developer → Edit Config**, and merge generated `claude-desktop.json`. On macOS the configuration file is `~/Library/Application Support/Claude/claude_desktop_config.json`. Restart Claude Desktop.

```json
{
  "mcpServers": {
    "cascadeur": {
      "command": "/absolute/path/cascadeur-mcp/.venv/bin/python",
      "args": ["-m", "cascadeur_mcp", "--bridge-dir", "/absolute/path/cascadeur-session", "--workspace", "/absolute/path/animation-projects"]
    }
  }
}
```

[Official local MCP setup guide](https://modelcontextprotocol.io/docs/develop/connect-local-servers).

### Claude Code

```sh
claude mcp add --transport stdio --scope user cascadeur -- \
  "/absolute/path/cascadeur-mcp/.venv/bin/python" -m cascadeur_mcp \
  --bridge-dir "/absolute/path/cascadeur-session" \
  --workspace "/absolute/path/animation-projects"
```

Use `/mcp` to inspect the connection. Long operations may need `MCP_TOOL_TIMEOUT=120000` (milliseconds). [Official Claude Code documentation](https://code.claude.com/docs/en/mcp).

### Cursor

Merge generated `cursor.json` into `~/.cursor/mcp.json` globally, or `.cursor/mcp.json` for a project. Reload Cursor and enable the `cascadeur` server. The generated entry includes `"type": "stdio"`.

[Official Cursor documentation](https://cursor.com/docs/context/mcp).

### Other clients

Launch the same Python executable and arguments as a **local stdio MCP server**. Image review requires support for MCP image content. A remote-only chat cannot launch an app on your computer without a local runtime.

## 4. First prompt

> Read cascadeur://guide. Check Cascadeur's capabilities and inspect the active scene, rig, body controls, finger controls and tracks. Report the available operations and license restrictions before editing.

For an animation task, provide the character, reference, action, intended duration/FPS and output requirements. Have the agent checkpoint, block poses, inspect inbetweens, refine hands, and verify saves/exports.

## Coverage

| Area | Access |
| --- | --- |
| Projects and scene tabs | Create, open, activate, inspect, save |
| Rigs and objects | Search, types, behaviours, data values, transforms, finger candidates |
| Animation | Body/finger pose batches, keys, interpolation, track/frame selection, motion sampling |
| Review | Camera inspection/placement, framing, display modes, PNG images returned through MCP |
| Exchange | FBX scene/model/animation import and scene/animation/selection export |
| Physics and advanced menu tools | Curated action catalog; state-dependent, not all verified |
| Wider API | Live signature discovery; optional Python execution |

See [tool schemas](docs/tools.json) for machine-readable arguments, and [the guide](docs/AI_GUIDE.md) for workflows and restrictions.

## Known limits

- **Native Python video export crashed the tested Cascadeur build.** It is not exposed as a normal tool. Capture PNG frames instead. See [TESTING.md](docs/TESTING.md).
- Additive layers, mocap, AI motion generation, retargeting quality and rig generation are not claimed as verified features. Discover APIs and check your license before use.
- Menu actions report dispatch, not successful completion. Many commands are toggles, need a selection, or can open dialogs.
- The server checks normal input/output file paths against the workspace. This is not an operating-system sandbox. Projects may reference other assets.
- A timeout or application crash can leave an uncertain result. Inspect before retrying. Save checkpoints before substantial changes.

## Advanced scripting

To expose `cascadeur_run_script`, add `--allow-scripts` both to the setup-generation command and to the server's client arguments. The generated settings include it when setup uses that flag.

Scripts execute with the user's full privileges inside Cascadeur, including file, process and network access. They bypass the workspace path checks used by normal tools. They are disabled by default. Read the scripting section of the AI guide before using them.

## How the connection works

The AI client talks standard MCP over stdio to a Python process. That process writes requests into a local mailbox. A Qt timer in Cascadeur executes one request at a time on the app's main thread and writes a response. There is no HTTP listener, open network port, model dependency or remote relay.

The mailbox uses atomic writes, session identities, deadlines, cancellation cleanup, payload limits and a cross-process client lock. On Unix, the connection directory is owner-only. Windows uses the folder's inherited ACL; keep it in a private user directory. All clients share the active scene and selection, so avoid simultaneous artistic edits.

## Development and testing

```sh
.venv/bin/python -m pip install '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```

To reproduce the live test, start the bridge against a dedicated test workspace, then run:

```sh
.venv/bin/python examples/live_smoke.py \
  --sample "/Applications/Cascadeur.app/Contents/Resources/samples/Cascy.casc" \
  --workspace "/absolute/path/test-workspace" \
  --bridge-dir "/absolute/path/cascadeur-session"
```

The test creates/overwrites its named test scene and previews in that workspace. It uses the sample installed with Cascadeur; no vendor rig or app binaries are distributed by this repository.

## License

This integration is [MIT licensed](LICENSE). Cascadeur and bundled sample assets retain their own licenses. This project is independent of Nekki, OpenAI, Anthropic and Cursor.
