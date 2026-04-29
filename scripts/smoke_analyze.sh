#!/usr/bin/env bash
# 固定：分析 monitor-system backend，产出写到 demo/_test_out（已 gitignore）。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/demo/_test_out"
PROJECT="${JAVA_CODE_WIKI_SMOKE_PROJECT:-${HOME}/.liteclaw/workspace/monitor-system/backend}"
JUDGE_MODEL="${JAVA_CODE_WIKI_RUBRIC_MODEL:-glm-5}"
JUDGE_BASE_URL="${JAVA_CODE_WIKI_RUBRIC_BASE_URL:-https://coding.dashscope.aliyuncs.com/v1}"
JUDGE_API_KEY="${JAVA_CODE_WIKI_RUBRIC_API_KEY:-}"
JUDGE_TIMEOUT_SEC="${JAVA_CODE_WIKI_RUBRIC_TIMEOUT_SEC:-90}"
JUDGE_MAX_LEAVES="${JAVA_CODE_WIKI_RUBRIC_MAX_LEAVES:-2}"
DYNAMIC_USE_LLM_SYNTH="${JAVA_CODE_WIKI_DYNAMIC_USE_LLM_SYNTH:-1}"
DYNAMIC_PARENT_TIMEOUT_SEC="${JAVA_CODE_WIKI_DYNAMIC_PARENT_TIMEOUT_SEC:-180}"
DYNAMIC_SYNTH_RETRY_TIMES="${JAVA_CODE_WIKI_DYNAMIC_SYNTH_RETRY_TIMES:-1}"

args=(
  "${PROJECT}"
  -o "${OUT}"
  --log-level DEBUG
  --rubric-judge-model "${JUDGE_MODEL}"
  --rubric-judge-base-url "${JUDGE_BASE_URL}"
  --rubric-judge-timeout-sec "${JUDGE_TIMEOUT_SEC}"
  --rubric-judge-max-leaves "${JUDGE_MAX_LEAVES}"
  --dynamic-llm-parent-timeout-sec "${DYNAMIC_PARENT_TIMEOUT_SEC}"
  --dynamic-llm-synth-retry-times "${DYNAMIC_SYNTH_RETRY_TIMES}"
)
if [[ -n "${JUDGE_API_KEY}" ]]; then
  args+=(--rubric-judge-api-key "${JUDGE_API_KEY}")
fi
if [[ "${DYNAMIC_USE_LLM_SYNTH}" == "1" ]]; then
  args+=(--dynamic-use-llm-synthesis)
fi
args+=("$@")

exec java-code-wiki analyze "${args[@]}"
