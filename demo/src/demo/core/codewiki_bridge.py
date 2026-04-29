"""Bridge to run vendored CodeWiki from the demo CLI."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    # demo/src/demo/core/codewiki_bridge.py -> repo root
    return Path(__file__).resolve().parents[4]


def _codewiki_checkout_root() -> Path:
    """Path to the CodeWiki package directory at the repository root (``./CodeWiki``)."""
    return _repo_root() / "CodeWiki"


def ensure_codewiki_available() -> Path:
    root = _codewiki_checkout_root()
    if not root.is_dir():
        raise FileNotFoundError(f"CodeWiki not found at: {root}")
    marker = root / "codewiki" / "__main__.py"
    if not marker.is_file():
        raise FileNotFoundError(f"Invalid CodeWiki checkout (missing {marker})")
    return root


def _codewiki_installed() -> bool:
    return importlib.util.find_spec("codewiki") is not None


def _ensure_codewiki_importable() -> None:
    """
    Fail fast with an actionable message if CodeWiki can't be imported.

    CodeWiki lives at the repo root in ``./CodeWiki``; it still requires its dependency tree
    to be installed (recommended: ``pip install -e CodeWiki``).
    """
    if _codewiki_installed():
        return

    root = str(ensure_codewiki_available())
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        import codewiki.cli.main  # noqa: PLC0415 - optional heavy dependency
    except ModuleNotFoundError as e:
        missing = getattr(e, "name", None) or str(e)
        raise RuntimeError(
            "CodeWiki is present but its Python dependencies are not installed.\n"
            f"Import error while loading codewiki: {missing}\n\n"
            "Fix (recommended):\n"
            "  ./scripts/bootstrap_codewiki.sh\n"
            "or:\n"
            "  python -m pip install --resume-retries 10 -e CodeWiki\n"
        ) from e


def run_codewiki_passthrough(args: list[str]) -> int:
    """
    Execute `python -m codewiki ...`.

    Prefer an installed ``codewiki`` package (e.g. ``pip install -e CodeWiki``).
    If not installed, bootstrap ``PYTHONPATH`` to the ``CodeWiki`` checkout root.
    """
    _ensure_codewiki_importable()

    env = os.environ.copy()
    if not _codewiki_installed():
        root = ensure_codewiki_available()
        py_path = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{root}{os.pathsep}{py_path}" if py_path else str(root)

    cmd = [sys.executable, "-m", "codewiki", *args]
    proc = subprocess.run(cmd, env=env, check=False)
    return int(proc.returncode)

