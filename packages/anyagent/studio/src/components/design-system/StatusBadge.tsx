import { ReactNode } from "react";

export type BadgeStatus = "success" | "error" | "warning" | "neutral" | "info" | "running";

const STATUS_LABEL: Record<BadgeStatus, string> = {
  success: "Success",
  error: "Error",
  warning: "Warning",
  neutral: "Pending",
  info: "Info",
  running: "Running",
};

type StatusBadgeProps = {
  status: BadgeStatus;
  children?: ReactNode;
  /** 是否显示状态圆点，默认 true */
  dot?: boolean;
  className?: string;
};

/** 紧凑状态徽章，替代大尺寸彩色标签 */
export function StatusBadge({ status, children, dot = true, className }: StatusBadgeProps) {
  return (
    <span className={`ds-badge ds-badge--${status} ${className ?? ""}`}>
      {dot ? <span className="ds-badge-dot" aria-hidden="true" /> : null}
      {children ?? STATUS_LABEL[status]}
    </span>
  );
}

/** 将任意状态字符串归一化为 BadgeStatus，便于消费 run/tool 状态 */
export function normalizeStatus(status: string | undefined | null): BadgeStatus {
  if (!status) return "neutral";
  const value = status.toLowerCase();
  if (["completed", "success", "succeeded", "ok", "passed"].includes(value)) return "success";
  if (["failed", "error", "errored"].includes(value)) return "error";
  if (["cancelled", "canceled", "timeout", "timed_out", "warning", "warn"].includes(value)) return "warning";
  if (["running", "streaming", "in_progress", "pending"].includes(value)) return "running";
  if (["denied", "blocked"].includes(value)) return "warning";
  return "neutral";
}
