#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "${REPO_ROOT}/pyproject.toml" ]]; then
  echo "Expected CodeWiki repo at: ${REPO_ROOT}" >&2
  exit 1
fi

VENV_PY="${REPO_ROOT}/.venv/bin/python"
if [[ ! -x "${VENV_PY}" ]]; then
  echo "Create a venv at repo root first: python3 -m venv ${REPO_ROOT}/.venv" >&2
  exit 1
fi

# CodeWiki has a large dependency tree; flaky mirrors may need resume retries.
exec "${VENV_PY}" -m pip install --resume-retries 10 -e "${REPO_ROOT}" "$@"
