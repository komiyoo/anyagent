"""Built-in anyagent.yaml defaults.

Values reference the historical environment variable names. Deployments that
only set those variables keep working. Interpolation runs after the layer
merge, so a workspace file can replace a placeholder with a literal.
"""

from __future__ import annotations

from typing import Any


def builtin_defaults() -> dict[str, Any]:
    return {
        "models": {
            "default": "fast",
            "providers": {
                "openai": {
                    "kind": "openai",
                    "api_key": "${OPENAI_API_KEY}",
                    "base_url": "${OPENAI_BASE_URL:-https://api.openai.com/v1}",
                },
                "openai_chat": {
                    "kind": "openai_chat",
                    "api_key": "${OPENAI_API_KEY}",
                    "base_url": "${OPENAI_BASE_URL:-https://api.openai.com/v1}",
                },
                "anthropic": {
                    "kind": "anthropic",
                    "api_key": "${ANTHROPIC_API_KEY}",
                    "base_url": "${ANTHROPIC_BASE_URL:-https://api.anthropic.com/v1}",
                    "anthropic_version": "${ANTHROPIC_VERSION}",
                },
                "gemini": {
                    "kind": "gemini",
                    "api_key": "${GOOGLE_API_KEY:-${GEMINI_API_KEY}}",
                    "base_url": "${GEMINI_BASE_URL:-https://generativelanguage.googleapis.com/v1beta}",
                },
            },
            "aliases": {
                "fast": {"provider": "openai", "model": "gpt-4o-mini"},
            },
        },
        "server": {
            "host": "127.0.0.1",
            "port": "${PORT:-8787}",
            "api_key": "${API_KEY}",
            "admin_api_key": "${ADMIN_API_KEY}",
            "agent_api_key": "${AGENT_API_KEY}",
            "cors_origins": "${CORS_ORIGINS}",
            "studio_dir": "${STUDIO_DIR}",
            "sandbox_root": None,
            "enable_studio": True,
        },
        "storage": {
            "profile": "${STORAGE_PROFILE}",
            "mode": "${STORAGE_MODE}",
            "event_store_backend": "${EVENT_STORE_BACKEND}",
            "run_store_backend": "${RUN_STORE_BACKEND}",
            "session_store_backend": "${SESSION_STORE_BACKEND}",
            "session_lock_backend": "${SESSION_LOCK_BACKEND}",
            "session_lease_ttl_s": "${SESSION_LEASE_TTL_S:-30}",
            "postgres_dsn": "${POSTGRES_DSN:-${DATABASE_URL}}",
            "postgres_schema": "${POSTGRES_SCHEMA:-public}",
            "postgres_schema_policy": "${POSTGRES_SCHEMA_POLICY:-migrate}",
            "redis_dsn": "${REDIS_DSN}",
            "mysql_dsn": "${MYSQL_DSN}",
            "sql_backend_dialect": "${SQL_BACKEND_DIALECT:-auto}",
            "redis_namespace": "${REDIS_NAMESPACE:-anyagent}",
            "event_store_retention_s": "${EVENT_STORE_RETENTION_S:-7200}",
            "replay_event_store_retention_s": "${REPLAY_EVENT_STORE_RETENTION_S:-3600}",
            "run_store_retention_s": "${RUN_STORE_RETENTION_S:-7200}",
            "session_store_retention_s": "${SESSION_STORE_RETENTION_S:-86400}",
            "rollout_root_dir": "${ROLLOUT_ROOT_DIR}",
            "rollout_rotate_max_bytes": "${ROLLOUT_ROTATE_MAX_BYTES:-0}",
            "rollout_rotate_max_age_seconds": "${ROLLOUT_ROTATE_MAX_AGE_SECONDS:-0}",
            "rollout_rotate_keep_files": "${ROLLOUT_ROTATE_KEEP_FILES:-16}",
        },
        "credentials": {
            "backend": "${MCP_CREDENTIAL_STORE_BACKEND:-none}",
            "file": {"root": "${MCP_CREDENTIAL_STORE_FILE_ROOT:-.anyagent/credentials}"},
            "db": {
                "dsn": "${CREDENTIAL_POSTGRES_DSN}",
                "schema": "${CREDENTIAL_POSTGRES_SCHEMA:-public}",
                "encryption_key": "${CREDENTIAL_ENCRYPTION_KEY}",
                "create_schema": "${CREDENTIAL_DB_CREATE_SCHEMA:-false}",
            },
            "vault": {
                "addr": "${VAULT_ADDR}",
                "token": "${VAULT_TOKEN}",
                "mount": "${VAULT_MOUNT:-secret}",
                "credential_root_path": "${VAULT_CREDENTIAL_ROOT_PATH:-anyagent/credentials}",
            },
            "infisical": {
                "host": "${INFISICAL_HOST:-https://app.infisical.com}",
                "client_id": "${INFISICAL_UNIVERSAL_AUTH_CLIENT_ID}",
                "client_secret": "${INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET}",
                "token": "${INFISICAL_TOKEN}",
                "project_id": "${INFISICAL_PROJECT_ID}",
                "environment": "${INFISICAL_ENVIRONMENT}",
                "cache_ttl_seconds": "${INFISICAL_CACHE_TTL_SECONDS:-60}",
                "credential_root_path": "${INFISICAL_CREDENTIAL_ROOT_PATH:-/anyagent/credentials}",
                "path_layout": "${INFISICAL_PATH_LAYOUT:-scoped}",
            },
            "runtime_env": [],
        },
        "sandbox": {
            "allow": "${ALLOW_SANDBOX:-false}",
            "backend": "${SANDBOX_BACKEND:-auto}",
            "isolation_mode": "${SANDBOX_ISOLATION_MODE:-disabled}",
            "workspace_root": "${SANDBOX_WORKSPACE_ROOT:-/workspace}",
            "filesystem_persistence_mode": "${SANDBOX_FILESYSTEM_PERSISTENCE_MODE:-ephemeral}",
            "hot_idle_ttl_s": "${SANDBOX_HOT_IDLE_TTL_S:-900}",
            "cold_retention_s": "${SANDBOX_COLD_RETENTION_S:-604800}",
            "max_snapshot_bytes": "${SANDBOX_MAX_SNAPSHOT_BYTES:-5368709120}",
            "opensandbox": {
                "base_url": "${OPENSANDBOX_BASE_URL}",
                "api_key": "${OPENSANDBOX_API_KEY}",
                "image": "${OPENSANDBOX_IMAGE:-ubuntu:24.04}",
                "timeout_s": "${OPENSANDBOX_TIMEOUT_S:-3600}",
                "cpu_limit": "${OPENSANDBOX_CPU_LIMIT:-1000m}",
                "memory_limit": "${OPENSANDBOX_MEMORY_LIMIT:-1Gi}",
                "proxy_port": "${OPENSANDBOX_PROXY_PORT:-44772}",
            },
            "metadata_backend": "${WORKSPACE_METADATA_BACKEND:-auto}",
            "metadata_root_dir": "${WORKSPACE_METADATA_ROOT_DIR}",
            "lease_backend": "${WORKSPACE_LEASE_BACKEND:-auto}",
            "lease_namespace": "${WORKSPACE_LEASE_NAMESPACE:-anyagent-tool-runtime}",
            "lease_ttl_ms": "${WORKSPACE_LEASE_TTL_MS:-60000}",
            "lease_wait_timeout_ms": "${WORKSPACE_LEASE_WAIT_TIMEOUT_MS:-2000}",
            "snapshot_backend": "${WORKSPACE_SNAPSHOT_BACKEND:-auto}",
            "snapshot_root_dir": "${WORKSPACE_SNAPSHOT_ROOT_DIR}",
            "snapshot_s3_endpoint": "${WORKSPACE_SNAPSHOT_S3_ENDPOINT}",
            "snapshot_s3_access_key": "${WORKSPACE_SNAPSHOT_S3_ACCESS_KEY}",
            "snapshot_s3_secret_key": "${WORKSPACE_SNAPSHOT_S3_SECRET_KEY}",
            "snapshot_s3_bucket": "${WORKSPACE_SNAPSHOT_S3_BUCKET:-anyagent-workspaces}",
            "snapshot_s3_secure": "${WORKSPACE_SNAPSHOT_S3_SECURE:-false}",
            "snapshot_s3_region": "${WORKSPACE_SNAPSHOT_S3_REGION}",
        },
        "plugins": {
            "roots": "${PLUGIN_ROOTS}",
            "fail_open": False,
        },
        "observability": {
            "log_format": "${LOG_FORMAT:-text}",
            "log_level": "${LOG_LEVEL:-INFO}",
            "http_url": "${OBSERVABILITY_HTTP_URL}",
            "http_headers": "${OBSERVABILITY_HTTP_HEADERS}",
            "replay_stdout": "${REPLAY_OBSERVABILITY_STDOUT}",
            "replay_file": "${REPLAY_OBSERVABILITY_FILE}",
        },
        "alerts": {
            "webhook_url": "${ALERT_WEBHOOK_URL}",
            "webhook_format": "${ALERT_WEBHOOK_FORMAT:-json}",
            "webhook_headers": "${ALERT_WEBHOOK_HEADERS}",
        },
        "tool_runtime": {
            "base_url": "${TOOL_RUNTIME_BASE_URL}",
            "internal_key": "${TOOL_RUNTIME_INTERNAL_KEY}",
            "host": "${HOST:-127.0.0.1}",
            "port": "${PORT:-8788}",
            "manifest_cache_ttl_seconds": "${MANIFEST_CACHE_TTL_SECONDS:-5}",
            "plugin_roots": "${TOOL_RUNTIME_PLUGIN_ROOTS}",
            "plugins_fail_open": "${TOOL_RUNTIME_PLUGINS_FAIL_OPEN:-false}",
            "sandbox_root_dir": "${SANDBOX_ROOT_DIR:-/tmp/anyagent-tool-runtime-sandboxes}",
            "workspace_event_backend": "${WORKSPACE_EVENT_BACKEND:-memory}",
            "workspace_event_root_dir": "${WORKSPACE_EVENT_ROOT_DIR}",
            "workspace_event_max_buffer": "${WORKSPACE_EVENT_MAX_BUFFER:-512}",
        },
    }
