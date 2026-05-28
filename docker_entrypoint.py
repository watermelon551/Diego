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
        # Grant diego user write access to workspace volume (for pptd tool endpoints)
        workspace_dir = Path("/app/workspace")
        if workspace_dir.is_dir():
            _chown_tree(workspace_dir, user.pw_uid, user.pw_gid)
            # Set world-writable + setgid so new files by any user are writable by diego
            os.chmod(workspace_dir, 0o777)
            for child in workspace_dir.iterdir():
                if child.is_dir():
                    os.chmod(child, 0o777)
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
