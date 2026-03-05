# Acceptance 文档索引

本目录用于“可复现、可验收”的最小闭环：一条命令/一组步骤，验证某个对外契约或关键链路。

建议阅读顺序：

1) [acceptance-responses-api.md](acceptance-responses-api.md)：Responses API 兼容面（HTTP + SSE）的最小验收
2) [acceptance-gateway-e2e.md](acceptance-gateway-e2e.md)：Gateway 端到端链路验收（如适用）
3) [acceptance-demo-customization.md](acceptance-demo-customization.md)：Demo/应用级定制化实操与回归清单

约定：

- 新增验收文档时，用 `acceptance-<topic>.md` 命名，并把入口挂到本 `README.md`。
