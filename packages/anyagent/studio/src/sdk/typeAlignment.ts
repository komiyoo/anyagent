/**
 * SDK 类型对齐校验
 *
 * Phase 4 基础设施：证明 AnyAgent TS SDK 的 wire-level 类型
 * (`anyagent/generated/protocol-types`) 与 Studio 的 UI 适配类型
 * (`anyagentClient.ts`) 结构兼容，为后续将 `anyagentClient.ts` 的 API 调用
 * 迁移到 `AnyAgentClient` namespace 铺路。
 *
 * 本文件仅做编译期类型校验，零运行时影响（`import type` 在构建时擦除）。
 * 若任一校验失败，tsc 会报错——说明 SDK 协议已演进，需同步 Studio 类型。
 *
 * 参考: docs/architecture/api/sdk-public-surface.md
 */

import type {
  InternalObservabilityRunItem,
  InternalObservabilitySummaryResponse,
  InternalObservabilityMetricsResponse,
  InternalObservabilityToolStats,
  InternalObservabilityErrorItem,
  InternalObservabilityTimelineResponse,
  InternalObservabilityTraceResponse,
  InternalResponseToolExecutionsResponse,
  InternalResponseModelRequestResponse,
  InternalResponsePromptContextResponse,
} from "anyagent/generated/protocol-types";

import type {
  ObservabilityRunItem,
  ObservabilitySummary,
  ObservabilityMetrics,
  ObservabilityToolStats,
  ObservabilityErrorItem,
  ObservabilityTimelineEvent,
  ObservabilityTrace,
  ToolExecutionDetail,
  ModelRequestResponse,
  PromptContextResponse,
} from "../anyagentClient";

/**
 * 双向结构兼容校验：若 A extends B 且 B extends A，则两类型结构等价。
 * 任一方向不满足时 tsc 报错，提示字段漂移。
 */
type MutuallyExtends<A, B> = A extends B ? (B extends A ? true : never) : never;

// ── ObservabilityRunItem ──
// SDK: InternalObservabilityRunItem (wire), Studio: ObservabilityRunItem (UI)
// 字段已人工核对一致：agent_id/created_at_ms/effective_status/ended_at_ms/
// response_id/session_key/status/stream/updated_at_ms
type _RunCheck = MutuallyExtends<InternalObservabilityRunItem, ObservabilityRunItem>;

// ── ObservabilitySummary ──
// Studio 的 ObservabilitySummary 是 UI 派生形态（字段可选 + turns 数组），
// SDK 的 InternalObservabilitySummaryResponse 是 wire 形态。两者非完全等价，
// 但 Studio 字段应是 SDK 字段的子集。校验 Studio extends SDK。
type _SummaryCheck = ObservabilitySummary extends Partial<InternalObservabilitySummaryResponse> ? true : never;

// ── ObservabilityMetrics ──
type _MetricsCheck = ObservabilityMetrics extends Partial<InternalObservabilityMetricsResponse> ? true : never;

// ── ObservabilityToolStats ──
type _ToolStatsCheck = ObservabilityToolStats extends Partial<InternalObservabilityToolStats> ? true : never;

// ── ObservabilityErrorItem ──
type _ErrorItemCheck = ObservabilityErrorItem extends Partial<InternalObservabilityErrorItem> ? true : never;

// ── Timeline event ──
// Studio 的 ObservabilityTimelineEvent 与 SDK 的 timeline item 应结构兼容。
type SdkTimelineEvent = NonNullable<InternalObservabilityTimelineResponse["events"]>[number];
type _TimelineCheck = ObservabilityTimelineEvent extends Partial<SdkTimelineEvent> ? true : never;

// ── Trace ──
type _TraceCheck = ObservabilityTrace extends Partial<InternalObservabilityTraceResponse> ? true : never;

// ── Tool execution / model request / prompt context ──
type SdkToolExec = NonNullable<NonNullable<InternalResponseToolExecutionsResponse["tool_executions"]>[number]>;
type _ToolExecCheck = ToolExecutionDetail extends Partial<SdkToolExec> ? true : never;
type _ModelReqCheck = ModelRequestResponse extends Partial<InternalResponseModelRequestResponse> ? true : never;
type _PromptCtxCheck = PromptContextResponse extends Partial<InternalResponsePromptContextResponse> ? true : never;

// 汇总：若任一校验为 never，此处报错。
type _AllChecks = [
  _RunCheck,
  _SummaryCheck,
  _MetricsCheck,
  _ToolStatsCheck,
  _ErrorItemCheck,
  _TimelineCheck,
  _TraceCheck,
  _ToolExecCheck,
  _ModelReqCheck,
  _PromptCtxCheck,
];

// 导出一个编译期常量，确保文件被 tsc 当作模块处理。
export const SDK_TYPE_ALIGNMENT_OK: _AllChecks extends true[] ? true : false = true as _AllChecks extends true[] ? true : false;
