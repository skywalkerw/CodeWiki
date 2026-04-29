"""Build module_tree.json: Maven/Gradle modules + package-level feature leaves + metrics."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from demo.core.package_index import (
    collect_package_file_map,
    count_lines_java,
    file_under_module_root,
    loc_for_files,
    package_directory_hint,
    package_short_name,
)

_SLUG_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def _slug(s: str, max_len: int = 80) -> str:
    t = _SLUG_SAFE.sub("-", s.strip()).strip("-")
    return (t[:max_len] or "pkg") if t else "pkg"


def _type_leaf_children(
    project_root: Path,
    mod_id: str,
    pkg: str,
    pkg_seq: int,
    sym_list: list[Any],
    line_cache: dict[str, int],
) -> list[dict[str, Any]]:
    """One node per top-level symbol from light scan (class/interface/enum…)."""
    if not isinstance(sym_list, list) or not sym_list:
        return []

    def sort_key(it: Any) -> tuple[str, int, str]:
        if not isinstance(it, dict):
            return ("", 0, "")
        line = it.get("line")
        ln = int(line) if isinstance(line, int) else 0
        return (str(it.get("file") or ""), ln, str(it.get("name") or ""))

    out: list[dict[str, Any]] = []
    for i, it in enumerate(sorted(sym_list, key=sort_key)):
        if not isinstance(it, dict):
            continue
        name = it.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        file_raw = it.get("file")
        if not isinstance(file_raw, str):
            continue
        fr = file_raw.replace("\\", "/")
        if fr not in line_cache:
            line_cache[fr] = count_lines_java(project_root, fr)
        loc = line_cache[fr]
        kind_label = it.get("kindLabel")
        if not isinstance(kind_label, str):
            kind_label = "type"
        sym_kind = it.get("kind")
        line = it.get("line")
        node: dict[str, Any] = {
            "id": f"type-{mod_id}-{_slug(pkg)}-{pkg_seq}-{_slug(name)}-{i}",
            "name": name.strip(),
            "kind": "type_leaf",
            "kindLabel": kind_label,
            "qualified_name": f"{pkg}.{name.strip()}",
            "file": fr,
            "metrics": {
                "loc_java": loc,
                "cyclomatic_sum": 0,
            },
        }
        if isinstance(sym_kind, int):
            node["symbolKind"] = sym_kind
        if isinstance(line, int):
            node["line"] = line
        out.append(node)
    return out


def modules_scan_to_module_tree(modules_json: dict[str, Any]) -> dict[str, Any]:
    """
    Back-compat shallow tree (no symbols). Prefer :func:`build_module_tree`.
    """
    return build_module_tree(modules_json, None, project_root=Path(modules_json.get("projectRoot", ".")))


def build_module_tree(
    modules_json: dict[str, Any],
    symbols_json: dict[str, Any] | None,
    *,
    project_root: Path,
) -> dict[str, Any]:
    """
    Hierarchical tree aligned with ``docs/samples/1.3-module_tree.json``:

    - **repository** root
    - **maven_module** (or gradle) per reactor module, with aggregated ``loc_java`` / ``type_count``
    - **feature_leaf** per Java package under that module, with metrics and source path
    - **type_leaf** per top-level type from ``symbols-by-package`` (``qualified_name``, ``file``, ``line``)

    If ``symbols_json`` is None, falls back to module-only nodes (empty children).
    """
    root_path = Path(modules_json.get("projectRoot", str(project_root))).resolve()
    project_root = root_path
    modules = list(modules_json.get("modules") or [])
    pkg_files = collect_package_file_map(symbols_json) if symbols_json else {}

    # Non-Maven tree with Java sources: treat whole repo as one synthetic module
    if not modules and pkg_files:
        modules = [
            {
                "name": root_path.name,
                "path": ".",
                "source": "synthetic-single-root",
                "hasPom": False,
            }
        ]
    line_cache: dict[str, int] = {}

    children: list[dict[str, Any]] = []
    for i, m in enumerate(modules):
        if isinstance(m, str):
            mod_path = m
            mod_name = Path(m).name or m
            artifact = None
        elif isinstance(m, dict):
            mod_path = str(m.get("path") or m.get("name") or f"mod-{i}")
            mod_name = Path(mod_path).name or mod_path
            artifact = m.get("artifactId")
        else:
            continue

        mod_id = f"mod-{_slug(mod_name)}-{i}"

        # Packages that have at least one file under this module root
        mod_packages: list[tuple[str, set[str]]] = []
        for pkg, files in sorted(pkg_files.items()):
            in_mod = {f for f in files if file_under_module_root(project_root, mod_path, f)}
            if in_mod:
                mod_packages.append((pkg, in_mod))

        leaf_nodes: list[dict[str, Any]] = []
        mod_loc = 0
        mod_types = 0
        for j, (pkg, files) in enumerate(mod_packages):
            sym_list = []
            if symbols_json and isinstance(symbols_json.get("packages"), dict):
                sym_list = symbols_json["packages"].get(pkg) or []
            type_count = len(sym_list) if isinstance(sym_list, list) else len(files)
            loc = loc_for_files(project_root, files, line_cache)
            mod_loc += loc
            mod_types += type_count

            dir_hint = package_directory_hint(project_root, files)
            type_children = _type_leaf_children(
                project_root, mod_id, pkg, j, sym_list if isinstance(sym_list, list) else [], line_cache
            )
            leaf: dict[str, Any] = {
                "id": f"leaf-{mod_id}-{_slug(pkg)}-{j}",
                "name": package_short_name(pkg),
                "kind": "feature_leaf",
                "full_package": pkg,
                "path": dir_hint,
                "metrics": {
                    "loc_java": loc,
                    "type_count": type_count,
                    "cyclomatic_sum": 0,
                },
                "delegation_depth": 0,
            }
            if type_children:
                leaf["children"] = type_children
            leaf_nodes.append(leaf)

        children.append(
            {
                "id": mod_id,
                "name": mod_name,
                "kind": "maven_module",
                "path": mod_path,
                "artifactId": artifact,
                "metrics": {
                    "loc_java": mod_loc,
                    "type_count": mod_types,
                },
                "children": leaf_nodes,
            }
        )

    repo_name = root_path.name or "repository"
    return {
        "$schema": "https://example.local/schemas/java-historical-analysis/module-tree-1.json",
        "schema_version": "1.0",
        "manifest_ref": "1.1-analysis_manifest.json",
        "root": {
            "id": "root",
            "name": repo_name,
            "kind": "repository",
            "metrics": {
                "loc_java": sum(c["metrics"].get("loc_java", 0) for c in children),
                "type_count": sum(c["metrics"].get("type_count", 0) for c in children),
                "package_count": sum(len(c.get("children") or []) for c in children),
            },
            "children": children,
        },
        "_source": "java-code-wiki.build_module_tree",
    }
