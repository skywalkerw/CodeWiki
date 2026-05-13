# Backend — Agent Orchestration & Dependency Analysis

## OVERVIEW
Core documentation generation engine: AST-parses 9 languages into dependency graphs, clusters modules hierarchically, then dispatches LLM agents (pydantic-ai) to generate docs leaf-first with topological assembly.

## STRUCTURE
```
be/
├── main.py                    # Standalone backend entry (argparse)
├── documentation_generator.py # Core pipeline: parse → cluster → generate → assemble
├── agent_orchestrator.py      # pydantic-ai Agent creation + module processing
├── agent_tools/               # Callable tools registered per agent
│   ├── read_code_components.py        # Code reading for agents
│   ├── str_replace_editor.py          # Doc editing (789 lines)
│   ├── deps.py                        # Dependency traversal
│   └── generate_sub_module_documentations.py
├── cluster_modules.py         # Hierarchical decomposition (dynamic programming)
├── llm_services.py            # LiteLLM wrapper (OpenAI, Anthropic, Bedrock, Azure)
├── prompt_template.py         # LLM prompt construction (CRITICAL format constraints)
├── utils.py                   # Token estimation, mermaid validation
├── dependency_analyzer/       # Multi-language AST parsing + graph building
│   ├── ast_parser.py          # DependencyParser: repo → components
│   ├── dependency_graphs_builder.py
│   ├── topo_sort.py           # Topological sort with cycle resolution fallback
│   ├── analyzers/             # 9 language-specific analyzers (all ~300-980 lines)
│   │   ├── python.py, java.py, javascript.py, typescript.py
│   │   ├── c.py, cpp.py, csharp.py, kotlin.py, php.py
│   ├── analysis/
│   │   ├── analysis_service.py       # AST analysis orchestrator
│   │   ├── call_graph_analyzer.py    # Call graph construction (619 lines)
│   │   ├── repo_analyzer.py          # Repository-level analysis
│   │   └── cloning.py               # Repository cloning utilities
│   ├── models/
│   │   ├── core.py                   # Node, module data models
│   │   └── analysis.py               # Analysis result models
│   └── utils/
│       ├── patterns.py               # Default ignore patterns per language (654 lines)
│       ├── security.py               # Symlink + path escape prevention
│       └── logging_config.py         # Logging utilities
└── component_id_resolve.py    # Component ID resolution
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Generate docs end-to-end | `documentation_generator.py` | `DocumentationGenerator.run()` pipeline |
| Create/manage LLM agents | `agent_orchestrator.py:68-95` | `create_agent()` registers tools per complexity |
| Process a single module | `agent_orchestrator.py:97-156` | `process_module()` handles leaf/parent logic |
| LLM API calls | `llm_services.py` | Provider routing, retry, trace context |
| Build system prompt | `prompt_template.py` | CRITICAL format tags: `<OVERVIEW>`, exact component IDs |
| Parse a repo into components | `dependency_analyzer/ast_parser.py:38` | `DependencyParser.parse_repository()` |
| Add a new language analyzer | `analyzers/` + register in `ast_parser.py` LANGUAGE_ANALYZERS | See DEVELOPMENT.md § Adding Support for New Languages |
| Cluster modules hierarchically | `cluster_modules.py` | Feature-oriented partitioning with token budget |
| File filtering (include/exclude) | `dependency_analyzer/utils/patterns.py` | Default ignore lists per language |
| Path security | `dependency_analyzer/utils/security.py` | `assert_safe_path()`, `safe_open_text()` |
| Topological ordering | `dependency_analyzer/topo_sort.py:165` | Falls back to any order on cycle detection |
| Agent tool registration | `agent_orchestrator.py:create_agent()` | Complex: 3 tools; Leaf: 2 tools; Base: configurable |
| LLM trace debugging | `llm_services.py` + `CODEWIKI_LLM_TRACE=1` | Writes prompt/response under `output_dir/trace/` |

## CONVENTIONS
- **Tools registered per agent**: Not global — `create_agent()` assembles tool list per module complexity
- **Leaf-first generation**: Modules processed in dependency order; parent docs assembled from children
- **Token estimation**: Conservative estimates to avoid context overflow — see `utils.py`
- **Mermaid validation**: Sequential only — parallel causes native segfaults
- **Component IDs**: Full `path/to/File.java::ClassName` format — never shorten in LLM payloads
- **Fallback chain**: main_model → cluster_model → fallback_model for LLM resilience
- **Retry on overview**: `_OVERVIEW_MAX_ATTEMPTS` retry loop for format-valid overview docs

## ANTI-PATTERNS
- Agent tools must maintain deterministic behavior — avoid side effects in tool implementations
- Mermaid validation runs sequentially — `utils.py`; parallel causes segfaults
