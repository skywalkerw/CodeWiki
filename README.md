<h1 align="center">CodeWiki: Evaluating AI's Ability to Generate Holistic Documentation for Large-Scale Codebases</h1>

<p align="center">
  <strong>AI-Powered Repository Documentation Generation</strong> • <strong>Multi-Language Support</strong> • <strong>Architecture-Aware Analysis</strong>
</p>

<p align="center">
  Generate holistic, structured documentation for large-scale codebases • Cross-module interactions • Visual artifacts and diagrams
</p>

<p align="center">
  <a href="https://python.org/"><img alt="Python version" src="https://img.shields.io/badge/python-3.12+-blue?style=flat-square" /></a>
  <a href="./LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-green.svg?style=flat-square" /></a>
  <a href="https://github.com/FSoft-AI4Code/CodeWiki/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/FSoft-AI4Code/CodeWiki?style=flat-square" /></a>
  <a href="https://arxiv.org/abs/2510.24428"><img alt="arXiv" src="https://img.shields.io/badge/arXiv-2510.24428-b31b1b?style=flat-square" /></a>
</p>

<p align="center">
  <a href="#quick-start"><strong>Quick Start</strong></a> •
  <a href="#cli-commands"><strong>CLI Commands</strong></a> •
  <a href="#documentation-output"><strong>Output Structure</strong></a> •
  <a href="https://arxiv.org/abs/2510.24428"><strong>Paper</strong></a>
</p>

<p align="center">
  <img src="./img/framework-overview.png" alt="CodeWiki Framework" width="600" style="border: 2px solid #e1e4e8; border-radius: 12px; padding: 20px;"/>
</p>

---

## Quick Start

### 1. Install CodeWiki

```bash
# Install from source
pip install git+https://github.com/FSoft-AI4Code/CodeWiki.git

# Verify installation
codewiki --version
```

### 2. Configure Your Environment

CodeWiki supports multiple LLM providers: **OpenAI-compatible**, **Anthropic**, **AWS Bedrock**, and **Azure OpenAI**.

```bash
# Anthropic
codewiki config set \
  --api-key YOUR_API_KEY \
  --base-url https://api.anthropic.com \
  --main-model claude-sonnet-4 \
  --cluster-model claude-sonnet-4 \
  --fallback-model glm-4p5

# Azure OpenAI
codewiki config set \
  --provider azure-openai \
  --api-key YOUR_AZURE_KEY \
  --base-url https://YOUR_RESOURCE.openai.azure.com \
  --azure-deployment YOUR_DEPLOYMENT \
  --main-model gpt-4o \
  --cluster-model gpt-4o

# AWS Bedrock
codewiki config set \
  --provider bedrock \
  --aws-region us-east-1 \
  --main-model anthropic.claude-sonnet-4-v2:0 \
  --cluster-model anthropic.claude-sonnet-4-v2:0
```

### 3. Generate Documentation

```bash
# Navigate to your project
cd /path/to/your/project

# Generate documentation
codewiki generate

# Generate with HTML viewer for GitHub Pages
codewiki generate --github-pages --create-branch
```

**That's it!** Your documentation will be generated in `./docs/` with comprehensive repository-level analysis.

### Usage Example

![CLI Usage Example](https://github.com/FSoft-AI4Code/CodeWiki/releases/download/assets/cli-usage-example.gif)

---

## What is CodeWiki?

CodeWiki is an open-source framework for **automated repository-level documentation** across eight programming languages. It generates holistic, architecture-aware documentation that captures not only individual functions but also their cross-file, cross-module, and system-level interactions.

### Key Innovations

| Innovation | Description | Impact |
|------------|-------------|--------|
| **Hierarchical Decomposition** | Dynamic programming-inspired strategy that preserves architectural context | Handles codebases of arbitrary size (86K-1.4M LOC tested) |
| **Recursive Agentic System** | Adaptive multi-agent processing with dynamic delegation capabilities | Maintains quality while scaling to repository-level scope |
| **Multi-Modal Synthesis** | Generates textual documentation, architecture diagrams, data flows, and sequence diagrams | Comprehensive understanding from multiple perspectives |

### Supported Languages

**🐍 Python** • **☕ Java** • **🟨 JavaScript** • **🔷 TypeScript** • **⚙️ C** • **🔧 C++** • **🪟 C#** • **🎯 Kotlin**

---

## CLI Commands

### Configuration Management

```bash
# Set up your API configuration
codewiki config set \
  --api-key <your-api-key> \
  --base-url <provider-url> \
  --main-model <model-name> \
  --cluster-model <model-name> \
  --fallback-model <model-name>

# Configure max token settings
codewiki config set --max-tokens 32768 --max-token-per-module 36369 --max-token-per-leaf-module 16000

# Configure max depth for hierarchical decomposition
codewiki config set --max-depth 3

# Show current configuration
codewiki config show

# Validate your configuration
codewiki config validate
```

### Documentation Generation

```bash
# Basic generation
codewiki generate

# Custom output directory
codewiki generate --output ./documentation

# Create git branch for documentation
codewiki generate --create-branch

# Generate HTML viewer for GitHub Pages
codewiki generate --github-pages

# Enable verbose logging
codewiki generate --verbose

# Full-featured generation
codewiki generate --create-branch --github-pages --verbose

# Incremental update (only regenerate changed modules since last run)
codewiki generate --update
```

### Customization Options

CodeWiki supports customization for language-specific projects and documentation styles:

```bash
# C# project: only analyze .cs files, exclude test directories
codewiki generate --include "*.cs" --exclude "Tests,Specs,*.test.cs"

# Focus on specific modules with architecture-style docs
codewiki generate --focus "src/core,src/api" --doc-type architecture

# Add custom instructions for the AI agent
codewiki generate --instructions "Focus on public APIs and include usage examples"
```

#### Pattern Behavior (Important!)

- **`--include`**: When specified, **ONLY** these patterns are used (replaces defaults completely)
  - Example: `--include "*.cs"` will analyze ONLY `.cs` files
  - If omitted, all supported file types are analyzed
  - Supports glob patterns: `*.py`, `src/**/*.ts`, `*.{js,jsx}`
  
- **`--exclude`**: When specified, patterns are **MERGED** with default ignore patterns
  - Example: `--exclude "Tests,Specs"` will exclude these directories AND still exclude `.git`, `__pycache__`, `node_modules`, etc.
  - Default patterns include: `.git`, `node_modules`, `__pycache__`, `*.pyc`, `bin/`, `dist/`, and many more
  - Supports multiple formats:
    - Exact names: `Tests`, `.env`, `config.local`
    - Glob patterns: `*.test.js`, `*_test.py`, `*.min.*`
    - Directory patterns: `build/`, `dist/`, `coverage/`

#### Setting Persistent Defaults

Save your preferred settings as defaults:

```bash
# Set include patterns for C# projects
codewiki config agent --include "*.cs"

# Exclude test projects by default (merged with default excludes)
codewiki config agent --exclude "Tests,Specs,*.test.cs"

# Set focus modules
codewiki config agent --focus "src/core,src/api"

# Set default documentation type
codewiki config agent --doc-type architecture

# View current agent settings
codewiki config agent

# Clear all agent settings
codewiki config agent --clear
```

| Option | Description | Behavior | Example |
|--------|-------------|----------|---------|
| `--include` | File patterns to include | **Replaces** defaults | `*.cs`, `*.py`, `src/**/*.ts` |
| `--exclude` | Patterns to exclude | **Merges** with defaults | `Tests,Specs`, `*.test.js`, `build/` |
| `--focus` | Modules to document in detail | Standalone option | `src/core,src/api` |
| `--doc-type` | Documentation style | Standalone option | `api`, `architecture`, `user-guide`, `developer` |
| `--instructions` | Custom agent instructions | Standalone option | Free-form text |

### Token Settings & Context Window

CodeWiki allows you to configure token limits for LLM calls. **Starting from v1.0.2, context window is auto-detected** from the model name (supports 60+ models including Claude, GPT, DeepSeek, Gemini, Qwen, GLM, Mistral).

```bash
# Set max tokens for LLM responses (default: 32768)
codewiki config set --max-tokens 16384

# Set max tokens for module clustering (default: 36369, auto-scales with context window)
codewiki config set --max-token-per-module 40000

# Set max tokens for leaf modules (default: 16000, auto-scales with context window)
codewiki config set --max-token-per-leaf-module 20000

# Override auto-detected context window (rarely needed)
# codewiki config set --model-context-window 128000

# Set max depth for hierarchical decomposition (default: 2)
codewiki config set --max-depth 3

# Override at runtime for a single generation
codewiki generate --max-tokens 16384 --max-token-per-module 40000 --max-depth 3
```

#### How Token Thresholds Work

```
model_context_window (1M for DeepSeek v4, 200K for Claude, auto-detected)
│
├─ clustering budget = context_window - max_tokens - 64
│
├─ effective_max_token_per_module = context_window × 0.55  ← 触发聚类阈值
│   自动缩放: 显式设置时使用用户值，否则从 context_window 计算
│
└─ effective_max_token_per_leaf_module = context_window × 0.24  ← 叶子递归阈值
    自动缩放: 同上
```

| Parameter | Role | Default | Auto-scale |
|-----------|------|---------|------------|
| `--max-tokens` | LLM 单次响应输出上限 | 32768 | No |
| `--max-token-per-module` | 模块总 token 超此值触发聚类分层 | 36369 | **Yes** (×0.55) |
| `--max-token-per-leaf-module` | 叶子模块 token 超此值触发递归委派 | 16000 | **Yes** (×0.24) |
| `--max-depth` | 最大层次分解深度 | 2 | No |

**用户显式设置的值始终优先**，不会被自动缩放覆盖。

#### Auto-Detected Model Support

| Model Family | Detected Window |
|-------------|-----------------|
| Claude 3 / 4 (Sonnet, Opus, Haiku) | 200K |
| GPT-4o / GPT-4-Turbo | 128K |
| GPT-3.5 | 16K |
| o1 / o3 / o4-mini | 200K |
| DeepSeek v4 / v4-pro | 1M |
| DeepSeek v3 / R1 | 128K |
| Gemini 1.5 Pro | 2M |
| GLM-4 / GLM-5 | 128K |
| Qwen 2.5 | 32K |
| Llama 3 | 128K |
| Mistral Large | 128K |

> **Note**: Run `codewiki config validate` to see the auto-detected context window for your model.

### Configuration Storage

- **API keys**: Securely stored in system keychain (macOS Keychain, Windows Credential Manager, Linux Secret Service). Falls back to `~/.codewiki/credentials.json` in headless/container environments. Set `CODEWIKI_NO_KEYRING=1` to force file-based storage.
- **Settings & Agent Instructions**: `~/.codewiki/config.json`

---

## Documentation Output

Generated documentation includes both **textual descriptions** and **visual artifacts** for comprehensive understanding.

### Textual Documentation
- Repository overview with architecture guide
- Module-level documentation with API references
- Usage examples and implementation patterns
- Cross-module interaction analysis

### Visual Artifacts
- System architecture diagrams (Mermaid)
- Data flow visualizations
- Dependency graphs and module relationships
- Sequence diagrams for complex interactions

### Output Structure

```
./docs/
├── overview.md              # Repository overview (start here!)
├── module1.md               # Module documentation
├── module2.md               # Additional modules...
├── module_tree.json         # Hierarchical module structure
├── first_module_tree.json   # Initial clustering result
├── metadata.json            # Generation metadata
└── index.html               # Interactive viewer (with --github-pages)
```

---

## Experimental Results

CodeWiki has been evaluated on **CodeWikiBench**, the first benchmark specifically designed for repository-level documentation quality assessment.

### Performance by Language Category

| Language Category | CodeWiki (Sonnet-4) | DeepWiki | Improvement |
|-------------------|---------------------|----------|-------------|
| High-Level (Python, JS, TS) | **79.14%** | 68.67% | **+10.47%** |
| Managed (C#, Java) | **68.84%** | 64.80% | **+4.04%** |
| Systems (C, C++) | 53.24% | 56.39% | -3.15% |
| **Overall Average** | **68.79%** | **64.06%** | **+4.73%** |

### Results on Representative Repositories

| Repository | Language | LOC | CodeWiki-Sonnet-4 | DeepWiki | Improvement |
|------------|----------|-----|-------------------|----------|-------------|
| All-Hands-AI--OpenHands | Python | 229K | **82.45%** | 73.04% | **+9.41%** |
| puppeteer--puppeteer | TypeScript | 136K | **83.00%** | 64.46% | **+18.54%** |
| sveltejs--svelte | JavaScript | 125K | **71.96%** | 68.51% | **+3.45%** |
| Unity-Technologies--ml-agents | C# | 86K | **79.78%** | 74.80% | **+4.98%** |
| elastic--logstash | Java | 117K | **57.90%** | 54.80% | **+3.10%** |

**View comprehensive results:** See [paper](https://arxiv.org/abs/2510.24428) for complete evaluation on 21 repositories spanning all supported languages.

---

## How It Works

### Architecture Overview

CodeWiki employs a three-stage process for comprehensive documentation generation:

1. **Hierarchical Decomposition**: Uses dynamic programming-inspired algorithms to partition repositories into coherent modules while preserving architectural context across multiple granularity levels.

2. **Recursive Multi-Agent Processing**: Implements adaptive multi-agent processing with dynamic task delegation, allowing the system to handle complex modules at scale while maintaining quality.

3. **Multi-Modal Synthesis**: Integrates textual descriptions with visual artifacts including architecture diagrams, data-flow representations, and sequence diagrams for comprehensive understanding.

### Data Flow

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Codebase      │───▶│  Hierarchical    │───▶│  Multi-Agent    │
│   Analysis      │    │  Decomposition   │    │  Processing     │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │                        │
                                ▼                        ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Visual        │◀───│  Multi-Modal     │◀───│  Structured     │
│   Artifacts     │    │  Synthesis       │    │  Content        │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

---

## Requirements

- **Python 3.12+**
- **Node.js** (for Mermaid diagram validation)
- **LLM API access** (Anthropic Claude, OpenAI, Azure OpenAI, AWS Bedrock)
- **Git** (for branch creation features)

---

## Additional Resources

### Documentation & Guides
- **[MCP Server](codewiki/mcp/)** - Model Context Protocol server for IDE integrations
- **[Docker Deployment](docker/DOCKER_README.md)** - Containerized deployment instructions
- **[Development Guide](DEVELOPMENT.md)** - Project structure, architecture, and contributing guidelines
- **[CodeWikiBench](https://github.com/FSoft-AI4Code/CodeWikiBench)** - Repository-level documentation benchmark
- **[Live Demo](https://fsoft-ai4code.github.io/codewiki-demo/)** - Interactive demo and examples

### Academic Resources
- **[Paper](https://arxiv.org/abs/2510.24428)** - Full research paper with detailed methodology and results
- **[Citation](#citation)** - How to cite CodeWiki in your research

---

## Citation

If you use CodeWiki in your research, please cite:

```bibtex
@misc{hoang2025codewikievaluatingaisability,
      title={CodeWiki: Evaluating AI's Ability to Generate Holistic Documentation for Large-Scale Codebases},
      author={Anh Nguyen Hoang and Minh Le-Anh and Bach Le and Nghi D. Q. Bui},
      year={2025},
      eprint={2510.24428},
      archivePrefix={arXiv},
      primaryClass={cs.SE},
      url={https://arxiv.org/abs/2510.24428},
}
```

---

## Star History

<p align="center">
  <a href="https://star-history.com/#FSoft-AI4Code/CodeWiki&Date">
   <picture>
     <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=FSoft-AI4Code/CodeWiki&type=Date&theme=dark" />
     <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=FSoft-AI4Code/CodeWiki&type=Date" />
     <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=FSoft-AI4Code/CodeWiki&type=Date" />
   </picture>
  </a>
</p>

---

## License

This project is licensed under the MIT License.
