/**
 * AnyAgent Studio Design System
 *
 * 高密度数据控制台核心组件库。所有组件使用 `ds-` 前缀样式，
 * 与现有页面样式隔离，供 Phase 2 起逐页面迁移采用。
 *
 * 设计参考: docs/architecture/control-plane/studio-ui-optimization-plan.md
 */
export { StatusBadge, normalizeStatus } from "./StatusBadge";
export type { BadgeStatus } from "./StatusBadge";
export { StatStrip } from "./StatStrip";
export type { StatItem, StatTone } from "./StatStrip";
export { CompactTable } from "./CompactTable";
export type { CompactColumn, ColumnAlign } from "./CompactTable";
export { CollapsibleSection } from "./CollapsibleSection";
export { Skeleton, Spinner, Progress } from "./LoadingStates";
export { ErrorBanner, EmptyState, useToast } from "./Feedback";
