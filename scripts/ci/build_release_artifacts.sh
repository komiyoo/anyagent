#!/usr/bin/env bash
set -euo pipefail

echo "[ci] release artifacts: python wheel/sdist + package checks"

export PIP_DISABLE_PIP_VERSION_CHECK="${PIP_DISABLE_PIP_VERSION_CHECK:-1}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
export PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST:-mirrors.aliyun.com}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-${HOME:-/root}/.cache/pip}"
mkdir -p "$PIP_CACHE_DIR"

if ! python -c "import ctypes" >/dev/null 2>&1; then
  echo "Python ctypes is unavailable after libffi setup; check libffi runtime." >&2
  exit 1
fi

python -m pip install --upgrade "build>=1.2" "hatchling>=1.24" "twine>=5.0"

rm -rf packages/anyagent/dist
python -m build --no-isolation packages/anyagent
python -m twine check packages/anyagent/dist/*

python - <<'PY'
from pathlib import Path
from zipfile import ZipFile

wheel_paths = sorted(Path("packages/anyagent/dist").glob("anyagent-*.whl"))
if not wheel_paths:
    raise SystemExit("missing anyagent wheel in packages/anyagent/dist")

wheel_path = wheel_paths[-1]
with ZipFile(wheel_path) as wheel:
    names = set(wheel.namelist())
    metadata_name = next(
        name for name in names if name.endswith(".dist-info/METADATA")
    )
    entry_points_name = next(
        name for name in names if name.endswith(".dist-info/entry_points.txt")
    )
    metadata = wheel.read(metadata_name).decode()
    entry_points = wheel.read(entry_points_name).decode()
    init_py = wheel.read("anyagent/__init__.py").decode()

if "Name: anyagent" not in metadata:
    raise SystemExit(f"{wheel_path} metadata does not report Name: anyagent")
if "anyagent = anyagent.cli:main" not in entry_points:
    raise SystemExit(f"{wheel_path} is missing the anyagent CLI entrypoint")

metadata_version = next(
    line.removeprefix("Version: ").strip()
    for line in metadata.splitlines()
    if line.startswith("Version: ")
)
runtime_version = next(
    line.split("=", 1)[1].strip().strip('"')
    for line in init_py.splitlines()
    if line.startswith("__version__ = ")
)
if metadata_version != runtime_version:
    raise SystemExit(
        f"{wheel_path} metadata version {metadata_version} does not match anyagent.__version__ {runtime_version}"
    )

print(f"ok: checked {wheel_path.name}")
PY
