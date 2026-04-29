"""Dynamic decomposition + recursive documentation loop (CodeWiki-style)."""

from __future__ import annotations

import logging
import re
import json
import urllib.request
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)
_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def _slug(s: str, max_len: int = 60) -> str:
    t = _SAFE.sub("-", s.strip()).strip("-")
    return t[:max_len] if t else "node"


def _as_int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _is_terminal_feature_leaf(node: dict[str, Any]) -> bool:
    if node.get("kind") != "feature_leaf":
        return False
    children = node.get("children") or []
    if not isinstance(children, list):
        return False
    # terminal leaf = only type_leaf children
    return all(isinstance(c, dict) and c.get("kind") == "type_leaf" for c in children)


def _terminal_leaves(module_tree: dict[str, Any]) -> list[tuple[list[str], dict[str, Any], dict[str, Any]]]:
    """
    Return tuples of (path_parts, module_node, leaf_node).
    path excludes repository root; module name first then delegated names.
    """
    out: list[tuple[list[str], dict[str, Any], dict[str, Any]]] = []
    root = module_tree.get("root") if isinstance(module_tree, dict) else None
    modules = root.get("children") if isinstance(root, dict) else None
    if not isinstance(modules, list):
        return out

    def walk(parent_path: list[str], module_node: dict[str, Any], node: dict[str, Any]) -> None:
        if _is_terminal_feature_leaf(node):
            out.append((parent_path + [str(node.get("name") or "leaf")], module_node, node))
            return
        for ch in node.get("children") or []:
            if isinstance(ch, dict) and ch.get("kind") in ("feature_leaf", "feature_parent"):
                walk(parent_path + [str(node.get("name") or "leaf")], module_node, ch)

    for m in modules:
        if not isinstance(m, dict):
            continue
        m_name = str(m.get("name") or m.get("artifactId") or m.get("path") or "module")
        for leaf in m.get("children") or []:
            if isinstance(leaf, dict):
                walk([m_name], m, leaf)
    return out


def _sum_metrics_from_type_children(children: list[dict[str, Any]]) -> tuple[int, int]:
    loc = 0
    tcount = 0
    for c in children:
        if not isinstance(c, dict) or c.get("kind") != "type_leaf":
            continue
        loc += _as_int((c.get("metrics") or {}).get("loc_java"))
        tcount += 1
    return loc, tcount


def _chunk_types(type_nodes: list[dict[str, Any]], max_leaf_types: int) -> list[list[dict[str, Any]]]:
    """
    Stable deterministic chunks. Prefer split by kindLabel first, then chunk.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    for t in type_nodes:
        k = str(t.get("kindLabel") or "type")
        buckets.setdefault(k, []).append(t)
    chunks: list[list[dict[str, Any]]] = []
    for k in sorted(buckets.keys()):
        seq = sorted(
            buckets[k],
            key=lambda x: (str(x.get("file") or ""), _as_int(x.get("line")), str(x.get("name") or "")),
        )
        for i in range(0, len(seq), max_leaf_types):
            chunks.append(seq[i : i + max_leaf_types])
    return chunks


def evolve_module_tree_dynamic(
    module_tree: dict[str, Any],
    *,
    max_depth: int = 3,
    max_leaf_types: int = 8,
    max_leaf_loc: int = 1800,
) -> tuple[dict[str, Any], int]:
    """
    Dynamic delegation loop:
    - If terminal feature leaf exceeds complexity budget, split into child feature_leaf nodes.
    - Repeat until stable or max depth reached.
    Returns (mutated_tree, delegation_count).
    """
    delegation_count = 0

    def recurse(node: dict[str, Any], depth: int) -> bool:
        nonlocal delegation_count
        changed = False
        if _is_terminal_feature_leaf(node):
            metrics = node.get("metrics") if isinstance(node.get("metrics"), dict) else {}
            loc = _as_int(metrics.get("loc_java"))
            tcount = _as_int(metrics.get("type_count"))
            over_budget = tcount > max_leaf_types or loc > max_leaf_loc
            if over_budget and depth < max_depth:
                types = [c for c in (node.get("children") or []) if isinstance(c, dict) and c.get("kind") == "type_leaf"]
                if len(types) > 1:
                    chunks = _chunk_types(types, max_leaf_types=max_leaf_types)
                    # Avoid meaningless split into one chunk.
                    if len(chunks) > 1:
                        new_children: list[dict[str, Any]] = []
                        for i, chunk in enumerate(chunks):
                            c_loc, c_types = _sum_metrics_from_type_children(chunk)
                            child_name = f"{node.get('name')}-part{i + 1}"
                            child = {
                                "id": f"{node.get('id')}-d{depth + 1}-{i}",
                                "name": child_name,
                                "kind": "feature_leaf",
                                "full_package": node.get("full_package"),
                                "path": node.get("path"),
                                "metrics": {
                                    "loc_java": c_loc,
                                    "type_count": c_types,
                                    "cyclomatic_sum": _as_int(metrics.get("cyclomatic_sum")),
                                },
                                "delegation_depth": depth + 1,
                                "children": chunk,
                            }
                            new_children.append(child)
                        node["kind"] = "feature_parent"
                        node["notes"] = "auto-delegated by dynamic loop"
                        node["children"] = new_children
                        delegation_count += 1
                        LOG.info(
                            "Delegated leaf id=%s name=%s into %d children (depth=%d)",
                            node.get("id"),
                            node.get("name"),
                            len(new_children),
                            depth + 1,
                        )
                        return True
            return False

        for ch in node.get("children") or []:
            if isinstance(ch, dict) and ch.get("kind") in ("feature_leaf", "feature_parent"):
                if recurse(ch, depth + 1):
                    changed = True
        return changed

    root = module_tree.get("root") if isinstance(module_tree, dict) else None
    modules = root.get("children") if isinstance(root, dict) else None
    if not isinstance(modules, list):
        return module_tree, delegation_count

    while True:
        changed = False
        for m in modules:
            if not isinstance(m, dict):
                continue
            for n in m.get("children") or []:
                if isinstance(n, dict) and n.get("kind") in ("feature_leaf", "feature_parent"):
                    if recurse(n, 0):
                        changed = True
        if not changed:
            break
    return module_tree, delegation_count


def _leaf_doc_content(
    module_name: str,
    leaf_name: str,
    path: str,
    full_package: str,
    metrics: dict[str, Any],
    type_rows: list[str],
    type_details: list[str],
    endpoint_rows: list[str],
    signals: dict[str, float],
) -> str:
    loc = _as_int(metrics.get("loc_java"))
    tcount = _as_int(metrics.get("type_count"))
    lines = [
        f"# 叶子模块分析：`{module_name}` / `{leaf_name}`",
        "",
        "## 1. 范围与边界",
        "",
        "| 项 | 值 |",
        "|----|-----|",
        f"| 路径 | `{path}` |",
        f"| 包 | `{full_package}` |",
        f"| 粗粒度 LOC（Java） | {loc} |",
        f"| 类型数 | {tcount} |",
        f"| 类型覆盖率（typed_ratio） | {signals.get('typed_ratio', 0):.3f} |",
        f"| 体量信号（size_score） | {signals.get('size_score', 0):.3f} |",
        f"| 入口信号（entrypoint_score） | {signals.get('entrypoint_score', 0):.3f} |",
        "",
        "## 2. 职责摘要",
        "",
        f"该叶子聚焦 `{full_package}` 包，位于模块 `{module_name}` 路径 `{path}`。",
        "建议先阅读关键类型，再顺着对外入口和服务实现深入。",
        "",
        "## 3. 关键类型（节选）",
        "",
        "| FQN | 角色 | 文件 |",
        "|-----|------|------|",
    ]
    lines.extend(type_rows[:16] if type_rows else ["| `-` | - | - |"])
    lines.extend(
        [
            "",
            "### 3.1 类型明细",
            "",
        ]
    )
    lines.extend(type_details[:24] if type_details else ["- 无可用类型明细"])
    lines.extend(
        [
            "",
            "## 4. 关联 HTTP 入口（按同文件匹配）",
            "",
            "| Method | Path | Handler |",
            "|--------|------|---------|",
        ]
    )
    lines.extend(endpoint_rows[:20] if endpoint_rows else ["| `-` | - | - |"])
    lines.extend(
        [
            "",
            "## 5. 建议阅读顺序",
            "",
            "1. 先看本节关键类型表中的前 3 个类型",
            "2. 再看同文件关联的 HTTP 入口（若有）",
            "3. 最后结合 `1.2-graph` 追踪跨包依赖",
            "",
            "## 6. 交叉引用",
            "",
            "- `data/1.2-graph.json`",
            "- `data/1.3-module_tree.json`",
            "- `data/1.4-entrypoints.json`",
            "- `data/1.5-rest-map.json`",
            "- `reports/2.2-rubric_eval.sample.json`",
        ]
    )
    return "\n".join(lines) + "\n"


def _llm_synthesize_markdown(
    *,
    model: str,
    base_url: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    timeout_sec: float,
    retry_times: int = 1,
) -> str:
    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    LOG.debug("LLM synth request model=%s base_url=%s", model, base_url)
    raw = ""
    last_error: Exception | None = None
    for attempt in range(retry_times + 1):
        try:
            req = urllib.request.Request(
                url=f"{base_url.rstrip('/')}/chat/completions",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            )
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            break
        except Exception as e:  # noqa: BLE001
            last_error = e
            LOG.warning("LLM synth failed attempt=%d/%d err=%s", attempt + 1, retry_times + 1, e)
            if attempt >= retry_times:
                raise
    if not raw and last_error:
        raise last_error
    LOG.debug("LLM synth raw response=%s", raw)
    payload = json.loads(raw)
    content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
    text = str(content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("markdown"):
            text = text[len("markdown") :].strip()
    return text or "## Synthesis Empty\n"


def run_dynamic_documentation_loop(
    output_dir: Path,
    module_tree_json: dict[str, Any],
    rest_map_json: dict[str, Any] | None = None,
    *,
    max_depth: int = 3,
    max_leaf_types: int = 8,
    max_leaf_loc: int = 1800,
    use_llm_synthesis: bool = False,
    llm_model: str | None = None,
    llm_base_url: str | None = None,
    llm_api_key: str | None = None,
    llm_timeout_sec: float = 90.0,
    llm_parent_timeout_sec: float | None = None,
    llm_synth_retry_times: int = 1,
) -> dict[str, Any]:
    """
    Three-phase dynamic loop (deterministic, no extra LLM calls):
    1) evolve module tree via delegation until stable
    2) generate leaf docs for terminal leaves
    3) bottom-up assembly for parent docs + repository overview
    """
    reports_dir = output_dir / "reports"
    docs_dir = output_dir / "docs"
    reports_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    # Clear prior dynamic docs
    for p in list(reports_dir.glob("2.1-leaf_*.md")) + list(reports_dir.glob("2.3-parent_*.md")):
        p.unlink(missing_ok=True)
    (output_dir / "0.1-REPOSITORY_OVERVIEW.md").unlink(missing_ok=True)

    tree, delegation_count = evolve_module_tree_dynamic(
        module_tree_json,
        max_depth=max_depth,
        max_leaf_types=max_leaf_types,
        max_leaf_loc=max_leaf_loc,
    )

    leaves = _terminal_leaves(tree)
    leaf_paths: list[str] = []
    for path_parts, module_node, leaf in leaves:
        module_name = str(module_node.get("artifactId") or module_node.get("name") or module_node.get("path") or "module")
        leaf_name = str(leaf.get("name") or leaf.get("full_package") or "leaf")
        fname = f"2.1-leaf_{_slug(module_name, 40)}-{_slug('-'.join(path_parts[1:]), 60)}.md"
        rows: list[str] = []
        type_details: list[str] = []
        type_files: set[str] = set()
        for t in leaf.get("children") or []:
            if not isinstance(t, dict) or t.get("kind") != "type_leaf":
                continue
            f = str(t.get("file") or "")
            if f:
                type_files.add(f.replace("\\", "/"))
            rows.append(
                f"| `{t.get('qualified_name') or t.get('name')}` | {t.get('kindLabel') or 'type'} | `{t.get('file') or ''}` |"
            )
            type_details.append(
                "- `{}` (`{}`) line={} loc={}".format(
                    t.get("qualified_name") or t.get("name") or "-",
                    t.get("kindLabel") or "type",
                    t.get("line") if t.get("line") is not None else "-",
                    _as_int((t.get("metrics") or {}).get("loc_java")),
                )
            )
        endpoint_rows: list[str] = []
        endpoint_hit = 0
        endpoints = rest_map_json.get("endpoints") if isinstance(rest_map_json, dict) else None
        if isinstance(endpoints, list):
            for ep in endpoints:
                if not isinstance(ep, dict):
                    continue
                file_rel = ep.get("file")
                if not isinstance(file_rel, str):
                    continue
                if file_rel.replace("\\", "/") not in type_files:
                    continue
                endpoint_hit += 1
                endpoint_rows.append(
                    "| `{}` | `{}` | `{}` |".format(
                        ep.get("httpMethod") or "?",
                        ep.get("path") or "",
                        ep.get("methodName") or "",
                    )
                )
        m = leaf.get("metrics") if isinstance(leaf.get("metrics"), dict) else {}
        tcount = _as_int(m.get("type_count"))
        loc = _as_int(m.get("loc_java"))
        signals = {
            "typed_ratio": (len([x for x in (leaf.get("children") or []) if isinstance(x, dict) and x.get("kind") == "type_leaf"]) / tcount) if tcount else 0.0,
            "size_score": min(1.0, loc / 1200.0) if loc > 0 else 0.0,
            "entrypoint_score": 1.0 if endpoint_hit > 0 else 0.0,
        }
        text = _leaf_doc_content(
            module_name=module_name,
            leaf_name=leaf_name,
            path=str(leaf.get("path") or ""),
            full_package=str(leaf.get("full_package") or ""),
            metrics=leaf.get("metrics") if isinstance(leaf.get("metrics"), dict) else {},
            type_rows=rows,
            type_details=type_details,
            endpoint_rows=endpoint_rows,
            signals=signals,
        )
        p = reports_dir / fname
        p.write_text(text, encoding="utf-8")
        leaf_paths.append(str(p.relative_to(output_dir)))

    can_llm = bool(use_llm_synthesis and llm_model and llm_base_url and llm_api_key)
    if use_llm_synthesis and not can_llm:
        LOG.warning("LLM synthesis requested but credentials/model missing; fallback to template assembly.")

    # Parent assembly (module-level)
    root = tree.get("root") if isinstance(tree, dict) else {}
    modules = root.get("children") if isinstance(root, dict) else []
    parent_paths: list[str] = []
    if isinstance(modules, list):
        for m in modules:
            if not isinstance(m, dict):
                continue
            m_name = str(m.get("artifactId") or m.get("name") or m.get("path") or "module")
            m_slug = _slug(m_name, 50)
            child_docs = [p for p in leaf_paths if f"2.1-leaf_{_slug(m_name,40)}-" in p]
            out = reports_dir / f"2.3-parent_{m_slug}.md"
            if can_llm:
                child_payload: list[dict[str, Any]] = []
                for d in child_docs[:8]:
                    text = (output_dir / d).read_text(encoding="utf-8", errors="replace")
                    child_payload.append({"path": d, "content": text[:1800]})
                prompt = (
                    "请基于子模块文档，生成父模块汇总 Markdown。要求：\n"
                    "1) 包含职责摘要\n2) 子模块关系\n3) 风险与后续建议\n"
                    f"父模块: {m_name}\n"
                    f"子文档JSON: {json.dumps(child_payload, ensure_ascii=False)}"
                )
                try:
                    text = _llm_synthesize_markdown(
                        model=str(llm_model),
                        base_url=str(llm_base_url),
                        api_key=str(llm_api_key),
                        system_prompt="你是资深 Java 架构文档工程师，只输出 Markdown。",
                        user_prompt=prompt,
                        timeout_sec=llm_parent_timeout_sec or llm_timeout_sec,
                        retry_times=max(llm_synth_retry_times, 0),
                    )
                except Exception as e:  # noqa: BLE001
                    LOG.warning("Parent LLM synthesis failed for %s: %s", m_name, e)
                    text = ""
            else:
                text = ""
            if not text:
                summary = [
                    f"# 父模块汇总：`{m_name}`",
                    "",
                    "## 子模块文档",
                    "",
                ]
                summary.extend([f"- `{d}`" for d in child_docs] or ["- `无`"])
                text = "\n".join(summary) + "\n"
            out.write_text(text, encoding="utf-8")
            parent_paths.append(str(out.relative_to(output_dir)))

    overview_text = ""
    if can_llm:
        parent_payload = []
        for p in parent_paths[:8]:
            txt = (output_dir / p).read_text(encoding="utf-8", errors="replace")
            parent_payload.append({"path": p, "content": txt[:2200]})
        prompt = (
            "请生成仓库级总览 Markdown，包含：架构概览、关键模块、处理流程、主要风险。\n"
            f"仓库名: {root.get('name') or 'repository'}\n"
            f"动态委托次数: {delegation_count}\n"
            f"父文档JSON: {json.dumps(parent_payload, ensure_ascii=False)}"
        )
        try:
            overview_text = _llm_synthesize_markdown(
                model=str(llm_model),
                base_url=str(llm_base_url),
                api_key=str(llm_api_key),
                system_prompt="你是资深 Java 架构文档工程师，只输出 Markdown。",
                user_prompt=prompt,
                timeout_sec=llm_timeout_sec,
                retry_times=max(llm_synth_retry_times, 0),
            )
        except Exception as e:  # noqa: BLE001
            LOG.warning("Repository LLM synthesis failed: %s", e)
            overview_text = ""
    if not overview_text:
        overview = [
            f"# Repository Overview: `{root.get('name') or 'repository'}`",
            "",
            "## Dynamic Loop Summary",
            "",
            f"- delegations: {delegation_count}",
            f"- terminal leaf docs: {len(leaf_paths)}",
            f"- parent docs: {len(parent_paths)}",
        ]
        overview_text = "\n".join(overview) + "\n"
    (output_dir / "0.1-REPOSITORY_OVERVIEW.md").write_text(overview_text, encoding="utf-8")

    return {
        "module_tree": tree,
        "delegations": delegation_count,
        "leaf_docs": leaf_paths,
        "parent_docs": parent_paths,
        "overview_doc": "0.1-REPOSITORY_OVERVIEW.md",
    }

