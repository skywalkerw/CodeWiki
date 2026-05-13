# PROJECT KNOWLEDGE BASE

**Generated:** 2026-04-29
**Commit:** 9fb7a60
**Branch:** main

## OVERVIEW
CodeWiki is an AI-powered documentation generator for large codebases. Python 3.12+ CLI tool + FastAPI web app that parses 9 languages via Tree-sitter, builds dependency graphs, and uses LLM agents to generate holistic docs with Mermaid diagrams.

## STRUCTURE
```
CodeWiki/
├── codewiki/                # Main Python package
│   ├── cli/                 # Click CLI (config, generate, mcp commands)
│   ├── src/be/              # Backend: dependency analysis + agent orchestration → AGENTS.md
│   ├── src/fe/              # Frontend: FastAPI web app (routes, GitHub proc, viewer)
│   ├── mcp/                 # MCP server for IDE integration
│   └── templates/           # Jinja2 templates for GitHub Pages viewer
├── demo/                    # Separate subproject: Java historical analysis (own pyproject.toml)
├── docker/                  # Docker deployment (FastAPI on port 8000)
├── scripts/                 # Bootstrap, smoke test, export scripts
├── docs/                    # Academic paper, samples, architecture docs
├── pyproject.toml           # Build config, dependencies, tool settings
├── requirements.txt         # Full pinned dependency list
└── DEVELOPMENT.md           # Detailed architecture + contributing guide
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| CLI entry point | `codewiki/cli/main.py` | Click LazyGroup; commands lazy-loaded |
| Generate command | `codewiki/cli/commands/generate.py` | Main orchestrator; 580+ lines |
| Config management | `codewiki/cli/commands/config.py` + `config_manager.py` | Persists to `~/.codewiki/` |
| Web app entry | `codewiki/run_web_app.py` → `src/fe/web_app.py` | FastAPI on uvicorn |
| Dependency parser | `codewiki/src/be/dependency_analyzer/ast_parser.py` | Multi-language AST via Tree-sitter |
| Language analyzers | `codewiki/src/be/dependency_analyzer/analyzers/` | 9 languages: py, java, js, ts, c, cpp, csharp, kotlin, php |
| Agent orchestration | `codewiki/src/be/agent_orchestrator.py` | pydantic-ai recursive agents |
| Agent tools | `codewiki/src/be/agent_tools/` | read_code_components, str_replace_editor, deps, generate_sub_module |
| LLM integration | `codewiki/src/be/llm_services.py` | LiteLLM wrapper (OpenAI, Anthropic, Bedrock, Azure) |
| Prompt templates | `codewiki/src/be/prompt_template.py` | LLM prompt construction with CRITICAL constraints |
| Module clustering | `codewiki/src/be/cluster_modules.py` | Hierarchical decomposition |
| Doc generation engine | `codewiki/src/be/documentation_generator.py` | Core pipeline orchestrator |
| File security | `codewiki/src/be/dependency_analyzer/utils/security.py` | Symlink + path escape prevention |
| MCP server | `codewiki/mcp/server.py` | Model Context Protocol for IDE tools |
| Config dataclass | `codewiki/src/config.py` | Central Config class; CLI vs web context switching |
| CLI-to-backend adapter | `codewiki/cli/adapters/doc_generator.py` | Progress tracking, error wrapping |
| Default ignore patterns | `codewiki/src/be/dependency_analyzer/utils/patterns.py` | Comprehensive exclude list per language |
| Agent instructions model | `codewiki/cli/models/config.py` | AgentInstructions dataclass |
| GitHub pages viewer | `codewiki/src/fe/templates.py` | 679 lines of HTML generation |

## CODE MAP
| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `cli` | Function | `codewiki/__init__.py:11` | CLI entry point (Click group) |
| `main()` | Function | `codewiki/__main__.py:7` | Module entry (`python -m codewiki`) |
| `Config` | Class | `codewiki/src/config.py:47` | Central configuration dataclass |
| `generate_command` | Function | `codewiki/cli/commands/generate.py:176` | Main generation CLI handler |
| `DocumentationGenerator` | Class | `codewiki/src/be/documentation_generator.py` | Core pipeline orchestrator |
| `AgentOrchestrator` | Class | `codewiki/src/be/agent_orchestrator.py:60` | Recursive agent management |
| `DependencyParser` | Class | `codewiki/src/be/dependency_analyzer/ast_parser.py:18` | Multi-language repo parser |
| `AnalysisService` | Class | `codewiki/src/be/dependency_analyzer/analysis/analysis_service.py` | AST analysis service |
| `WebRoutes` | Class | `codewiki/src/fe/routes.py` | FastAPI route handlers |
| `WebAppConfig` | Class | `codewiki/src/fe/config.py` | Web app configuration |
| `AgentInstructions` | Class | `codewiki/cli/models/config.py` | Agent customization model |
| `CLIDocumentationGenerator` | Class | `codewiki/cli/adapters/doc_generator.py` | CLI-to-backend adapter |

## CONVENTIONS
- **Python 3.12+** required; type hints used but not strictly enforced (`disallow_untyped_defs = false`)
- **Line length 100** (black + ruff both set to 100, not default 88)
- **Naming**: `snake_case` functions/variables, `PascalCase` classes
- **Docstrings**: Google-style on public functions/classes
- **Dataclasses** preferred for data models (Config, AgentInstructions, etc.)
- **Lazy imports** in CLI (LazyGroup pattern) for subcommand performance
- **Logging**: `logging.getLogger(__name__)` throughout
- **Test naming**: files `test_*.py`, classes `Test*`, functions `test_*` (pytest configured, no tests exist yet)
- **Agent tools**: Tools registered per-module in `AgentOrchestrator.create_agent()`
- **Dual config system**: CLI config (`~/.codewiki/config.json` + keyring) vs backend Config dataclass
- **Topological processing**: Docs generated leaf-first, then parents assembled

## ANTI-PATTERNS (THIS PROJECT)
- **NEVER** allow symlinks in file processing — `security.py` blocks all symlinks
- **NEVER** allow path escapes beyond repo base — `assert_safe_path()` enforced
- **DO NOT** validate mermaid diagrams in parallel — causes segfaults
- **DO NOT** omit `<OVERVIEW>` / `</OVERVIEW>` tags in LLM responses — format validation enforced
- **DO NOT** shorten component IDs in JSON — must copy full `path/to/File.java::ClassName` strings
- **DO NOT** load incomplete jobs from disk — only completed jobs per `background_worker.py`
- **ALWAYS** use `safe_open_text()` when reading files from repos
- API keys must be masked in display (first + last 4 chars)
- Debug logs: set `CODEWIKI_LOG_LEVEL=DEBUG` or `--verbose`
- LLM traces: set `CODEWIKI_LLM_TRACE=1` (writes under `output_dir/trace/`)
- Token estimation must be conservative to avoid context-limit overflow

## UNIQUE STYLES
- **LazyGroup pattern**: CLI subcommands loaded on first use, not at import time
- **Context switching**: `set_cli_context()` / `is_cli_context()` for CLI vs web mode
- **AgentInstructions pipeline**: CLI args → AgentInstructions dataclass → Config dict → prompt injection
- **Fallback model chain**: main → cluster → fallback for LLM call resilience
- **Module naming**: `codewiki` package uses `src/be/` and `src/fe/` sub-packages (unusual nested src)
- **Exclude patterns merge**: CLI `--exclude` merges with defaults; `--include` replaces defaults

## COMMANDS
```bash
# Install (dev)
pip install -e .
pip install -r requirements.txt

# CLI usage
codewiki --version
codewiki config set --api-key KEY --base-url URL --main-model MODEL
codewiki config show
codewiki config validate
codewiki generate                     # basic generation
codewiki generate --update            # incremental (changed modules only)
codewiki generate --github-pages --create-branch
codewiki generate --verbose
codewiki generate --doc-type api --focus "src/core,src/api"
codewiki mcp                          # start MCP IDE server

# Docker
docker-compose -f docker/docker-compose.yml up -d

# Testing
pytest
pytest --cov=codewiki tests/

# Linting / formatting
black codewiki/
ruff check codewiki/
mypy codewiki/

# Dev scripts
./scripts/bootstrap_codewiki.sh       # install editable + deps
./scripts/check_requirements.sh       # validate deps without installing
```

## NOTES
- **No tests implemented yet** — pytest configured but `tests/` directory is empty/missing
- **No CI/CD** — no `.github/workflows/` configured
- **Keyring dependency**: API keys stored in system keychain; set `CODEWIKI_NO_KEYRING=1` for file-based
- **Node.js required** at runtime for Mermaid diagram validation (not just dev)
- **Demo subproject** in `demo/` is a separate Python package for Java historical analysis experiments — has own `pyproject.toml`, does not affect main package
- **Large files**: 13 files >500 lines; biggest are `analyzers/typescript.py` (980), `cli/commands/config.py` (830), `agent_tools/str_replace_editor.py` (789)
- **Output structure**: `docs/` contains overview.md, per-module .md files, module_tree.json, metadata.json
