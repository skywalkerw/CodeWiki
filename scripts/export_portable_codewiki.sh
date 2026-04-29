#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEWIKI_DIR="${ROOT_DIR}/CodeWiki"
OUT_ROOT="${ROOT_DIR}/portable_packages"
STAMP="$(date +%Y%m%d_%H%M%S)"
PYTHON_BIN="${EXPORT_PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
TARGET_PLATFORM="${EXPORT_TARGET_PLATFORM:-}"
TARGET_PYTHON_VERSION="${EXPORT_TARGET_PYTHON_VERSION:-}"
TARGET_IMPLEMENTATION="${EXPORT_TARGET_IMPLEMENTATION:-cp}"
TARGET_ABI="${EXPORT_TARGET_ABI:-}"
TARGET_ONLY_BINARY="${EXPORT_TARGET_ONLY_BINARY:-}"
TARGET_SOURCE_FALLBACK_PACKAGES="${EXPORT_TARGET_SOURCE_FALLBACK_PACKAGES:-pminit==1.2.0}"
TARGET_SKIP_PACKAGES="${EXPORT_TARGET_SKIP_PACKAGES:-}"
PIP_INDEX_URL="${EXPORT_PIP_INDEX_URL:-}"
PIP_EXTRA_INDEX_URL="${EXPORT_PIP_EXTRA_INDEX_URL:-}"
TARGET_SOURCE_BUILD_DEPS="${EXPORT_TARGET_SOURCE_BUILD_DEPS:-poetry-core>=1.1.1,setuptools>=68.0.0,wheel}"
TARGET_EXTRA_PACKAGES="${EXPORT_TARGET_EXTRA_PACKAGES:-}"

if [[ ! -f "${CODEWIKI_DIR}/pyproject.toml" ]]; then
  echo "Missing CodeWiki project at ${CODEWIKI_DIR}" >&2
  exit 1
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="${EXPORT_PYTHON_BIN:-python3}"
fi

PY_VER="$("${PYTHON_BIN}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PLATFORM_TAG="$("${PYTHON_BIN}" -c 'import platform; print(f"{platform.system().lower()}-{platform.machine().lower()}")')"

if [[ -n "${TARGET_PYTHON_VERSION}" ]]; then
  PY_VER="${TARGET_PYTHON_VERSION}"
fi
if [[ -n "${TARGET_PLATFORM}" ]]; then
  PLATFORM_TAG="${TARGET_PLATFORM}"
fi

WORK_DIR="${OUT_ROOT}/_work_${STAMP}"
CODE_PKG_DIR="${WORK_DIR}/codewiki-portable-minimal"
DEPS_PKG_DIR="${WORK_DIR}/codewiki-python-deps"
WHEELS_DIR="${DEPS_PKG_DIR}/wheels"

mkdir -p "${CODE_PKG_DIR}" "${WHEELS_DIR}" "${OUT_ROOT}"

echo "[1/5] Preparing portable code package layout..."
cp -R "${CODEWIKI_DIR}/codewiki" "${CODE_PKG_DIR}/codewiki"
cp "${CODEWIKI_DIR}/pyproject.toml" "${CODE_PKG_DIR}/pyproject.toml"
cp "${CODEWIKI_DIR}/README.md" "${CODE_PKG_DIR}/README.md"
cp "${CODEWIKI_DIR}/requirements.txt" "${CODE_PKG_DIR}/requirements.txt"
cp "${CODEWIKI_DIR}/requirements.txt" "${DEPS_PKG_DIR}/requirements.txt"

cat > "${CODE_PKG_DIR}/run_codewiki.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SELF_DIR}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ ! -d "${VENV_DIR}" ]]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip

if [[ -d "${SELF_DIR}/../codewiki-python-deps/wheels" ]]; then
  python -m pip install --no-index --find-links "${SELF_DIR}/../codewiki-python-deps/wheels" -r "${SELF_DIR}/requirements.txt"
else
  python -m pip install -r "${SELF_DIR}/requirements.txt"
fi

python -m pip install --no-deps -e "${SELF_DIR}"
exec python -m codewiki "$@"
EOF
chmod +x "${CODE_PKG_DIR}/run_codewiki.sh"

cat > "${CODE_PKG_DIR}/native_codewiki_generate.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="${NATIVE_CODEWIKI_PROJECT:-$(pwd)}"
OUT="${NATIVE_CODEWIKI_OUT:-${PROJECT}/docs}"
BASE_URL="${NATIVE_CODEWIKI_BASE_URL:-https://coding.dashscope.aliyuncs.com/v1}"
MODEL="${NATIVE_CODEWIKI_MODEL:-glm-5}"

if [[ "${NATIVE_CODEWIKI_APPLY_CONFIG:-0}" == "1" ]] && [[ -n "${NATIVE_CODEWIKI_API_KEY:-}" ]]; then
  "${SELF_DIR}/run_codewiki.sh" config set \
    --provider openai-compatible \
    --api-key "${NATIVE_CODEWIKI_API_KEY}" \
    --base-url "${BASE_URL}" \
    --main-model "${MODEL}" \
    --cluster-model "${MODEL}" \
    --fallback-model "${MODEL}"
fi

mkdir -p "${OUT}"
export CODEWIKI_LLM_TRACE="${CODEWIKI_LLM_TRACE:-1}"

cd "${PROJECT}"
exec "${SELF_DIR}/run_codewiki.sh" generate -o "${OUT}" --verbose "$@"
EOF
chmod +x "${CODE_PKG_DIR}/native_codewiki_generate.sh"

cat > "${CODE_PKG_DIR}/config.template.json" <<'EOF'
{
  "base_url": "https://coding.dashscope.aliyuncs.com/v1",
  "main_model": "glm-5",
  "cluster_model": "glm-5",
  "fallback_model": "glm-4p5",
  "doc_language": "zh",
  "default_output": "docs",
  "provider": "openai-compatible",
  "aws_region": "us-east-1",
  "api_version": "2024-12-01-preview",
  "azure_deployment": "",
  "max_tokens": 32768,
  "max_token_per_module": 36369,
  "max_token_per_leaf_module": 16000,
  "max_depth": 2,
  "agent_instructions": {}
}
EOF

cat > "${CODE_PKG_DIR}/PORTABLE_README.md" <<EOF
# CodeWiki Portable (Minimal Code + Startup Script)

## Included
- \`codewiki/\` source package
- \`pyproject.toml\`
- \`requirements.txt\`
- \`run_codewiki.sh\`
- \`native_codewiki_generate.sh\`
- \`config.template.json\`

## Usage
1. Place this folder next to \`codewiki-python-deps/\` (optional but recommended for offline install).
2. Run:
   \`\`\`bash
   ./run_codewiki.sh --version
   \`\`\`
3. Configure model:
   \`\`\`bash
   ./run_codewiki.sh config set --api-key <KEY> --base-url <URL> --main-model <MODEL> --cluster-model <MODEL>
   \`\`\`
4. Generate docs from your repo root:
   \`\`\`bash
   ./run_codewiki.sh generate -o ./docs --verbose
   \`\`\`
5. Optional: use template config
   \`\`\`bash
   mkdir -p ~/.codewiki
   cp ./config.template.json ~/.codewiki/config.json
   ./run_codewiki.sh config validate
   \`\`\`
EOF

echo "[2/5] Downloading Python dependency wheels..."
REQ_FOR_DOWNLOAD="${CODEWIKI_DIR}/requirements.txt"
PIP_DOWNLOAD_ARGS=(-r "${REQ_FOR_DOWNLOAD}" -d "${WHEELS_DIR}")
if [[ -n "${PIP_INDEX_URL}" ]]; then
  PIP_DOWNLOAD_ARGS+=(--index-url "${PIP_INDEX_URL}")
fi
if [[ -n "${PIP_EXTRA_INDEX_URL}" ]]; then
  PIP_DOWNLOAD_ARGS+=(--extra-index-url "${PIP_EXTRA_INDEX_URL}")
fi
if [[ -n "${TARGET_PLATFORM}" ]]; then
  if [[ -z "${TARGET_ONLY_BINARY}" ]]; then
    TARGET_ONLY_BINARY=":all:"
  fi
  if [[ -n "${TARGET_SOURCE_FALLBACK_PACKAGES}" ]]; then
    FILTERED_REQ="${WORK_DIR}/requirements.binary.txt"
    cp "${CODEWIKI_DIR}/requirements.txt" "${FILTERED_REQ}"
    IFS=',' read -r -a SOURCE_PKGS <<< "${TARGET_SOURCE_FALLBACK_PACKAGES}"
    for pkg in "${SOURCE_PKGS[@]}"; do
      pkg="$(echo "${pkg}" | xargs)"
      [[ -z "${pkg}" ]] && continue
      # Remove exact pinned line from binary-only list; fetched as source later.
      grep -Fvx "${pkg}" "${FILTERED_REQ}" > "${FILTERED_REQ}.tmp" || true
      mv "${FILTERED_REQ}.tmp" "${FILTERED_REQ}"
    done
    REQ_FOR_DOWNLOAD="${FILTERED_REQ}"
    PIP_DOWNLOAD_ARGS=(-r "${REQ_FOR_DOWNLOAD}" -d "${WHEELS_DIR}")
  fi
  if [[ -n "${TARGET_SKIP_PACKAGES}" ]]; then
    if [[ "${REQ_FOR_DOWNLOAD}" != "${WORK_DIR}/requirements.binary.txt" ]]; then
      FILTERED_REQ="${WORK_DIR}/requirements.binary.txt"
      cp "${CODEWIKI_DIR}/requirements.txt" "${FILTERED_REQ}"
      REQ_FOR_DOWNLOAD="${FILTERED_REQ}"
      PIP_DOWNLOAD_ARGS=(-r "${REQ_FOR_DOWNLOAD}" -d "${WHEELS_DIR}")
    fi
    IFS=',' read -r -a SKIP_PKGS <<< "${TARGET_SKIP_PACKAGES}"
    for pkg in "${SKIP_PKGS[@]}"; do
      pkg="$(echo "${pkg}" | xargs)"
      [[ -z "${pkg}" ]] && continue
      grep -Ev "^${pkg}([<>=!~].*)?$" "${FILTERED_REQ}" > "${FILTERED_REQ}.tmp" || true
      mv "${FILTERED_REQ}.tmp" "${FILTERED_REQ}"
      echo "Skipping package from target download: ${pkg}"
    done
    PIP_DOWNLOAD_ARGS=(-r "${REQ_FOR_DOWNLOAD}" -d "${WHEELS_DIR}")
  fi
  PIP_DOWNLOAD_ARGS+=(--platform "${TARGET_PLATFORM}")
  PIP_DOWNLOAD_ARGS+=(--implementation "${TARGET_IMPLEMENTATION}")
  if [[ -n "${TARGET_PYTHON_VERSION}" ]]; then
    PIP_DOWNLOAD_ARGS+=(--python-version "${TARGET_PYTHON_VERSION}")
  fi
  if [[ -n "${TARGET_ABI}" ]]; then
    PIP_DOWNLOAD_ARGS+=(--abi "${TARGET_ABI}")
  fi
  if [[ -n "${TARGET_ONLY_BINARY}" ]]; then
    PIP_DOWNLOAD_ARGS+=(--only-binary "${TARGET_ONLY_BINARY}")
  fi
fi
"${PYTHON_BIN}" -m pip download "${PIP_DOWNLOAD_ARGS[@]}"

if [[ -n "${TARGET_PLATFORM}" ]] && [[ -n "${TARGET_SOURCE_FALLBACK_PACKAGES}" ]]; then
  IFS=',' read -r -a SOURCE_PKGS <<< "${TARGET_SOURCE_FALLBACK_PACKAGES}"
  for pkg in "${SOURCE_PKGS[@]}"; do
    pkg="$(echo "${pkg}" | xargs)"
    [[ -z "${pkg}" ]] && continue
    echo "Downloading source fallback package: ${pkg}"
    "${PYTHON_BIN}" -m pip download --no-deps "${pkg}" -d "${WHEELS_DIR}"
  done
fi

# Download build backends for source fallback packages (offline build isolation support)
if [[ -n "${TARGET_SOURCE_BUILD_DEPS}" ]]; then
  IFS=',' read -r -a BUILD_DEPS <<< "${TARGET_SOURCE_BUILD_DEPS}"
  for dep in "${BUILD_DEPS[@]}"; do
    dep="$(echo "${dep}" | xargs)"
    [[ -z "${dep}" ]] && continue
    echo "Downloading source build dependency: ${dep}"
    BUILD_DEP_ARGS=(--no-deps "${dep}" -d "${WHEELS_DIR}")
    if [[ -n "${PIP_INDEX_URL}" ]]; then
      BUILD_DEP_ARGS+=(--index-url "${PIP_INDEX_URL}")
    fi
    if [[ -n "${PIP_EXTRA_INDEX_URL}" ]]; then
      BUILD_DEP_ARGS+=(--extra-index-url "${PIP_EXTRA_INDEX_URL}")
    fi
    "${PYTHON_BIN}" -m pip download "${BUILD_DEP_ARGS[@]}"
  done
fi

# Download extra packages explicitly (useful for platform-marker deps in cross-platform export).
if [[ -n "${TARGET_EXTRA_PACKAGES}" ]]; then
  IFS=',' read -r -a EXTRA_PKGS <<< "${TARGET_EXTRA_PACKAGES}"
  for pkg in "${EXTRA_PKGS[@]}"; do
    pkg="$(echo "${pkg}" | xargs)"
    [[ -z "${pkg}" ]] && continue
    echo "Downloading extra package: ${pkg}"
    EXTRA_ARGS=("${pkg}" -d "${WHEELS_DIR}")
    if [[ -n "${PIP_INDEX_URL}" ]]; then
      EXTRA_ARGS+=(--index-url "${PIP_INDEX_URL}")
    fi
    if [[ -n "${PIP_EXTRA_INDEX_URL}" ]]; then
      EXTRA_ARGS+=(--extra-index-url "${PIP_EXTRA_INDEX_URL}")
    fi
    if [[ -n "${TARGET_PLATFORM}" ]]; then
      EXTRA_ARGS+=(--platform "${TARGET_PLATFORM}" --implementation "${TARGET_IMPLEMENTATION}")
      if [[ -n "${TARGET_PYTHON_VERSION}" ]]; then
        EXTRA_ARGS+=(--python-version "${TARGET_PYTHON_VERSION}")
      fi
      if [[ -n "${TARGET_ABI}" ]]; then
        EXTRA_ARGS+=(--abi "${TARGET_ABI}")
      fi
      if [[ -n "${TARGET_ONLY_BINARY}" ]]; then
        EXTRA_ARGS+=(--only-binary "${TARGET_ONLY_BINARY}")
      fi
    fi
    "${PYTHON_BIN}" -m pip download "${EXTRA_ARGS[@]}"
  done
fi

# Keep packaged requirements aligned with skipped packages to avoid target install failures.
if [[ -n "${TARGET_SKIP_PACKAGES}" ]]; then
  IFS=',' read -r -a SKIP_PKGS <<< "${TARGET_SKIP_PACKAGES}"
  for req_file in "${CODE_PKG_DIR}/requirements.txt" "${DEPS_PKG_DIR}/requirements.txt"; do
    for pkg in "${SKIP_PKGS[@]}"; do
      pkg="$(echo "${pkg}" | xargs)"
      [[ -z "${pkg}" ]] && continue
      grep -Ev "^${pkg}([<>=!~].*)?$" "${req_file}" > "${req_file}.tmp" || true
      mv "${req_file}.tmp" "${req_file}"
    done
  done
  {
    echo "# Packages intentionally skipped for this export target"
    for pkg in "${SKIP_PKGS[@]}"; do
      pkg="$(echo "${pkg}" | xargs)"
      [[ -z "${pkg}" ]] && continue
      echo "${pkg}"
    done
  } > "${CODE_PKG_DIR}/SKIPPED_PACKAGES.txt"
fi

echo "[3/5] Building dependency install helper..."
cat > "${DEPS_PKG_DIR}/install_deps.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <venv-path>" >&2
  exit 1
fi

VENV_PATH="$1"
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

"${PYTHON_BIN}" -m venv "${VENV_PATH}"
source "${VENV_PATH}/bin/activate"
python -m pip install --upgrade pip
python -m pip install --no-index --find-links "${SELF_DIR}/wheels" -r "${SELF_DIR}/requirements.txt"

echo "Dependencies installed into ${VENV_PATH}"
EOF
chmod +x "${DEPS_PKG_DIR}/install_deps.sh"

cat > "${DEPS_PKG_DIR}/PORTABLE_README.md" <<EOF
# CodeWiki Portable Python Dependencies

Offline wheel bundle for Python ${PY_VER} on ${PLATFORM_TAG}.

## Install into a venv
\`\`\`bash
./install_deps.sh ./.venv
\`\`\`

Or use with the minimal package:
- Put \`codewiki-python-deps/\` next to \`codewiki-portable-minimal/\`
- Run \`codewiki-portable-minimal/run_codewiki.sh\`
EOF

echo "[4/5] Creating tar.gz archives..."
CODE_ARCHIVE="${OUT_ROOT}/codewiki-portable-minimal-${STAMP}.tar.gz"
DEPS_ARCHIVE="${OUT_ROOT}/codewiki-python-deps-${PY_VER}-${PLATFORM_TAG}-${STAMP}.tar.gz"

tar -C "${WORK_DIR}" -czf "${CODE_ARCHIVE}" "codewiki-portable-minimal"
tar -C "${WORK_DIR}" -czf "${DEPS_ARCHIVE}" "codewiki-python-deps"

echo "[5/5] Done."
echo "Code package : ${CODE_ARCHIVE}"
echo "Deps package : ${DEPS_ARCHIVE}"
