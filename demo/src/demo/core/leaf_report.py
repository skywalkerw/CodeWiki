"""Generate 2.1 leaf markdown reports from static artifacts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def _slug(s: str, max_len: int = 80) -> str:
    t = _SAFE.sub("-", s.strip()).strip("-")
    return t[:max_len] if t else "leaf"


def _leaf_report_name(module_name: str, leaf_name: str) -> str:
    return f"2.1-leaf_{_slug(module_name, 40)}-{_slug(leaf_name, 40)}.md"


def _rest_index(rest_map_json: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    endpoints = rest_map_json.get("endpoints") if isinstance(rest_map_json, dict) else None
    if not isinstance(endpoints, list):
        return out
    for ep in endpoints:
        if not isinstance(ep, dict):
            continue
        f = ep.get("file")
        if isinstance(f, str) and f:
            out.setdefault(f.replace("\\", "/"), []).append(ep)
    return out


def _leaf_markdown(
    module: dict[str, Any],
    leaf: dict[str, Any],
    manifest_name: str,
    rest_by_file: dict[str, list[dict[str, Any]]],
) -> str:
    module_name = str(module.get("artifactId") or module.get("name") or module.get("path") or "module")
    leaf_name = str(leaf.get("name") or leaf.get("full_package") or "leaf")
    leaf_id = str(leaf.get("id") or "")
    full_package = str(leaf.get("full_package") or "")
    path = str(leaf.get("path") or "")
    m = leaf.get("metrics") if isinstance(leaf.get("metrics"), dict) else {}
    loc = m.get("loc_java", 0)
    type_count = m.get("type_count", 0)

    type_rows: list[str] = []
    endpoint_rows: list[str] = []
    for t in (leaf.get("children") or []):
        if not isinstance(t, dict):
            continue
        if t.get("kind") != "type_leaf":
            continue
        fqn = t.get("qualified_name") or t.get("name") or "-"
        kind = t.get("kindLabel") or "type"
        file_rel = str(t.get("file") or "")
        type_rows.append(f"| `{fqn}` | {kind} | `{file_rel}` |")
        for ep in rest_by_file.get(file_rel, []):
            method = ep.get("httpMethod") or "?"
            epath = ep.get("path") or ""
            mname = ep.get("methodName") or ""
            endpoint_rows.append(f"| `{method}` | `{epath}` | `{mname}` |")

    type_rows = type_rows[:12]
    endpoint_rows = endpoint_rows[:12]

    lines = [
        f"# 叶子模块分析：`{module_name}` / `{leaf_name}`",
        "",
        f"> 编号 **2.x**：由第一层产物派生的叶子报告。对应 `1.3-module_tree.json` 的 `{leaf_id or leaf_name}`。",
        f"> 分析快照见 `{manifest_name}`。",
        "",
        "## 1. 范围与边界",
        "",
        "| 项 | 值 |",
        "|----|-----|",
        f"| 路径 | `{path}` |",
        f"| Maven 模块 | `{module_name}` |",
        f"| 包 | `{full_package}` |",
        f"| 粗粒度 LOC（Java） | {loc} |",
        f"| 类型数 | {type_count} |",
        "",
        "## 2. 职责摘要",
        "",
        f"该叶子聚焦包 `{full_package or leaf_name}`，作为模块 `{module_name}` 下的可阅读单元。",
        "建议先读公共入口类型，再顺着依赖深入内部实现。",
        "",
        "## 3. 关键类型（节选）",
        "",
        "| FQN | 角色 | 文件 |",
        "|-----|------|------|",
    ]
    if type_rows:
        lines.extend(type_rows)
    else:
        lines.append("| `-` | - | - |")

    lines.extend(
        [
            "",
            "## 4. 相关 HTTP 入口（按文件关联，节选）",
            "",
            "| Method | Path | Handler |",
            "|--------|------|---------|",
        ]
    )
    if endpoint_rows:
        lines.extend(endpoint_rows)
    else:
        lines.append("| `-` | - | - |")

    lines.extend(
        [
            "",
            "## 5. 交叉引用",
            "",
            "- 依赖图：`data/1.2-graph.json`",
            "- 模块树：`data/1.3-module_tree.json`",
            "- 入口清单：`data/1.4-entrypoints.json`",
            "- REST 映射：`data/1.5-rest-map.json`",
        ]
    )
    return "\n".join(lines) + "\n"


def write_leaf_reports(
    output_dir: Path,
    module_tree_json: dict[str, Any],
    rest_map_json: dict[str, Any],
    *,
    manifest_name: str = "1.1-analysis_manifest.json",
) -> list[str]:
    """Write one 2.1 leaf markdown per feature_leaf under output_dir/reports."""
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    for stale in reports_dir.glob("2.1-leaf_*.md"):
        stale.unlink(missing_ok=True)
    rest_by_file = _rest_index(rest_map_json)
    written: list[str] = []

    root = module_tree_json.get("root") if isinstance(module_tree_json, dict) else None
    modules = root.get("children") if isinstance(root, dict) else None
    if not isinstance(modules, list):
        return written

    for module in modules:
        if not isinstance(module, dict):
            continue
        module_name = str(module.get("artifactId") or module.get("name") or module.get("path") or "module")
        leaves = module.get("children")
        if not isinstance(leaves, list):
            continue
        for leaf in leaves:
            if not isinstance(leaf, dict) or leaf.get("kind") != "feature_leaf":
                continue
            leaf_name = str(leaf.get("name") or leaf.get("full_package") or "leaf")
            file_name = _leaf_report_name(module_name, leaf_name)
            content = _leaf_markdown(module, leaf, manifest_name, rest_by_file)
            path = reports_dir / file_name
            path.write_text(content, encoding="utf-8")
            written.append(str(path.relative_to(output_dir)))

    return sorted(written)

