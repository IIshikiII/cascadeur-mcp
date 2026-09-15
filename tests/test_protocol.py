import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.parametrize("scripts", [False, True])
async def test_real_stdio_handshake_tools_resource_and_validation(tmp_path, scripts):
    args = [
        "-m",
        "cascadeur_mcp",
        "--bridge-dir",
        str(tmp_path / "session"),
        "--workspace",
        str(tmp_path),
    ]
    if scripts:
        args.append("--allow-scripts")
    async with stdio_client(
        StdioServerParameters(command=sys.executable, args=args)
    ) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            listed = await client.list_tools()
            names = {tool.name for tool in listed.tools}
            assert ("cascadeur_run_script" in names) == scripts
            assert "cascadeur_render_video" not in names
            assert "cascadeur_animate_transforms" in names
            guide = await client.read_resource("cascadeur://guide")
            assert "finger" in guide.contents[0].text.lower()
            status = await client.call_tool("cascadeur_status", {})
            assert status.is_error
            bad = await client.call_tool(
                "cascadeur_animate_transforms",
                {"keyframes": [{"frame": -1, "transforms": []}]},
            )
            assert bad.is_error
            assert not list((tmp_path / "session").glob("request-*.json"))
