import json
import tomllib

import pytest
from pydantic import ValidationError

from cascadeur_mcp.operations import file_path, frame_number, vector
from cascadeur_mcp.server import Transform
from cascadeur_mcp.setup import generate


def test_paths_cannot_escape_workspace_or_overwrite_implicitly(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = {"workspace": workspace}
    outside = tmp_path / "private.casc"
    outside.write_text("existing")
    inside = workspace / "scene.casc"
    inside.write_text("existing")
    for value in ("relative.casc", str(workspace / ".." / "private.casc")):
        with pytest.raises(ValueError):
            file_path(value, state)
    try:
        (workspace / "symlink.casc").symlink_to(outside)
    except OSError:
        symlinks = False  # Windows without admin rights or Developer Mode
    else:
        symlinks = True
    if symlinks:
        with pytest.raises(ValueError, match="outside"):
            file_path(str(workspace / "symlink.casc"), state, exists=True)
    with pytest.raises(ValueError, match="exists"):
        file_path(str(inside), state)
    assert file_path(str(inside), state, overwrite=True) == inside
    assert file_path(str(inside), state, exists=True, suffix={".casc"}) == inside
    if not symlinks:
        pytest.skip("symlinks unavailable: the symlink escape check was not run")


@pytest.mark.parametrize("value", [-1, True, 1.5, 100001])
def test_invalid_frames(value):
    with pytest.raises(ValueError):
        frame_number(value)


def test_finite_vectors_and_explicit_transform_values():
    with pytest.raises(ValueError):
        vector([0, 1, float("nan")])
    with pytest.raises(ValidationError):
        Transform(object="hand")
    with pytest.raises(ValidationError):
        Transform(
            object="hand",
            rotation_delta_degrees=[1, 2, 3],
            rotation_quaternion_wxyz=[1, 0, 0, 0],
        )
    with pytest.raises(ValidationError):
        Transform(object="hand", position=[float("inf"), 0, 0])


def test_setup_is_standalone_and_client_configs_agree(tmp_path):
    out = tmp_path / "setup with spaces"
    workspace = tmp_path / "workspace"
    directory = tmp_path / "session"
    generate(out, directory, workspace)
    codex = tomllib.loads((out / "codex.toml").read_text())["mcp_servers"]["cascadeur"]
    claude = json.loads((out / "claude-desktop.json").read_text())["mcpServers"][
        "cascadeur"
    ]
    cursor = json.loads((out / "cursor.json").read_text())["mcpServers"]["cascadeur"]
    assert codex["args"] == claude["args"] == cursor["args"]
    assert "--allow-scripts" not in codex["args"]
    assert (out / "app" / "cascadeur_mcp" / "operations.py").is_file()
    compile((out / "start_bridge.py").read_text(), "startup", "exec")
