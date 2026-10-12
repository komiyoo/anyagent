<!--
---
doc_kind: architecture
status: stable
tags: ["config", "workspace", "env", "adr"]
summary: 工作区只保留一个 anyagent.yaml，取值只使用 ${VAR} 插值，使只设环境变量的部署继续可用。
req: ["requirements.md#req-0-2"]
---
-->

# ADR: 单一工作区配置文件与插值

Status: Accepted
Date: 2026-10-12
Scope: 工作区配置、CLI、凭据后端、开箱即用启动

## 背景

0.4 的同一项设置可以写在多处，并且有三种取值方式：

- 模型同时出现在 `agent.yaml` 的 `model.provider` / `api_key_env` / `base_url_env` 和仓库根目录的 `models.yaml`。
- 凭据后端同时出现在进程环境变量、`.anyagent/secrets.yaml` 的 `mcp_credentials` 和 `credential_vault`。
- 每个字段可以写字面量、写 `*_env`，而 `models.yaml` 又支持 `${VAR}`。
- `.env` 加载和 `${VAR}` 插值各有多份实现，行为不一致。
- `anyagent init` 与 `anyagent config init` 是两套初始化。没有 `.anyagent/agents/` 时服务直接失败。

结果是同一条配置要写两遍，只导出环境变量的部署还要再对一遍 yaml。

## 决策

1. 工作区设置只放在 `.anyagent/anyagent.yaml`。分段是 `models`、`server`、`storage`、`credentials`、`sandbox`、`plugins`、`observability`、`alerts`、`tool_runtime`。省略的字段使用内置默认。`models.yaml` 与 `secrets.yaml` 不再读取。
2. 取值只有 `${VAR}` 和 `${VAR:-default}`，由 `packages/anyagent/src/anyagent/config/env.py` 的 `interpolate` 实现。删除全部 `*_env` 配置字段。运行时设置从 `load_effective_config` 返回的 `EffectiveConfig` 读取，不在各调用点直接 `os.getenv`。
3. 内置默认本身引用约定环境变量（`OPENAI_API_KEY`、`POSTGRES_DSN`、`API_KEY` 等）。因此只设环境变量、不写 yaml 仍然可用。yaml 只写与默认不同的部分。凭据后端的环境变量是 `CREDENTIAL_BACKEND`、`CREDENTIAL_WRITABLE`、`CREDENTIAL_FILE_ROOT`。可写性是 `credentials.writable`，后端名不带 `-write`。
4. 优先级：CLI 参数 > workspace `.anyagent/anyagent.yaml` > user `~/.anyagent/anyagent.yaml` > system `/etc/anyagent/anyagent.yaml` > 内置默认。workspace 不能压过 system 或 user 已经设置的 `sandbox.mode` 和 `storage`。
5. `.env` 与 `.env.local` 只由 `load_dotenv` 读一次。不覆盖进程里已有的变量。`.env.local` 覆盖 `.env`。
6. `agent.yaml` 的 `model` 只引用别名或 `provider:model`。所有字段可选。没有 agent 目录时使用内置 `main`。`OPENAI_API_KEY=... anyagent serve` 在空目录可以启动。
7. 随包插件 `chatwoot` 与 `lifecycle_echo` 通过 `plugins.builtin` 显式启用。`anyagent serve` 在非 loopback host 且没有 API key 时拒绝启动。

操作说明见 [getting-started.md](../../guides/getting-started.md) 与 [deployment.md](../../guides/deployment.md)。

### 不选方案

1. **保留 `models.yaml` 与 `secrets.yaml`，在加载时合并进新文件。** 不选。两套文件会继续分叉，调用方无法知道哪一份生效。
2. **保留 `*_env` 字段，同时支持 `${VAR}`。** 不选。一个值仍有两种写法，`config show` 无法给出唯一来源。
3. **每个子系统继续直接读环境变量。** 不选。新增设置无法出现在 `config show`，默认值和部署文档会对不上。

## 后果

- 0.5.0 是破坏性配置变更，不提供读取旧文件的兼容层。迁移对照见 [getting-started.md](../../guides/getting-started.md#8-从-04-配置迁移)。
- 只导出环境变量的部署继续工作，因为默认文档里的占位符使用原来的变量名。凭据后端三个变量改名，部署需要同步。
- 新增运行时设置时，先加到 `WorkspaceConfig` 和 `builtin_defaults`，再让 server 从 `EffectiveConfig` 读取。
