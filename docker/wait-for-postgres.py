#!/usr/bin/env python3
"""Wait until FOX_DATABASE_URL host resolves and accepts TCP connections."""

import os
import socket
import sys
import time
from urllib.parse import urlparse


def main() -> None:
    raw = os.environ.get("FOX_DATABASE_URL", "")
    if not raw:
        print("FOX_DATABASE_URL is not set", file=sys.stderr)
        sys.exit(1)
    u = raw.replace("postgresql+asyncpg://", "postgresql://", 1)
    p = urlparse(u)
    host = p.hostname or "postgres"
    port = p.port or 5432
    deadline = time.monotonic() + int(os.environ.get("FOX_DB_WAIT_SECONDS", "120"))
    last_err: OSError | None = None
    while time.monotonic() < deadline:
        try:
            socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            with socket.create_connection((host, port), timeout=3):
                return
        except OSError as e:
            last_err = e
            time.sleep(1)
    print(
        f"Timed out connecting to {host}:{port} ({last_err}). "
        "If postgres is running but the hostname does not resolve, recreate: "
        "docker compose up -d --force-recreate postgres api worker",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
