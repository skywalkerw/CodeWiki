"""Derive per-package file sets and LOC from symbols payload + filesystem."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def collect_package_file_map(symbols_json: dict[str, Any]) -> dict[str, set[str]]:
    """
    package_name -> set of project-relative posix paths to .java files.
    """
    packages = symbols_json.get("packages")
    if not isinstance(packages, dict):
        return {}
    out: dict[str, set[str]] = {}
    for pkg, items in packages.items():
        if not isinstance(items, list):
            continue
        files: set[str] = set()
        for it in items:
            if not isinstance(it, dict):
                continue
            fp = it.get("file")
            if isinstance(fp, str) and fp.endswith(".java"):
                files.add(fp.replace("\\", "/"))
        if files:
            out[pkg] = files
    return out


def file_under_module_root(project_root: Path, module_rel: str, file_rel: str) -> bool:
    """Whether ``file_rel`` (relative to project root) lies under the Maven module directory."""
    try:
        f = (project_root / file_rel).resolve()
        base = (project_root / module_rel).resolve() if module_rel not in (".", "") else project_root.resolve()
        f.relative_to(base)
        return True
    except ValueError:
        return False
    except OSError:
        return False


def count_lines_java(project_root: Path, file_rel: str) -> int:
    path = project_root / file_rel
    if not path.is_file():
        return 0
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return 1 + text.count("\n") if text else 0


def loc_for_files(project_root: Path, files: set[str], cache: dict[str, int]) -> int:
    total = 0
    for fr in files:
        if fr not in cache:
            cache[fr] = count_lines_java(project_root, fr)
        total += cache[fr]
    return total


def package_directory_hint(project_root: Path, files: set[str]) -> str:
    """Best relative directory for a package (parent of first file, as posix rel path)."""
    if not files:
        return ""
    first = sorted(files)[0]
    p = (project_root / first).parent
    try:
        return str(p.relative_to(project_root)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def package_short_name(full_package: str) -> str:
    parts = full_package.strip().split(".")
    return parts[-1] if parts else full_package
