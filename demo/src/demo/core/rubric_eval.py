"""Deterministic 2.2 rubric evaluation from static artifacts."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def _rest_hits_by_file(rest_map_json: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    endpoints = rest_map_json.get("endpoints") if isinstance(rest_map_json, dict) else None
    if not isinstance(endpoints, list):
        return out
    for ep in endpoints:
        if not isinstance(ep, dict):
            continue
        f = ep.get("file")
        if isinstance(f, str) and f:
            out.add(f.replace("\\", "/"))
    return out


def _leaf_score(leaf: dict[str, Any], rest_files: set[str]) -> tuple[float, dict[str, float]]:
    m = leaf.get("metrics") if isinstance(leaf.get("metrics"), dict) else {}
    type_count = int(m.get("type_count") or 0)
    loc = int(m.get("loc_java") or 0)
    type_children = [c for c in (leaf.get("children") or []) if isinstance(c, dict) and c.get("kind") == "type_leaf"]
    typed_ratio = _clamp01(len(type_children) / type_count) if type_count > 0 else 0.0
    size_score = _clamp01(loc / 1200.0)  # saturates at 1.0 near medium leaf size
    has_entry = 0.0
    for c in type_children:
        f = c.get("file")
        if isinstance(f, str) and f.replace("\\", "/") in rest_files:
            has_entry = 1.0
            break
    score = 0.5 * typed_ratio + 0.3 * size_score + 0.2 * has_entry
    return _clamp01(score), {
        "typed_ratio": round(typed_ratio, 6),
        "size_score": round(size_score, 6),
        "entrypoint_score": round(has_entry, 6),
    }


def _collect_terminal_feature_leaves(node: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    kind = node.get("kind")
    children = node.get("children") or []
    if kind == "feature_leaf" and isinstance(children, list):
        if all(isinstance(c, dict) and c.get("kind") == "type_leaf" for c in children):
            return [node]
    if isinstance(children, list):
        for ch in children:
            if isinstance(ch, dict) and ch.get("kind") in ("feature_leaf", "feature_parent"):
                out.extend(_collect_terminal_feature_leaves(ch))
    return out


def _llm_leaf_judgement(
    *,
    model: str,
    base_url: str,
    api_key: str,
    module_name: str,
    leaf_name: str,
    full_package: str,
    leaf_path: str,
    loc: int,
    type_count: int,
    endpoint_count: int,
    type_samples: list[dict[str, Any]],
    endpoint_samples: list[dict[str, Any]],
    signals: dict[str, float],
    timeout_sec: float = 25.0,
) -> tuple[float, str]:
    """
    Ask LLM for a single [0,1] coverage score and short rationale.
    Endpoint assumes OpenAI-compatible ``/chat/completions``.
    """
    prompt = (
        "你是 Java 架构分析评审。根据给定叶子模块静态信息，"
        "给出一个 [0,1] 的覆盖度分数（1=信息充分，0=信息严重不足），"
        "并给出一句中文理由。"
        "\n输出 JSON，格式严格为："
        '{"score": 0.0, "rationale": "..."}.'
        "\n不要输出其它文本。"
        f"\n模块: {module_name}"
        f"\n叶子: {leaf_name}"
        f"\n包: {full_package}"
        f"\n路径: {leaf_path}"
        f"\nLOC: {loc}"
        f"\n类型数: {type_count}"
        f"\n关联 HTTP 入口数: {endpoint_count}"
        f"\n静态信号: {json.dumps(signals, ensure_ascii=False)}"
        f"\n类型样本(最多8条): {json.dumps(type_samples, ensure_ascii=False)}"
        f"\n入口样本(最多8条): {json.dumps(endpoint_samples, ensure_ascii=False)}"
    )
    LOG.debug(
        "LLM judge request model=%s base_url=%s module=%s leaf=%s package=%s loc=%s types=%s endpoints=%s timeout=%s",
        model,
        base_url,
        module_name,
        leaf_name,
        full_package,
        loc,
        type_count,
        endpoint_count,
        timeout_sec,
    )

    def call_once(model_name: str) -> dict[str, Any]:
        body = {
            "model": model_name,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "你是严谨的代码分析评审。仅输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
        }
        base = base_url.rstrip("/")
        req = urllib.request.Request(
            url=f"{base}/chat/completions",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )
        LOG.debug("LLM raw request body=%s", json.dumps(body, ensure_ascii=False))
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw_resp = resp.read().decode("utf-8", errors="replace")
            LOG.debug("LLM raw response model=%s body=%s", model_name, raw_resp)
            return json.loads(raw_resp)

    try:
        payload = call_once(model)
    except urllib.error.HTTPError as e:
        # Some gateways are case-sensitive for model ids (e.g. glm-5 vs GLM-5).
        if model != model.lower():
            payload = call_once(model.lower())
        else:
            raise e
    content = (
        payload.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    if not isinstance(content, str) or not content.strip():
        raise ValueError("empty LLM content")
    raw = content.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.replace("json", "", 1).strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: extract the first JSON object from mixed text.
        s = raw.find("{")
        e = raw.rfind("}")
        if s == -1 or e == -1 or e <= s:
            raise
        obj = json.loads(raw[s : e + 1])
    score = float(obj.get("score", 0.0))
    rationale = str(obj.get("rationale", "")).strip() or "LLM 未提供理由"
    LOG.debug("LLM parsed result score=%s rationale=%s", score, rationale)
    return _clamp01(score), rationale


def build_rubric_eval(
    module_tree_json: dict[str, Any],
    rest_map_json: dict[str, Any],
    *,
    project_name: str,
    judge_model: str | None = None,
    judge_base_url: str | None = None,
    judge_api_key: str | None = None,
    judge_timeout_sec: float = 90.0,
    judge_max_leaves: int | None = None,
) -> dict[str, Any]:
    """Create sample-style hierarchical rubric with deterministic scores."""
    rest_files = _rest_hits_by_file(rest_map_json)
    root = module_tree_json.get("root") if isinstance(module_tree_json, dict) else None
    modules = root.get("children") if isinstance(root, dict) else None
    if not isinstance(modules, list):
        modules = []

    rubric_children: list[dict[str, Any]] = []
    weighted_sum = 0.0
    total_weight = 0.0
    use_llm = bool(judge_model and judge_base_url and judge_api_key)
    llm_failures = 0
    llm_last_error: str | None = None
    llm_used = 0

    for mod_idx, mod in enumerate(modules):
        if not isinstance(mod, dict):
            continue
        leaves: list[dict[str, Any]] = []
        for x in (mod.get("children") or []):
            if isinstance(x, dict) and x.get("kind") in ("feature_leaf", "feature_parent"):
                leaves.extend(_collect_terminal_feature_leaves(x))
        if not leaves:
            continue
        mod_title = str(mod.get("name") or mod.get("artifactId") or mod.get("path") or f"module-{mod_idx}")
        mod_weight = float(sum(int((lf.get("metrics") or {}).get("loc_java") or 0) for lf in leaves) or len(leaves))
        leaf_children: list[dict[str, Any]] = []
        mod_sum = 0.0
        mod_w = 0.0
        for lf_idx, leaf in enumerate(leaves):
            leaf_name = str(leaf.get("name") or leaf.get("full_package") or f"leaf-{lf_idx}")
            full_package = str(leaf.get("full_package") or "")
            leaf_path = str(leaf.get("path") or "")
            leaf_loc = float(int((leaf.get("metrics") or {}).get("loc_java") or 0) or 1)
            det_score, signals = _leaf_score(leaf, rest_files)
            endpoint_count = 0
            endpoint_samples: list[dict[str, Any]] = []
            type_samples: list[dict[str, Any]] = []
            leaf_type_files: set[str] = set()
            for c in (leaf.get("children") or []):
                if not isinstance(c, dict):
                    continue
                f = c.get("file")
                if isinstance(f, str):
                    fr = f.replace("\\", "/")
                    leaf_type_files.add(fr)
                    if fr in rest_files:
                        endpoint_count += 1
                if len(type_samples) < 8 and c.get("kind") == "type_leaf":
                    type_samples.append(
                        {
                            "fqn": c.get("qualified_name") or c.get("name"),
                            "kind": c.get("kindLabel"),
                            "file": c.get("file"),
                            "line": c.get("line"),
                        }
                    )
            # Match endpoint samples by exact type files inside this leaf to avoid noisy context.
            endpoints = rest_map_json.get("endpoints") if isinstance(rest_map_json, dict) else None
            if isinstance(endpoints, list):
                for ep in endpoints:
                    if not isinstance(ep, dict):
                        continue
                    file_rel = ep.get("file")
                    if not isinstance(file_rel, str):
                        continue
                    if file_rel.replace("\\", "/") not in leaf_type_files:
                        continue
                    endpoint_samples.append(
                        {
                            "method": ep.get("httpMethod"),
                            "path": ep.get("path"),
                            "class": ep.get("className"),
                            "handler": ep.get("methodName"),
                            "line": ep.get("line"),
                        }
                    )
                    if len(endpoint_samples) >= 8:
                        break
            leaf_item: dict[str, Any] = {
                "id": f"R.mod{mod_idx}.leaf{lf_idx}",
                "title": f"叶子 `{leaf_name}` 信息完备性",
                "weight": 1.0,
                "leaf": True,
                "signals": signals,
            }
            if use_llm:
                llm_allowed = judge_max_leaves is None or llm_used < max(judge_max_leaves, 0)
                if not llm_allowed:
                    score = det_score
                    leaf_item["method"] = "deterministic_static_signals_v1_sampled_out"
                    leaf_item["leaf_score"] = score
                    leaf_item["leaf_stdev"] = 0.0
                    leaf_children.append(leaf_item)
                    mod_sum += score * leaf_loc
                    mod_w += leaf_loc
                    continue
                try:
                    llm_score, rationale = _llm_leaf_judgement(
                        model=str(judge_model),
                        base_url=str(judge_base_url),
                        api_key=str(judge_api_key),
                        module_name=mod_title,
                        leaf_name=leaf_name,
                        full_package=full_package,
                        leaf_path=leaf_path,
                        loc=int(leaf_loc),
                        type_count=int((leaf.get("metrics") or {}).get("type_count") or 0),
                        endpoint_count=endpoint_count,
                        type_samples=type_samples,
                        endpoint_samples=endpoint_samples,
                        signals=signals,
                        timeout_sec=judge_timeout_sec,
                    )
                    score = llm_score
                    llm_used += 1
                    leaf_item["method"] = "llm_judge_v1"
                    leaf_item["assessments"] = [
                        {
                            "judge": str(judge_model),
                            "satisfied": llm_score >= 0.5,
                            "rationale": rationale,
                        }
                    ]
                except (
                    TimeoutError,
                    urllib.error.HTTPError,
                    urllib.error.URLError,
                    ValueError,
                    json.JSONDecodeError,
                ) as e:
                    LOG.warning("LLM judge fallback to deterministic: %s", e)
                    llm_failures += 1
                    llm_last_error = str(e)
                    score = det_score
                    leaf_item["method"] = "deterministic_static_signals_v1_fallback"
            else:
                score = det_score
                leaf_item["method"] = "deterministic_static_signals_v1"
            leaf_item["leaf_score"] = score
            leaf_item["leaf_stdev"] = 0.0
            leaf_children.append(leaf_item)
            mod_sum += score * leaf_loc
            mod_w += leaf_loc
        mod_score = (mod_sum / mod_w) if mod_w else 0.0
        rubric_children.append(
            {
                "id": f"R.mod{mod_idx}",
                "title": f"模块 `{mod_title}`",
                "weight": mod_weight,
                "children": leaf_children,
                "aggregated_score": mod_score,
                "aggregated_stdev": 0.0,
            }
        )
        weighted_sum += mod_score * mod_weight
        total_weight += mod_weight

    root_score = (weighted_sum / total_weight) if total_weight else 0.0
    methodology = "llm_judge_single_model_v1" if use_llm else "deterministic_static_rubric_v1"
    out = {
        "$schema": "https://example.local/schemas/java-historical-analysis/rubric-eval-1.json",
        "schema_version": "1.0",
        "manifest_ref": "1.1-analysis_manifest.json",
        "methodology": methodology,
        "note": "Auto-generated rubric; LLM judge enabled when model/base_url/api_key are provided.",
        "rubric_root": {
            "id": "R",
            "title": f"{project_name} 理解度 rubric（自动生成）",
            "weight": 1.0,
            "children": rubric_children,
            "aggregated_score": root_score,
            "aggregated_stdev": 0.0,
            "formula_ref": "weighted average by leaf LOC then module LOC",
        },
        "_source": "java-code-wiki.build_rubric_eval",
    }
    if use_llm:
        out["judge"] = {
            "model": judge_model,
            "base_url": judge_base_url,
            "fallback_to_deterministic": True,
            "fallback_count": llm_failures,
            "llm_used_count": llm_used,
            "max_llm_leaves": judge_max_leaves,
        }
        if llm_last_error:
            out["judge"]["last_error"] = llm_last_error
    return out


def write_rubric_eval(
    output_dir: Path,
    module_tree_json: dict[str, Any],
    rest_map_json: dict[str, Any],
    *,
    project_name: str,
    judge_model: str | None = None,
    judge_base_url: str | None = None,
    judge_api_key: str | None = None,
    judge_timeout_sec: float = 90.0,
    judge_max_leaves: int | None = None,
) -> str:
    """Write rubric eval artifact and return relative path."""
    payload = build_rubric_eval(
        module_tree_json,
        rest_map_json,
        project_name=project_name,
        judge_model=judge_model,
        judge_base_url=judge_base_url,
        judge_api_key=judge_api_key,
        judge_timeout_sec=judge_timeout_sec,
        judge_max_leaves=judge_max_leaves,
    )
    out = output_dir / "reports" / "2.2-rubric_eval.sample.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(out.relative_to(output_dir))

