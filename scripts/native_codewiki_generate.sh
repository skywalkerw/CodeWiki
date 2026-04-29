#!/usr/bin/env bash
# 原生 CodeWiki：直接 `python -m codewiki generate`，不经 demo 桥接。
# 需已安装 vendored CodeWiki 依赖：./scripts/bootstrap_codewiki.sh
# 并配置 LLM：codewiki config set / validate（见 CodeWiki README）。
#
# DashScope（OpenAI 兼容）常用默认值（与 smoke_analyze 一致）：
#   NATIVE_CODEWIKI_BASE_URL 默认 https://coding.dashscope.aliyuncs.com/v1
#   NATIVE_CODEWIKI_MODEL     默认 glm-5（main / cluster / fallback）
# 若 NATIVE_CODEWIKI_APPLY_CONFIG=1 且设置了 NATIVE_CODEWIKI_API_KEY，会在运行前执行一次
#   codewiki config set（密钥勿写入仓库，用环境变量或本机 keychain）。
# 文档语言：`codewiki config set --doc-language zh|en`（写入 ~/.codewiki/config.json）；
#   单次覆盖可设环境变量 CODEWIKI_DOC_LANGUAGE=zh（优先级高于配置）。
# Monorepo：分析目录可以是子模块根目录（如 backend/），只要向上能找到 .git，Git 相关能力仍可用。
# 父模块 overview 若缺 <OVERVIEW> 标签会重试，次数：CODEWIKI_OVERVIEW_MAX_ATTEMPTS（默认 3）。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEWIKI_SRC="${REPO_ROOT}/CodeWiki"
DEMO_ROOT="${REPO_ROOT}/demo"

PROJECT="${NATIVE_CODEWIKI_PROJECT:-${HOME}/.liteclaw/workspace/monitor-system/backend}"
# 默认每次独立子目录，避免 generate 对已有 docs 的交互式覆盖确认
DEFAULT_OUT="${DEMO_ROOT}/_native_codewiki_out/$(date +%Y%m%d_%H%M%S)"
OUT="${NATIVE_CODEWIKI_OUT:-${DEFAULT_OUT}}"

VENV_PY="${REPO_ROOT}/.venv/bin/python"
if [[ -x "${VENV_PY}" ]]; then
  PYTHON="${NATIVE_CODEWIKI_PYTHON:-${VENV_PY}}"
else
  PYTHON="${NATIVE_CODEWIKI_PYTHON:-python3}"
fi

if [[ ! -d "${CODEWIKI_SRC}" ]] || [[ ! -f "${CODEWIKI_SRC}/pyproject.toml" ]]; then
  echo "Missing CodeWiki checkout at: ${CODEWIKI_SRC}" >&2
  exit 1
fi

if [[ ! -d "${PROJECT}" ]]; then
  echo "Project path does not exist: ${PROJECT}" >&2
  exit 1
fi

if ! "${PYTHON}" -c "import codewiki" 2>/dev/null; then
  echo "CodeWiki is not importable with: ${PYTHON}" >&2
  echo "Install with: ${REPO_ROOT}/scripts/bootstrap_codewiki.sh" >&2
  exit 1
fi

BASE_URL="${NATIVE_CODEWIKI_BASE_URL:-https://coding.dashscope.aliyuncs.com/v1}"
MODEL="${NATIVE_CODEWIKI_MODEL:-glm-5}"
if [[ "${NATIVE_CODEWIKI_APPLY_CONFIG:-0}" == "1" ]] && [[ -n "${NATIVE_CODEWIKI_API_KEY:-}" ]]; then
  "${PYTHON}" -m codewiki config set \
    --provider openai-compatible \
    --api-key "${NATIVE_CODEWIKI_API_KEY}" \
    --base-url "${BASE_URL}" \
    --main-model "${MODEL}" \
    --cluster-model "${MODEL}" \
    --fallback-model "${MODEL}"
fi

mkdir -p "${OUT}"

# 每次 LLM 调用的输入/输出写入 ${OUT}/trace/（代码默认关闭 trace；本脚本默认打开，CODEWIKI_LLM_TRACE=0 可关）
export CODEWIKI_LLM_TRACE="${CODEWIKI_LLM_TRACE:-1}"

echo "Native CodeWiki: project=${PROJECT}" >&2
echo "Native CodeWiki: output=${OUT}" >&2
echo "Native CodeWiki: LLM trace dir -> ${OUT}/trace (CODEWIKI_LLM_TRACE=${CODEWIKI_LLM_TRACE})" >&2

# generate 以当前工作目录为仓库根目录
cd "${PROJECT}"
exec "${PYTHON}" -m codewiki generate -o "${OUT}" --verbose "$@"
