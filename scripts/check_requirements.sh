#!/usr/bin/env bash
set -euo pipefail

# Check missing/incompatible requirements without installing packages.
# Supports:
#   - online index mode (default)
#   - offline wheel mode (--offline-wheels <dir>)
#
# Outputs:
#   - check_requirements.log
#   - missing_requirements.txt
#   - conflict_requirements.txt
#
# Example:
#   ./scripts/check_requirements.sh \
#     --requirements ./CodeWiki/requirements.txt \
#     --offline-wheels ./portable_packages/_work_xxx/codewiki-python-deps/wheels \
#     --python python3

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}" && pwd)"

REQ_FILE="${ROOT_DIR}/requirements.txt"
PYTHON_BIN="python3"
OFFLINE_WHEELS=""
OUT_DIR="${ROOT_DIR}/requirements_check_out"

usage() {
  cat <<'EOF'
Usage:
  check_requirements.sh [options]

Options:
  --requirements <path>      Path to requirements.txt (default: ./CodeWiki/requirements.txt)
  --python <bin>             Python executable (default: python3)
  --offline-wheels <dir>     Offline wheel directory; enables --no-index check
  --out-dir <dir>            Output directory (default: ./requirements_check_out)
  -h, --help                 Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --requirements)
      REQ_FILE="$2"
      shift 2
      ;;
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --offline-wheels)
      OFFLINE_WHEELS="$2"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ ! -f "${REQ_FILE}" ]]; then
  echo "requirements file not found: ${REQ_FILE}" >&2
  exit 1
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "python not found: ${PYTHON_BIN}" >&2
  exit 1
fi

if [[ -n "${OFFLINE_WHEELS}" ]] && [[ ! -d "${OFFLINE_WHEELS}" ]]; then
  echo "offline wheel dir not found: ${OFFLINE_WHEELS}" >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"
LOG_FILE="${OUT_DIR}/check_requirements.log"
MISSING_FILE="${OUT_DIR}/missing_requirements.txt"
CONFLICT_FILE="${OUT_DIR}/conflict_requirements.txt"

echo "requirements=${REQ_FILE}" > "${LOG_FILE}"
echo "python=${PYTHON_BIN}" >> "${LOG_FILE}"
if [[ -n "${OFFLINE_WHEELS}" ]]; then
  echo "mode=offline" >> "${LOG_FILE}"
  echo "offline_wheels=${OFFLINE_WHEELS}" >> "${LOG_FILE}"
else
  echo "mode=online" >> "${LOG_FILE}"
fi
echo "---" >> "${LOG_FILE}"

if [[ -n "${OFFLINE_WHEELS}" ]]; then
  set +e
  "${PYTHON_BIN}" -m pip install \
    --dry-run \
    --no-index \
    --find-links "${OFFLINE_WHEELS}" \
    -r "${REQ_FILE}" >> "${LOG_FILE}" 2>&1
  PIP_EXIT=$?
  set -e
else
  set +e
  "${PYTHON_BIN}" -m pip install \
    --dry-run \
    -r "${REQ_FILE}" >> "${LOG_FILE}" 2>&1
  PIP_EXIT=$?
  set -e
fi

# Extract missing distributions (conservative parsing: bash + grep only)
: > "${MISSING_FILE}"
while IFS= read -r line; do
  case "${line}" in
    *"No matching distribution found for"*|*"Could not find a version that satisfies the requirement"*)
      # Remove optional "ERROR: " prefix without sed/awk dependency
      if [[ "${line}" == ERROR:* ]]; then
        line="${line#ERROR: }"
      fi
      printf '%s\n' "${line}" >> "${MISSING_FILE}"
      ;;
  esac
done < "${LOG_FILE}"

# Try to extract requirement conflict hints from resolver output
: > "${CONFLICT_FILE}"
while IFS= read -r line; do
  case "${line}" in
    *"ResolutionImpossible"*|*"depends on"*|*"conflicting dependencies"*|*"Cannot install"*)
      printf '%s\n' "${line}" >> "${CONFLICT_FILE}"
      ;;
  esac
done < "${LOG_FILE}"

echo "Check done."
echo "pip_exit_code=${PIP_EXIT}"
echo "log:      ${LOG_FILE}"
echo "missing:  ${MISSING_FILE}"
echo "conflict: ${CONFLICT_FILE}"

if [[ -s "${MISSING_FILE}" || -s "${CONFLICT_FILE}" || ${PIP_EXIT} -ne 0 ]]; then
  echo "Result: issues found (missing package and/or dependency conflict)."
  exit 3
fi

echo "Result: no missing package or conflict detected in dry-run."
