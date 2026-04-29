"""
Core analysis: delegate to jdtls_lsp (reverse_design + entry_scan).

No LLM. Static scan uses scan_modules, batch_symbols_by_package, entrypoints, rest_map.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from demo.core.dynamic_docs import run_dynamic_documentation_loop
from demo.core.graph import build_graph
from demo.core.module_tree import build_module_tree
from demo.core.rubric_eval import write_rubric_eval
from demo.models.manifest import (
    AnalysisManifest,
    AnalysisInfo,
    BuildInfo,
    ProjectInfo,
    SnapshotInfo,
    utc_now_iso,
)
from demo.utils.git import try_git_head

LOG = logging.getLogger(__name__)


def _require_jdtls_lsp():
    try:
        from jdtls_lsp.reverse_design import batch_symbols_by_package, scan_modules
        from jdtls_lsp.entry_scan import scan_java_entrypoints, scan_rest_map
    except ImportError as e:
        raise ImportError(
            "Missing dependency jdtls_lsp. Install with:\n"
            "  pip install -e /path/to/code-wiki/external/jdtls-lsp-py\n"
            "then: pip install -e /path/to/code-wiki/demo"
        ) from e
    return scan_modules, batch_symbols_by_package, scan_java_entrypoints, scan_rest_map


def run_static_scan(
    project_root: Path,
    output_dir: Path,
    *,
    max_symbol_files: int = 500,
    max_rest_files: int = 4_000,
    glob_pattern: str = "**/src/main/java/**/*.java",
    rubric_judge_model: str | None = None,
    rubric_judge_base_url: str | None = None,
    rubric_judge_api_key: str | None = None,
    rubric_judge_timeout_sec: float = 90.0,
    rubric_judge_max_leaves: int | None = None,
    dynamic_max_depth: int = 3,
    dynamic_max_leaf_types: int = 8,
    dynamic_max_leaf_loc: int = 1800,
    dynamic_use_llm_synthesis: bool = False,
    dynamic_llm_parent_timeout_sec: float | None = None,
    dynamic_llm_synth_retry_times: int = 1,
) -> dict[str, Any]:
    """
    Phase-1: modules + symbols-by-package + entrypoints + rest-map (no JDTLS callchains).

    Writes under ``output_dir`` (numbered names aligned to ``docs/samples``):
      - 1.1-analysis_manifest.json
      - data/1.2-graph.json
      - data/1.2-modules.json, data/1.2-symbols-by-package.json
      - data/1.3-module_tree.json
      - data/1.4-entrypoints.json
      - data/1.5-rest-map.json
      - graphs/1.5-rest-map.mmd (if rest map yields endpoints)
      - reports/2.1-leaf_*.md (dynamic terminal leaf reports)
      - reports/2.3-parent_*.md (bottom-up parent synthesis docs)
      - 0.1-REPOSITORY_OVERVIEW.md (repository-level overview)
      - reports/2.2-rubric_eval.sample.json (deterministic static rubric)

    """
    scan_modules, batch_symbols_by_package, scan_java_entrypoints, scan_rest_map = _require_jdtls_lsp()

    project_root = project_root.resolve()
    output_dir = output_dir.resolve()
    LOG.info("Preparing directories under output=%s", output_dir)
    data_dir = output_dir / "data"
    graphs_dir = output_dir / "graphs"
    data_dir.mkdir(parents=True, exist_ok=True)
    graphs_dir.mkdir(parents=True, exist_ok=True)
    # Clean legacy unnumbered artifacts from older runs.
    for legacy in (
        data_dir / "modules.json",
        data_dir / "symbols-by-package.json",
        data_dir / "entrypoints.json",
        data_dir / "rest-map.json",
        graphs_dir / "rest-map.mmd",
    ):
        legacy.unlink(missing_ok=True)

    commit, branch = try_git_head(project_root)
    LOG.info("Building manifest for project=%s commit=%s", project_root.name, commit or "unknown")
    manifest = AnalysisManifest(
        project=ProjectInfo(
            name=project_root.name,
            description="java-code-wiki static scan",
        ),
        snapshot=SnapshotInfo(
            commit_sha=commit or "unknown",
            branch=branch,
        ),
        build=BuildInfo(tool="maven_or_gradle"),
        analysis=AnalysisInfo(
            run_id=f"run-{uuid.uuid4().hex[:12]}",
            generated_at=utc_now_iso(),
            engine="jdtls-lsp-py@static_scan",
            notes=["Phase-1 only; no JDTLS JVM for call hierarchy in this command."],
        ),
    )

    LOG.info("Scanning modules ...")
    modules_payload = scan_modules(project_root)
    modules_path = data_dir / "1.2-modules.json"
    modules_path.write_text(
        json.dumps(modules_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Infer artifact_id from first module meta if present
    mods = modules_payload.get("modules") or []
    if mods and isinstance(mods[0], dict) and mods[0].get("artifactId"):
        manifest.project.artifact_id = str(mods[0].get("artifactId", ""))

    LOG.info("Scanning symbols by package (max_files=%s) ...", max_symbol_files)
    symbols_payload = batch_symbols_by_package(
        str(project_root),
        glob_pattern=glob_pattern,
        max_files=max_symbol_files,
    )
    symbols_path = data_dir / "1.2-symbols-by-package.json"
    symbols_path.write_text(
        json.dumps(symbols_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    LOG.info("Scanning entrypoints ...")
    entry_hits = scan_java_entrypoints(project_root)
    entry_payload = {
        "projectRoot": str(project_root),
        "entryCount": len(entry_hits),
        "entries": entry_hits,
    }
    entrypoints_path = data_dir / "1.4-entrypoints.json"
    entrypoints_path.write_text(
        json.dumps(entry_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    LOG.info("Scanning REST map (max_files=%s) ...", max_rest_files)
    rest_payload = scan_rest_map(project_root, max_files=max_rest_files)
    rest_map_path = data_dir / "1.5-rest-map.json"
    rest_map_path.write_text(
        json.dumps(rest_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Optional tiny mermaid (same idea as jdtls bundle helper: simple LR chart)
    endpoints = rest_payload.get("endpoints") if isinstance(rest_payload, dict) else None
    if isinstance(endpoints, list) and endpoints:
        lines = ["flowchart LR", "  classDef ep fill:#e8f4fc,stroke:#0366d6"]
        for i, ep in enumerate(endpoints[:48]):
            if not isinstance(ep, dict):
                continue
            hm = str(ep.get("httpMethod", "?"))
            p = str(ep.get("path", ""))[:56].replace('"', "'")
            label = f"{hm} {p}".strip() or hm
            lines.append(f'  e{i}["{label}"]:::ep')
        lines.append("")
        rest_map_mmd = graphs_dir / "1.5-rest-map.mmd"
        rest_map_mmd.write_text("\n".join(lines), encoding="utf-8")

    graph_payload = build_graph(modules_payload, symbols_payload, rest_payload, project_root=project_root)
    LOG.info(
        "Built graph nodes=%s edges=%s",
        graph_payload.get("stats", {}).get("node_count"),
        graph_payload.get("stats", {}).get("edge_count"),
    )
    graph_path = data_dir / "1.2-graph.json"
    graph_path.write_text(
        json.dumps(graph_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    tree_payload = build_module_tree(modules_payload, symbols_payload, project_root=project_root)
    dynamic_out = run_dynamic_documentation_loop(
        output_dir,
        tree_payload,
        rest_payload,
        max_depth=dynamic_max_depth,
        max_leaf_types=dynamic_max_leaf_types,
        max_leaf_loc=dynamic_max_leaf_loc,
        use_llm_synthesis=dynamic_use_llm_synthesis,
        llm_model=rubric_judge_model,
        llm_base_url=rubric_judge_base_url,
        llm_api_key=rubric_judge_api_key,
        llm_timeout_sec=rubric_judge_timeout_sec,
        llm_parent_timeout_sec=dynamic_llm_parent_timeout_sec,
        llm_synth_retry_times=dynamic_llm_synth_retry_times,
    )
    tree_payload = dynamic_out["module_tree"]
    (data_dir / "1.3-module_tree.json").write_text(
        json.dumps(tree_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    leaf_reports = dynamic_out.get("leaf_docs") or []
    parent_reports = dynamic_out.get("parent_docs") or []
    overview_doc = dynamic_out.get("overview_doc")
    LOG.info(
        "Dynamic loop done delegations=%s leaf_docs=%s parent_docs=%s",
        dynamic_out.get("delegations"),
        len(leaf_reports),
        len(parent_reports),
    )
    LOG.info("Generated leaf reports count=%d", len(leaf_reports))
    rubric_report = write_rubric_eval(
        output_dir,
        tree_payload,
        rest_payload,
        project_name=project_root.name,
        judge_model=rubric_judge_model,
        judge_base_url=rubric_judge_base_url,
        judge_api_key=rubric_judge_api_key,
        judge_timeout_sec=rubric_judge_timeout_sec,
        judge_max_leaves=rubric_judge_max_leaves,
    )

    manifest_path = output_dir / "1.1-analysis_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary: dict[str, Any] = {
        "projectRoot": str(project_root),
        "outputDir": str(output_dir),
        "artifacts": [
            str(manifest_path.relative_to(output_dir)),
            str(graph_path.relative_to(output_dir)),
            str(modules_path.relative_to(output_dir)),
            str(symbols_path.relative_to(output_dir)),
            "data/1.3-module_tree.json",
            str(entrypoints_path.relative_to(output_dir)),
            str(rest_map_path.relative_to(output_dir)),
        ],
        "counts": {
            "modules": len(modules_payload.get("modules") or []),
            "module_tree_packages": tree_payload.get("root", {})
            .get("metrics", {})
            .get("package_count"),
            "entrypoints": entry_payload.get("entryCount"),
            "restEndpoints": len(endpoints) if isinstance(endpoints, list) else 0,
            "graphNodes": graph_payload.get("stats", {}).get("node_count"),
            "graphEdges": graph_payload.get("stats", {}).get("edge_count"),
            "leafReports": len(leaf_reports),
            "dynamicDelegations": dynamic_out.get("delegations", 0),
        },
    }
    if (graphs_dir / "1.5-rest-map.mmd").exists():
        summary["artifacts"].append(str(Path("graphs/1.5-rest-map.mmd")))
    summary["artifacts"].extend(leaf_reports)
    summary["artifacts"].extend(parent_reports)
    if isinstance(overview_doc, str):
        summary["artifacts"].append(overview_doc)
    summary["artifacts"].append(rubric_report)

    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary["summaryFile"] = str(summary_path.name)
    LOG.info("Wrote summary file=%s", summary_path)
    return summary
