FROM python:3.12-slim-bookworm

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    PIP_CACHE_DIR=/root/.cache/pip \
    UV_CACHE_DIR=/root/.cache/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        libffi-dev \
        pkg-config \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade build hatchling pytest twine uv \
    && mkdir -p "$PIP_CACHE_DIR" "$UV_CACHE_DIR"

RUN python -c "import ctypes" \
    && python - <<'PY'
import importlib.util

missing = [
    module
    for module in ("build", "hatchling", "pytest", "twine", "uv")
    if importlib.util.find_spec(module) is None
]
if missing:
    raise SystemExit(f"missing build tools: {', '.join(missing)}")
PY
