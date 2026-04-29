"""Build a lightweight 1.2 graph from static scan artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from demo.core.package_index import (
    collect_package_file_map,
    file_under_module_root,
    package_directory_hint,
)


def _module_id(mod: dict[str, Any], idx: int) -> str:
    artifact = mod.get("artifactId")
    if isinstance(artifact, str) and artifact.strip():
        return f"m:{artifact.strip()}"
    p = str(mod.get("path") or mod.get("name") or f"module-{idx}")
    return f"m:{p}"


def build_graph(
    modules_json: dict[str, Any],
    symbols_json: dict[str, Any],
    rest_map_json: dict[str, Any] | None,
    *,
    project_root: Path,
) -> dict[str, Any]:
    """Build docs/samples-like graph (module/package/type + optional rest endpoints)."""
    root = Path(modules_json.get("projectRoot", str(project_root))).resolve()
    modules = modules_json.get("modules") or []
    pkg_files = collect_package_file_map(symbols_json)
    pkg_symbols = symbols_json.get("packages") if isinstance(symbols_json, dict) else {}
    if not isinstance(pkg_symbols, dict):
        pkg_symbols = {}

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    edge_id = 0

    # module nodes
    module_items: list[tuple[str, str]] = []  # (module_id, module_path)
    for i, m in enumerate(modules):
        if not isinstance(m, dict):
            continue
        mod_id = _module_id(m, i)
        mod_path = str(m.get("path") or ".")
        module_items.append((mod_id, mod_path))
        nodes.append(
            {
                "id": mod_id,
                "kind": "maven_module",
                "label": str(m.get("name") or Path(mod_path).name or mod_path),
                "path": mod_path,
                "attrs": {
                    "artifactId": m.get("artifactId"),
                    "packaging": m.get("packaging"),
                    "source": m.get("source"),
                },
            }
        )

    # package + type nodes and structural edges
    type_fqn_to_id: dict[str, str] = {}
    type_file_to_ids: dict[str, list[str]] = {}
    for pkg, files in sorted(pkg_files.items()):
        pkg_id = f"pkg:{pkg}"
        nodes.append(
            {
                "id": pkg_id,
                "kind": "package",
                "label": pkg,
                "path": package_directory_hint(root, files),
                "attrs": {},
            }
        )

        for mod_id, mod_path in module_items:
            if any(file_under_module_root(root, mod_path, f) for f in files):
                edge_id += 1
                edges.append(
                    {
                        "id": f"e{edge_id}",
                        "relation": "contains",
                        "source": mod_id,
                        "target": pkg_id,
                        "kind": "module_contains_package",
                        "attrs": {},
                    }
                )

        for s in (pkg_symbols.get(pkg) or []):
            if not isinstance(s, dict):
                continue
            n = s.get("name")
            if not isinstance(n, str) or not n.strip():
                continue
            file_rel = s.get("file")
            if not isinstance(file_rel, str) or not file_rel.endswith(".java"):
                continue
            fqn = f"{pkg}.{n.strip()}"
            type_id = f"type:{fqn}"
            type_fqn_to_id[fqn] = type_id
            type_file_to_ids.setdefault(file_rel.replace("\\", "/"), []).append(type_id)
            nodes.append(
                {
                    "id": type_id,
                    "kind": "type",
                    "label": n.strip(),
                    "fqn": fqn,
                    "path": file_rel.replace("\\", "/"),
                    "attrs": {
                        "kindLabel": s.get("kindLabel"),
                        "symbolKind": s.get("kind"),
                    },
                }
            )
            edge_id += 1
            edges.append(
                {
                    "id": f"e{edge_id}",
                    "relation": "contains",
                    "source": pkg_id,
                    "target": type_id,
                    "kind": "package_contains_type",
                    "attrs": {},
                }
            )

    # Optional REST endpoint nodes and endpoint->type edges
    endpoints = rest_map_json.get("endpoints") if isinstance(rest_map_json, dict) else None
    if isinstance(endpoints, list):
        for i, ep in enumerate(endpoints):
            if not isinstance(ep, dict):
                continue
            path = ep.get("path")
            method = ep.get("httpMethod")
            if not isinstance(path, str):
                continue
            label = f"{method or '?'} {path}".strip()
            ep_id = f"ep:{i}:{label}"
            nodes.append(
                {
                    "id": ep_id,
                    "kind": "entrypoint",
                    "label": label,
                    "path": path,
                    "attrs": {
                        "annotation": ep.get("annotation"),
                        "line": ep.get("line"),
                    },
                }
            )
            type_id = None
            cls = ep.get("className")
            if isinstance(cls, str) and cls in type_fqn_to_id:
                type_id = type_fqn_to_id[cls]
            if type_id is None:
                file_rel = ep.get("file")
                if isinstance(file_rel, str):
                    bucket = type_file_to_ids.get(file_rel.replace("\\", "/")) or []
                    if bucket:
                        type_id = bucket[0]
            if type_id:
                edge_id += 1
                edges.append(
                    {
                        "id": f"e{edge_id}",
                        "relation": "depends_on",
                        "source": ep_id,
                        "target": type_id,
                        "kind": "rest_entrypoint_to_type",
                        "attrs": {
                            "httpMethod": method,
                            "path": path,
                            "methodName": ep.get("methodName"),
                        },
                    }
                )

    by_kind: dict[str, int] = {}
    for n in nodes:
        kind = str(n.get("kind") or "unknown")
        by_kind[kind] = by_kind.get(kind, 0) + 1

    return {
        "$schema": "https://example.local/schemas/java-historical-analysis/graph-1.json",
        "schema_version": "1.0",
        "manifest_ref": "1.1-analysis_manifest.json",
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "by_kind": by_kind,
        },
        "_source": "java-code-wiki.build_graph",
    }
