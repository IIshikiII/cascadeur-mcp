"""Generate a self-contained app bridge and portable client configuration."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def generate(output, bridge_dir, workspace, allow_scripts=False, pyside6_site=None):
    output = Path(output).expanduser().resolve()
    bridge_dir = Path(bridge_dir).expanduser().resolve()
    workspace = Path(workspace).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    package = output / "app" / "cascadeur_mcp"
    package.mkdir(parents=True, exist_ok=True)
    for name in ("__init__.py", "app_bridge.py", "operations.py", "actions.py"):
        shutil.copyfile(Path(__file__).with_name(name), package / name)
    startup = (
        "# Execute this file in Cascadeur Window > Python Console.\n"
        "import sys\n"
        "_previous_bridge = sys.modules.get('cascadeur_mcp.app_bridge')\n"
        "if _previous_bridge is not None:\n    _previous_bridge.stop()\n"
        "for _module_name in list(sys.modules):\n"
        "    if _module_name == 'cascadeur_mcp' or _module_name.startswith('cascadeur_mcp.'):\n"
        "        del sys.modules[_module_name]\n"
        f"sys.path.insert(0, {str(output / 'app')!r})\n"
        "from cascadeur_mcp import app_bridge\n"
        f"app_bridge.start({str(bridge_dir)!r}, {str(workspace)!r}, allow_scripts={allow_scripts!r}"
        + (
            f", pyside6_site={str(Path(pyside6_site).expanduser().resolve())!r}"
            if pyside6_site
            else ""
        )
        + ")\n"
    )
    (output / "start_bridge.py").write_text(startup)
    executable = str(Path(sys.executable).absolute())
    arguments = [
        "-m",
        "cascadeur_mcp",
        "--bridge-dir",
        str(bridge_dir),
        "--workspace",
        str(workspace),
    ]
    if allow_scripts:
        arguments.append("--allow-scripts")
    settings = {"mcpServers": {"cascadeur": {"command": executable, "args": arguments}}}
    (output / "claude-desktop.json").write_text(json.dumps(settings, indent=2) + "\n")
    settings["mcpServers"]["cascadeur"]["type"] = "stdio"
    (output / "cursor.json").write_text(json.dumps(settings, indent=2) + "\n")
    (output / "codex.toml").write_text(
        "[mcp_servers.cascadeur]\ncommand = "
        + json.dumps(executable)
        + "\nargs = "
        + json.dumps(arguments)
        + "\nstartup_timeout_sec = 30\ntool_timeout_sec = 120\n"
    )
    return {
        "startup_script": str(output / "start_bridge.py"),
        "codex": str(output / "codex.toml"),
        "claude_desktop": str(output / "claude-desktop.json"),
        "cursor": str(output / "cursor.json"),
        "next_step": "In Cascadeur Python Console execute: exec(open("
        + repr(str(output / "start_bridge.py"))
        + ").read())",
    }
