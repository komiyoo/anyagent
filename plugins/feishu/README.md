# Feishu plugin (reference)

本目录是 `requirements.md#req-6-2` 的 reference：演示如何通过 anyagent 插件体系将 `feishu.*` tools 注入到 Tool Runtime。

## 文件约定

- `plugin.json`：插件元信息 + `config_schema`
- `plugin.py`：入口，默认 `plugin.py:register(api)`
- `config.json`：运行时配置（建议只放 env var 名称，不要放 token 明文）

本仓库已在根目录 `.gitignore` 忽略 `plugins/**/config.json`，避免误提交敏感配置。

## 如何在 Tool Runtime 启用

1. 复制配置：

- 将 `config.example.json` 复制为 `config.json`（本地文件，不入 git）

2. 设置 token（示例：直接提供 tenant access token）：

- `export FEISHU_TENANT_ACCESS_TOKEN=...`

3. 启动 Tool Runtime：

- `cd apps/tool-runtime`
- `export TOOL_RUNTIME_PLUGIN_ROOTS=../../plugins`
- `export TOOL_RUNTIME_INTERNAL_KEY=dev`
- `uv run tool-runtime`

## 已注册的 tools

- `feishu.directory.get_chat_members(chat_id, page_size?, page_token?)`
- `feishu.doc.create(title, folder_token, content?)`（`content` 目前不支持，传入会报错）

其余能力（`doc.patch` / `drive.upload` / `perm.grant`）会以明确错误返回，留待后续按需求补齐。
