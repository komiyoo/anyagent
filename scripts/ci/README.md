# CI Scripts

本目录用于承载可复用的 CI 执行脚本，避免把所有命令堆在 workflow yaml 里。

当前脚本：

1. `run_docs_guardrails.sh`：文档护栏与进度可读性检查。
2. `run_offline_smokes.sh`：离线 smoke 集合（不依赖上游模型 API）。
