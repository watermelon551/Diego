from __future__ import annotations

import os
import pwd
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("missing command")

    runtime_dir = Path(os.environ.get("DIEGO_RUNTIME_DIR", "/app/.runtime"))
    runtime_dir.mkdir(parents=True, exist_ok=True)

    if os.geteuid() == 0:
        user = pwd.getpwnam("diego")
        _chown_tree(runtime_dir, user.pw_uid, user.pw_gid)
        os.environ["HOME"] = user.pw_dir
        os.setgid(user.pw_gid)
        os.setuid(user.pw_uid)

    os.execvp(sys.argv[1], sys.argv[1:])


def _chown_tree(path: Path, uid: int, gid: int) -> None:
    os.chown(path, uid, gid)
    for root, dirs, files in os.walk(path):
        for name in [*dirs, *files]:
            os.chown(Path(root) / name, uid, gid)


if __name__ == "__main__":
    main()
