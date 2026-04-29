"""
CLI for code-wiki-demo (Click), inspired by CodeWiki's cli/main group layout.

Entry points: ``demo`` and ``java-code-wiki`` (same implementation).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import click

from demo import __version__
from demo.core.codewiki_bridge import run_codewiki_passthrough
from demo.core.pipeline import run_static_scan

LOG = logging.getLogger(__name__)


def _setup_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


@click.group()
@click.version_option(version=__version__, prog_name="demo")
def main() -> None:
    """Java repository analysis (jdtls-lsp-py backend; CodeWiki-style phases)."""


@main.command("analyze")
@click.argument("project", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "-o",
    "--output",
    "output_dir",
    type=click.Path(path_type=Path),
    default="./java-code-wiki-out",
    help="Output directory for JSON/Markdown artifacts.",
)
@click.option(
    "--max-symbol-files",
    default=500,
    type=int,
    show_default=True,
    help="Cap for symbols-by-package scan (jdtls batch_symbols_by_package).",
)
@click.option(
    "--max-rest-files",
    default=4000,
    type=int,
    show_default=True,
    help="Max .java files for REST map heuristic scan.",
)
@click.option(
    "--rubric-judge-model",
    default=None,
    help="Optional LLM judge model for 2.2 rubric eval (e.g. GLM-5).",
)
@click.option(
    "--rubric-judge-base-url",
    default=None,
    help="Optional OpenAI-compatible base URL for rubric judge.",
)
@click.option(
    "--rubric-judge-api-key",
    default=None,
    help="Optional API key for rubric judge (or env RUBRIC_JUDGE_API_KEY).",
)
@click.option(
    "--rubric-judge-timeout-sec",
    default=90.0,
    type=float,
    show_default=True,
    help="Per-request timeout (seconds) for rubric LLM judge.",
)
@click.option(
    "--rubric-judge-max-leaves",
    default=None,
    type=int,
    help="Optional cap: only first N leaves use LLM judge; others stay deterministic.",
)
@click.option(
    "--dynamic-max-depth",
    default=3,
    show_default=True,
    type=int,
    help="Max delegation depth for dynamic module-tree evolution.",
)
@click.option(
    "--dynamic-max-leaf-types",
    default=8,
    show_default=True,
    type=int,
    help="Type-count threshold before delegating a leaf into sub-leaves.",
)
@click.option(
    "--dynamic-max-leaf-loc",
    default=1800,
    show_default=True,
    type=int,
    help="LOC threshold before delegating a leaf into sub-leaves.",
)
@click.option(
    "--dynamic-use-llm-synthesis",
    is_flag=True,
    default=False,
    help="Use LLM to synthesize 2.3 parent docs and 0.1 repository overview.",
)
@click.option(
    "--dynamic-llm-parent-timeout-sec",
    default=None,
    type=float,
    help="Optional timeout override (seconds) for parent-module (2.3) LLM synthesis.",
)
@click.option(
    "--dynamic-llm-synth-retry-times",
    default=1,
    show_default=True,
    type=int,
    help="Retry times for LLM synthesis calls (parent and overview).",
)
@click.option(
    "--log-level",
    default="INFO",
    show_default=True,
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    help="Log verbosity for analysis progress and LLM diagnostics.",
)
def analyze_command(
    project: Path,
    output_dir: Path,
    max_symbol_files: int,
    max_rest_files: int,
    rubric_judge_model: str | None,
    rubric_judge_base_url: str | None,
    rubric_judge_api_key: str | None,
    rubric_judge_timeout_sec: float,
    rubric_judge_max_leaves: int | None,
    dynamic_max_depth: int,
    dynamic_max_leaf_types: int,
    dynamic_max_leaf_loc: int,
    dynamic_use_llm_synthesis: bool,
    dynamic_llm_parent_timeout_sec: float | None,
    dynamic_llm_synth_retry_times: int,
    log_level: str,
) -> None:
    """Run phase-1 static analysis (no JDTLS call-chain JVM)."""
    _setup_logging(log_level)
    LOG.info("Starting analysis project=%s output=%s", project, output_dir)
    try:
        judge_api_key = rubric_judge_api_key or os.getenv("RUBRIC_JUDGE_API_KEY")
        summary = run_static_scan(
            project,
            output_dir,
            max_symbol_files=max_symbol_files,
            max_rest_files=max_rest_files,
            rubric_judge_model=rubric_judge_model,
            rubric_judge_base_url=rubric_judge_base_url,
            rubric_judge_api_key=judge_api_key,
            rubric_judge_timeout_sec=rubric_judge_timeout_sec,
            rubric_judge_max_leaves=rubric_judge_max_leaves,
            dynamic_max_depth=dynamic_max_depth,
            dynamic_max_leaf_types=dynamic_max_leaf_types,
            dynamic_max_leaf_loc=dynamic_max_leaf_loc,
            dynamic_use_llm_synthesis=dynamic_use_llm_synthesis,
            dynamic_llm_parent_timeout_sec=dynamic_llm_parent_timeout_sec,
            dynamic_llm_synth_retry_times=dynamic_llm_synth_retry_times,
        )
    except ImportError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    LOG.info("Analysis completed; artifacts=%d", len(summary.get("artifacts", [])))
    click.echo(json.dumps(summary, ensure_ascii=False, indent=2))


@main.command("codewiki")
@click.argument("codewiki_args", nargs=-1, type=str)
def codewiki_command(codewiki_args: tuple[str, ...]) -> None:
    """
    Run full native CodeWiki from ./CodeWiki (generate/config/mcp/...).

    Examples:
      demo codewiki generate
      java-code-wiki codewiki config show
      demo codewiki mcp
    """
    try:
        rc = run_codewiki_passthrough(list(codewiki_args))
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(2)
    except RuntimeError as e:
        click.echo(str(e), err=True)
        sys.exit(2)
    if rc != 0:
        sys.exit(rc)


if __name__ == "__main__":
    main()
