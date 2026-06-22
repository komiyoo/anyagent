import { ReactNode } from "react";
import { AlertTriangle, RotateCw } from "lucide-react";
import { useToastStore } from "../../stores/toastStore";

type ErrorBannerProps = {
  title?: string;
  message: ReactNode;
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
};

/** Inline 错误横幅，带可选重试按钮。用于 API 错误场景 */
export function ErrorBanner({ title = "Something went wrong", message, onRetry, retryLabel = "Retry", className }: ErrorBannerProps) {
  return (
    <div className={`ds-error-banner ${className ?? ""}`} role="alert">
      <AlertTriangle size={16} className="ds-error-banner-icon" aria-hidden="true" />
      <div className="ds-error-banner-body">
        <strong className="ds-error-banner-title">{title}</strong>
        <span className="ds-error-banner-message">{message}</span>
      </div>
      {onRetry ? (
        <button type="button" className="ds-error-banner-retry" onClick={onRetry}>
          <RotateCw size={13} />
          {retryLabel}
        </button>
      ) : null}
    </div>
  );
}

type EmptyStateProps = {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
  className?: string;
};

/** 空态占位，带主操作入口 */
export function EmptyState({ icon, title, description, action, compact = false, className }: EmptyStateProps) {
  return (
    <div className={`ds-empty-state ${compact ? "ds-empty-state--compact" : ""} ${className ?? ""}`}>
      {icon ? <span className="ds-empty-state-icon">{icon}</span> : null}
      <strong className="ds-empty-state-title">{title}</strong>
      {description ? <span className="ds-empty-state-desc">{description}</span> : null}
      {action ? <div className="ds-empty-state-action">{action}</div> : null}
    </div>
  );
}

/**
 * useToast — 基于全局 toastStore 的便捷 hook。
 * 复用 ToastViewport 渲染，调用方无需自建通知容器。
 */
export function useToast() {
  const showToast = useToastStore((state) => state.showToast);
  return {
    success: (message: string) => showToast("success", message),
    error: (message: string) => showToast("error", message),
    info: (message: string) => showToast("info", message),
  };
}
