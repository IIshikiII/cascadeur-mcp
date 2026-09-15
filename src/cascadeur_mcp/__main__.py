from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from platformdirs import user_data_path


def main():
    parser = argparse.ArgumentParser(
        description="Independent local Cascadeur MCP server (stdio)."
    )
    parser.add_argument(
        "--bridge-dir", type=Path, default=user_data_path("cascadeur-mcp") / "session"
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument(
        "--allow-scripts",
        action="store_true",
        help="Enable full-privilege Python execution; must also be enabled in app bridge.",
    )
    parser.add_argument(
        "--setup",
        type=Path,
        metavar="DIRECTORY",
        help="Generate a standalone app bridge and client settings here, then exit.",
    )
    parser.add_argument(
        "--doctor", action="store_true", help="Check the app connection and exit."
    )
    args = parser.parse_args()
    if args.setup:
        from .setup import generate

        print(
            json.dumps(
                generate(
                    args.setup, args.bridge_dir, args.workspace, args.allow_scripts
                ),
                indent=2,
            )
        )
        return
    from .bridge import Bridge, BridgeError

    try:
        bridge = Bridge(
            args.bridge_dir, args.workspace, args.timeout, args.allow_scripts
        )
        if args.doctor:
            print(json.dumps(bridge.status(), indent=2))
            return
        from .server import create_server

        create_server(bridge).run(transport="stdio")
    except (BridgeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
