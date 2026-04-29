# code-wiki-demo（原 java-code-wiki）

在历史 Java 仓库上跑 **CodeWiki 式「先分析、再产出」** 的最小 Python 实现：核心解析与结构化产物由 **`jdtls-lsp-py`**（JDTLS）提供；本包负责 **编排、manifest、与 `docs/samples` 对齐的 JSON 布局**。

## 依赖

使用 **conda `base` 环境**（或任意已激活、且 **Python ≥3.10** 的 conda 环境）。先确认版本：

```bash
conda activate base
python --version   # 需 3.10+
```

若 `base` 仍是 3.9，请先升级该环境的 Python（例如 `conda install python=3.12`），再安装下列依赖。

1. 安装本地 **`jdtls-lsp-py`**（与本仓库 `external/jdtls-lsp-py` 对应）：

```bash
cd /path/to/code-wiki
pip install -e ./external/jdtls-lsp-py
```

2. 在**仓库根目录**创建 venv 并安装本包与 CodeWiki（推荐）：

```bash
cd /path/to/code-wiki
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ./CodeWiki
pip install -e ./demo
```

`demo` 与 `java-code-wiki` 两个 CLI 会指向同一入口（`demo.cli:main`）。

JDTLS / Java 21+ 等要求与 [jdtls-lsp-py README](../external/jdtls-lsp-py/README.md) 一致。

## 用法

对 Maven/Gradle 工程根目录执行 **阶段 1：仅静态扫描**（不启 JDTLS 调用链；最快落地）：

```bash
java-code-wiki analyze /path/to/java-project -o ./out
# 或
demo analyze /path/to/java-project -o ./out
```

可选：启用 `2.2` 的 LLM Judge（OpenAI 兼容接口，示例 GLM-5）：

```bash
RUBRIC_JUDGE_API_KEY="your-key" \
java-code-wiki analyze /path/to/java-project -o ./out \
  --rubric-judge-model glm-5 \
  --rubric-judge-base-url https://coding.dashscope.aliyuncs.com/v1 \
  --rubric-judge-max-leaves 1
```

可选：开启 Phase-3 的 LLM 分层合成（`2.3` 与 `0.1`）：

```bash
RUBRIC_JUDGE_API_KEY="your-key" \
java-code-wiki analyze /path/to/java-project -o ./out \
  --rubric-judge-model glm-5 \
  --rubric-judge-base-url https://coding.dashscope.aliyuncs.com/v1 \
  --dynamic-use-llm-synthesis \
  --dynamic-llm-parent-timeout-sec 180 \
  --dynamic-llm-synth-retry-times 1
```

产出目录（与设计文档样例编号可对照）：

| 文件 | 说明 |
|------|------|
| `1.1-analysis_manifest.json` | 快照与运行元数据 |
| `data/1.2-graph.json` | 轻量依赖图：`maven_module` / `package` / `type`，含 REST entrypoint 到类型的关系边 |
| `data/1.3-module_tree.json` | 模块树：`maven_module` → `feature_leaf`（包）→ `type_leaf`（顶层类型：`qualified_name`、`file`、`line`、LOC） |
| `data/1.2-modules.json` | jdtls `scan_modules` |
| `data/1.2-symbols-by-package.json` | 按包聚合的顶层类型（轻量） |
| `data/1.4-entrypoints.json` | `scan_java_entrypoints` |
| `data/1.5-rest-map.json` | Spring MVC 静态映射（启发式） |
| `graphs/1.5-rest-map.mmd` | REST 预览 Mermaid |
| `reports/2.1-leaf_*.md` | 动态循环下终端叶子文档（树可在运行中委托演化） |
| `reports/2.3-parent_*.md` | 自底向上聚合的父模块文档 |
| `0.1-REPOSITORY_OVERVIEW.md` | 仓库级总览（分层汇总产物） |
| `reports/2.2-rubric_eval.sample.json` | 自动生成的分层 rubric 评分样例（deterministic，无 LLM Judge） |

进阶：使用 **`run_design_bundle`** 生成完整 `design/`（含可选 JDTLS 调用链）请直接使用上游 CLI 或在本项目中扩展 `analyze --with-jdtls-bundle`。

## 本地冒烟（固定输出到 `_test_out`）

在 **code-wiki 仓库根目录** 下，每次可用同一条命令把结果写到 `demo/_test_out`（该目录已 `.gitignore`）：

```bash
java-code-wiki analyze ~/.liteclaw/workspace/monitor-system/backend -o ./demo/_test_out
```

等价脚本（可用环境变量覆盖工程路径：`JAVA_CODE_WIKI_SMOKE_PROJECT`）：

```bash
./scripts/smoke_analyze.sh
```

## 与 CodeWiki 的关系

- **CodeWiki**（仓库根目录 `./CodeWiki`）：多语言 Tree-sitter + Agent 文档管线。
- **本包**：仅 Java；解析事实层委托 `jdtls-lsp-py`；后续可挂同一 `out/` 给 LLM 做「分层合成」（另里程碑）。

## 直接使用完整 CodeWiki 能力

若需要 **完整复用 CodeWiki 原生能力**（含 `generate/config/mcp` 以及其内部 tooling），可先安装 vendored 包，再用桥接命令或原生脚本：

```bash
# 推荐：把 CodeWiki 以 editable 方式装进仓库根 .venv
./scripts/bootstrap_codewiki.sh

demo codewiki generate
java-code-wiki codewiki config show
```

或使用仓库根脚本（不经 demo 桥接，直接 `python -m codewiki generate`）：

```bash
./scripts/native_codewiki_generate.sh
```

说明：

- 若已在 venv 中安装 `codewiki`，桥接命令会直接使用已安装版本。
- 若未安装，桥接会把 `./CodeWiki` 加入 `PYTHONPATH`；仍须满足 CodeWiki 的运行时依赖，因此更推荐 `bootstrap_codewiki.sh` 或 `pip install -e CodeWiki`。
