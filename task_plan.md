# 任务计划

## 目标
- 对照文档检查设计与实现不一致处
- 以文档为准持续选取最小可交付缺口推进实现

## 阶段
1. [completed] 重读凭证解析契约
2. [completed] 定位第七条实现偏差
3. [completed] 补实现与 smoke
4. [completed] 运行验证并回写

## 本轮结论
- 已修复第七条明确偏差：`AuthRef.kind` 之前在主执行链路中没有真正参与匹配，错误 kind 也能解析到凭证。
- 现已在 CredentialStore 与 Tool Runtime 双侧补上 kind 校验，并用离线 smoke 固化“错 kind 不命中”的行为。

## 后续候选
- 若继续推进，可转查 MCP 凭证解析与 Tool Runtime 解析是否仍有字段口径不一致，或继续细化审计字段完整性（who/source）。
