# Engineering 文档索引

本目录用于承载工程流程与质量体系设计（非业务架构）。

当前文档：

1. [ci-pipeline.md](ci-pipeline.md)：CI 质量门与发布（本地 git hooks、离线 gate、`main` 上构建 Python SDK 并发布到云效 Packages）

约定：

- 流程类文档优先放在本目录，避免散落到 `docs/architecture/` 根层。
- 每条流程设计都要附带“可执行命令”与“失败处理策略”。
