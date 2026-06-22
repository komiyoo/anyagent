import { ReactNode } from "react";

export type StatTone = "default" | "error" | "warning" | "success" | "accent";

export type StatItem = {
  label: string;
  value: ReactNode;
  /** 次级说明，展示在值右侧 */
  hint?: ReactNode;
  tone?: StatTone;
  title?: string;
};

type StatStripProps = {
  stats: StatItem[];
  className?: string;
};

/**
 * StatStrip — 单行紧凑指标条，替代独立 Metric Card。
 * 32px 高度，横向排列，移动端自动堆叠。值用 monospace + tabular-nums。
 */
export function StatStrip({ stats, className }: StatStripProps) {
  return (
    <div className={`ds-stat-strip ${className ?? ""}`}>
      {stats.map((stat, index) => (
        <div
          className="ds-stat"
          key={`${stat.label}-${index}`}
          title={stat.title ?? (stat.hint ? `${stat.label} · ${stat.hint}` : stat.label)}
        >
          <span className="ds-stat-label">{stat.label}</span>
          <span className={`ds-stat-value${stat.tone && stat.tone !== "default" ? ` ds-stat-value--${stat.tone}` : ""}`}>
            {stat.value}
          </span>
          {stat.hint ? <span className="ds-stat-hint">{stat.hint}</span> : null}
        </div>
      ))}
    </div>
  );
}
