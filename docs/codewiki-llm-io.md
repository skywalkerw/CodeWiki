# CodeWiki LLM 调用与输入/输出约定

本文说明本仓库所依赖的 **CodeWiki**（路径：`CodeWiki/codewiki/`）在分析流水线中如何构造 **请求**、如何解析 **返回文本**，以及 **`trace/` 调试文件** 的格式与覆盖范围。便于对照调试、改 prompt 或接入替代模型。

---

## 一、流水线中的三类 LLM 场景

| 阶段 | 模板入口 | 调用方式 | 源码 |
|------|----------|----------|------|
| **仓库/模块总览** | `REPO_OVERVIEW_PROMPT`、`MODULE_OVERVIEW_PROMPT` | `call_llm`（`trace_label=parent_overview`） | `prompt_template.py` → `documentation_generator.generate_parent_module_docs` |
| **模块聚类** | `CLUSTER_REPO_PROMPT` | `call_llm`（`trace_label=cluster_modules`） | `cluster_modules.py` |
| **叶子 / 子模块文档** | `USER_PROMPT` 等 | pydantic-ai **`Agent.run`** → `CompatibleOpenAIModel.request` | `agent_orchestrator.py`、`generate_sub_module_documentations.py` |

---

## 二、统一调用：`call_llm`

- **位置**：`CodeWiki/codewiki/src/be/llm_services.py` 中 **`call_llm`**。
- **入参**：`prompt: str`；可选 `model`、`temperature`、`trace_label`（写入 trace 元数据）。
- **Provider 分支**（同一函数内）：`openai-compatible`（默认）→ OpenAI SDK `chat.completions.create`；`bedrock` / `anthropic` → **litellm.completion**；`azure-openai` → **AzureOpenAI** `chat.completions.create`。
- **HTTP 形态（OpenAI 兼容）**：单次请求，**仅一条 `user` 消息**，无单独 `system` 字段（`messages=[{"role": "user", "content": prompt}]`）。
- **返回值**：`choices[0].message.content` 字符串（litellm/Azure 路径语义一致）。

---

## 三、场景详解

### 3.1 仓库/模块总览（Overview）

- **模板**：`REPO_OVERVIEW_PROMPT`、`MODULE_OVERVIEW_PROMPT`（`CodeWiki/codewiki/src/be/prompt_template.py`）。
- **输入占位**：仓库名、可选目录路径、`output_language` / `doc_language`，以及夹在 `<OVERVIEW>...</OVERVIEW>` 中的**参考摘要**（由依赖与结构等拼出）。
- **期望输出**：模型在 `<OVERVIEW>...</OVERVIEW>` 之间输出 Markdown；解析见 `_try_parse_overview_tags`；失败时可重试（`CODEWIKI_OVERVIEW_MAX_ATTEMPTS`）。

```text
【输入 user.content 片段示意】
...
<OVERVIEW>
（结构化摘要，供模型参考）
</OVERVIEW>
...
Your overview must be written inside <OVERVIEW>...</OVERVIEW> tags.
```

```text
【模型返回示意】
<OVERVIEW>
# Overview
...
</OVERVIEW>
```

### 3.2 模块聚类（Cluster）

- **模板**：`CLUSTER_REPO_PROMPT`，填入 `<POTENTIAL_CORE_COMPONENTS>` 等。
- **期望输出**：`<GROUPED_COMPONENTS>...</GROUPED_COMPONENTS>` 内为 **可 `eval` 的 Python 字典字面量**（顶层键为模块名，`components` 等字段与上游列表一致）。

**解析**（`cluster_modules.py`）：`split` 取标签内文本 → `eval` → `dict`；缺标签或非 `dict` 则聚类失败或跳过子树。

模板要求：顶层模块键 **ASCII snake_case**；`components` 中每项与上游 **逐字一致**。

### 3.3 叶子/核心组件文档（Leaf / Agent）

- **模板**：`USER_PROMPT`，含 `<CORE_COMPONENT_CODES>...</CORE_COMPONENT_CODES>` 等占位。
- **期望输出**：由模板约束的 Markdown 技术文档；由 **pydantic-ai Agent** 多轮调用模型与工具完成，**不是**单次 `call_llm` 能概括整条链路。

与总览、聚类相比，该阶段在 trace 里表现为多条 **`source=pydantic_agent`** 记录（每次底层 **`request`** 一次一条）。

---

## 四、LLM trace 文件（`<OUT>/trace/`）

### 4.1 何时写入

- **目录**：`codewiki generate -o <OUT>` 时，trace 写在 **`<OUT>/trace/`**（与 `-o` 一致，不是仓库根目录）。
- **开关**：`Config.from_cli` 读取环境变量 **`CODEWIKI_LLM_TRACE`**：为 `1` / `true` / `yes` / `on` 时开启；**未设置则默认关闭**（代码侧）。
- **本仓库脚本**：`scripts/native_codewiki_generate.sh` 默认 `export CODEWIKI_LLM_TRACE="${CODEWIKI_LLM_TRACE:-1}"`，即**用脚本时默认开**；关闭可设 `CODEWIKI_LLM_TRACE=0`。
- **文档语言**（可选）：`CODEWIKI_DOC_LANGUAGE=zh` 等，见 `Config.from_cli`（与 trace 独立）。
- **无 `-o` 输出目录时**（例如仅运行 **`codewiki config validate`**）：在 **`CODEWIKI_LLM_TRACE`** 开启时，trace 写入 **`CODEWIKI_LLM_TRACE_DIR`**，默认 **`~/.codewiki/llm_trace`**（`write_llm_trace_standalone`）。

### 4.2 文件命名与内容结构

- **文件名**：`llm_YYYYMMDD_HHMMSS_NNNNNN.txt`（序号递增）。
- **文件头元数据**（示例）：

```text
model=<模型名>
source=call_llm | pydantic_agent
label=<可选：cluster_modules | parent_overview | pydantic_ai_agent_request>
timestamp=ISO 本地时间
```

- **正文分隔**：
  - **`LLM TRACE — INPUT`**：聚类/总览为整段 `prompt`；Agent 为 pydantic **消息列表** 的 JSON/序列化文本。
  - 若失败：**`LLM TRACE — ERROR`** + 堆栈。
  - **`LLM TRACE — OUTPUT`**：模型返回文本或 Agent 的 `ModelResponse` 序列化。

### 4.3 统一切入点（业务层「最底层」）

1. **`call_llm`**：所有直连 **chat/completions 类** 的文档生成调用（聚类、总览），含 OpenAI / litellm / Azure 实现分支。
2. **`CompatibleOpenAIModel.request`** / **`request_stream`**：所有 pydantic-ai **`Agent`** 的底层请求（含 **`FallbackModel`** 对子模型依次 `request`）；流式路径在成功时仅记录 **输入 + 摘要**（不聚合逐 token 正文）。

未再包一层 **OpenAI Python SDK 的全局 monkey-patch**；若需要 SDK 级日志需自行 hook。

**其它 LLM 相关 API**：

- **`codewiki config validate`**：连通性探测使用 **`models.list()`**（或 Anthropic 等价），写入 **standalone** trace（`source=cli`，`label=config_validate_models_list`），不含 API key 明文。

### 4.4 `push_llm_trace_context` 与 CLI

- **`DocumentationGenerator.run()`**（MCP、`background_worker`、`src/be/main.py` 等）：在 `run()` 开头 **`push_llm_trace_context`**，整段 `_run_inner`（含聚类 + 文档生成）内 Agent 可解析 **`docs_dir`**。
- **CLI `codewiki generate`**：`CLIDocumentationGenerator` **不**调用 `run()`，而是分阶段执行；在 **`await generate_module_documentation`** 外已 **`push`/`pop`**，否则 **`source=pydantic_agent`** 的 trace 不会写入（`call_llm` 仍可用，因显式传入 `config`）。

### 4.5 LLM 调用点与 trace 覆盖（审计）

| 调用场景 | 代码位置 | trace 方式 |
|----------|----------|------------|
| 模块聚类 | `cluster_modules.py` → `call_llm(..., trace_label=cluster_modules)` | `source=call_llm`，显式 `config` |
| 父模块 / 仓库总览 | `documentation_generator.py` → `call_llm(..., trace_label=parent_overview)` | 同上 |
| 叶子 / 子模块 Agent | `agent_orchestrator.py`、`generate_sub_module_documentations.py` → `Agent.run` | `source=pydantic_agent`，依赖 **push** |
| MCP / `background_worker` | `await doc_gen.run()` | `run()` 内已 push，覆盖全流程 |
| CLI `codewiki generate` | `_run_backend_generation`：Stage2 聚类 → Stage3 **push** + `generate_module_documentation` | 聚类不依赖 push；Agent 依赖 push |
| CLI `config validate`（非 `--quick`） | `cli/commands/config.py`：Azure / Anthropic / OpenAI SDK `models.list` | standalone `~/.codewiki/llm_trace`（或 `CODEWIKI_LLM_TRACE_DIR`） |

### 4.6 若只看到聚类 trace

- **阶段顺序**：依赖分析 → 聚类 → 叶子/父级文档 → 仓库总览；**靠后的 call_llm / Agent 可能尚未执行完**。
- **跳过逻辑**：若 `<OUT>` 下已有 **`first_module_tree.json`** 且未删，可能不再重新聚类；若已有对应 **`.md` / `overview.md`**，会跳过部分 `call_llm` 或 Agent。
- **环境与安装**：需 **`pip install -e CodeWiki`** 且 **`CODEWIKI_LLM_TRACE=1`** 传入 **`python -m codewiki generate`** 进程（脚本已 export 时一般满足）。

---

## 五、与 `docs/samples` 的关系

`docs/samples/` 下为**虚构项目**的交付物结构样例（如 `0.1-REPOSITORY_OVERVIEW.md`、`2.1-leaf_*.md`），表示**流水线产出形态**；本文描述的是 **LLM 请求/响应与 trace 文件** 层级，二者可对照阅读，不是同一文件集合。

---

## 六、快速对照表（模板与解析）

| 阶段 | 主要模板 | 输入特点 | 输出如何被使用 |
|------|----------|----------|----------------|
| 总览 | `*_OVERVIEW_PROMPT` | `<OVERVIEW>` 参考块 | 截取 `<OVERVIEW>` 内 Markdown |
| 聚类 | `CLUSTER_REPO_PROMPT` | `<POTENTIAL_CORE_COMPONENTS>` | `<GROUPED_COMPONENTS>` → `eval` → `dict` |
| 叶子 | `USER_PROMPT` | `<CORE_COMPONENT_CODES>` 等 | Agent 多轮，落盘为各模块 `.md` |

修改行为时请同步调整 **`prompt_template.py`** 与调用方（如 **`cluster_modules.py`**）的解析假设，避免标签或 `eval` 格式不一致导致静默失败。
