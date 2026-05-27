# syntax=docker/dockerfile:1.7
FROM --platform=linux/amd64 python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=0 \
    PIP_CACHE_DIR=/root/.cache/pip \
    UV_CACHE_DIR=/root/.cache/uv \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH=/root/.local/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      bash \
      ca-certificates \
      curl \
      git \
      libffi8 \
      libssl3 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade \
      build \
      hatchling \
      pytest \
      twine \
      uv

WORKDIR /opt/anyagent-cache
COPY packages/anyagent/pyproject.toml packages/anyagent/uv.lock ./packages/anyagent/

RUN uv sync \
      --project packages/anyagent \
      --frozen \
      --extra external-storage \
      --group dev \
      --no-install-project \
    && rm -rf packages/anyagent/.venv

RUN python - <<'PY'
import ctypes
import importlib.util

for module in ("build", "hatchling", "pytest", "twine", "uv"):
    if importlib.util.find_spec(module) is None:
        raise SystemExit(f"missing module: {module}")

ctypes.CDLL("libffi.so.8")
PY

WORKDIR /root/workspace
