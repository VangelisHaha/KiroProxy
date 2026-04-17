#!/usr/bin/env python3
"""Legacy compatibility launcher.

This file used to contain an older standalone proxy implementation.
It now delegates to the maintained package entrypoints.
"""

import sys


def _run_server(port: int = 8080):
    from kiro_proxy.main import run
    run(port)


def _run_cli():
    from kiro_proxy.cli import main
    main()


if __name__ == "__main__":
    # Keep backward-compatible CLI subcommands.
    if len(sys.argv) > 1 and sys.argv[1] in {"accounts", "login", "status", "serve"}:
        _run_cli()
    # Compatibility: python kiro_proxy.py --no-ui [port]
    elif len(sys.argv) > 1 and sys.argv[1] == "--no-ui":
        port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 8080
        _run_server(port)
    # Compatibility: python kiro_proxy.py [port]
    elif len(sys.argv) > 1 and sys.argv[1].isdigit():
        _run_server(int(sys.argv[1]))
    else:
        _run_server(8080)
