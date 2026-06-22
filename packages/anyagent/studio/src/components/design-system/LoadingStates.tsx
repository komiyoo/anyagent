import { CSSProperties } from "react";

type SkeletonVariant = "line" | "text" | "panel" | "table" | "circle";

type SkeletonProps = {
  variant?: SkeletonVariant;
  width?: number | string;
  height?: number | string;
  rows?: number;
  className?: string;
};

/** Skeleton 占位，首次加载时保持布局稳定 */
export function Skeleton({ variant = "line", width, height, rows = 3, className }: SkeletonProps) {
  const style: CSSProperties = {};
  if (width !== undefined) style.width = typeof width === "number" ? `${width}px` : width;
  if (height !== undefined) style.height = typeof height === "number" ? `${height}px` : height;

  if (variant === "table") {
    return (
      <div className={`ds-skeleton-table ${className ?? ""}`} aria-hidden="true">
        {Array.from({ length: rows }).map((_, i) => (
          <div className="ds-skeleton-row" key={i}>
            <span className="ds-skeleton-bar" style={{ width: "30%" }} />
            <span className="ds-skeleton-bar" style={{ width: "45%" }} />
            <span className="ds-skeleton-bar" style={{ width: "20%" }} />
          </div>
        ))}
      </div>
    );
  }

  if (variant === "panel") {
    return (
      <div className={`ds-skeleton-panel ${className ?? ""}`} aria-hidden="true">
        <span className="ds-skeleton-bar" style={{ width: "40%", height: 16 }} />
        <span className="ds-skeleton-bar" style={{ width: "80%", height: 14 }} />
        <span className="ds-skeleton-bar" style={{ width: "65%", height: 14 }} />
      </div>
    );
  }

  if (variant === "circle") {
    return <span className={`ds-skeleton-circle ${className ?? ""}`} style={style} aria-hidden="true" />;
  }

  if (variant === "text") {
    return (
      <div className={`ds-skeleton-text ${className ?? ""}`} aria-hidden="true">
        {Array.from({ length: rows }).map((_, i) => (
          <span key={i} className="ds-skeleton-bar" style={{ width: i === rows - 1 ? "60%" : "100%" }} />
        ))}
      </div>
    );
  }

  return <span className={`ds-skeleton-bar ${className ?? ""}`} style={style} aria-hidden="true" />;
}

type SpinnerProps = {
  size?: number;
  className?: string;
  label?: string;
};

/** Spinner 旋转指示器，用于刷新/重新加载场景 */
export function Spinner({ size = 16, className, label = "Loading" }: SpinnerProps) {
  return (
    <span
      className={`ds-spinner ${className ?? ""}`}
      style={{ width: size, height: size }}
      role="status"
      aria-label={label}
    />
  );
}

type ProgressProps = {
  value: number;
  max?: number;
  className?: string;
  label?: string;
};

/** Progress 进度条，用于长时间操作 */
export function Progress({ value, max = 100, className, label }: ProgressProps) {
  const ratio = max > 0 ? value / max : 0;
  const pct = Math.max(0, Math.min(100, ratio * 100));
  return (
    <div
      className={`ds-progress ${className ?? ""}`}
      role="progressbar"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-label={label}
    >
      <div className="ds-progress-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}
