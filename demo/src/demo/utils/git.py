from __future__ import annotations

import subprocess
from pathlib import Path


def try_git_head(project_root: Path) -> tuple[str, str | None]:
    """Return (commit_sha, branch_name_or_None)."""
    try:
        sha = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if sha.returncode != 0:
            return "", None
        commit = sha.stdout.strip()
        br = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        branch = br.stdout.strip() if br.returncode == 0 else None
        return commit, branch
    except (OSError, subprocess.TimeoutExpired):
        return "", None
