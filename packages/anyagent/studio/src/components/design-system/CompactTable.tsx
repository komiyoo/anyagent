import { ReactNode } from "react";

export type ColumnAlign = "left" | "right" | "center";

export type CompactColumn<T> = {
  key: string;
  header: ReactNode;
  align?: ColumnAlign;
  width?: string;
  render: (row: T, index: number) => ReactNode;
};

type CompactTableProps<T> = {
  columns: CompactColumn<T>[];
  rows: T[];
  rowKey: (row: T, index: number) => string;
  onRowClick?: (row: T, index: number) => void;
  /** 当前选中行的 key，用于高亮 */
  activeRowKey?: string | null;
  empty?: ReactNode;
  /** 固定表头（需配合限定高度的滚动容器） */
  stickyHeader?: boolean;
  className?: string;
};

/**
 * CompactTable — 32px 行高的紧凑表格，替代 48px 大行。
 * 数值列用 monospace + tabular-nums，行 hover 高亮，支持点击行与空态。
 */
export function CompactTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  activeRowKey,
  empty,
  stickyHeader = false,
  className,
}: CompactTableProps<T>) {
  if (rows.length === 0 && empty) {
    return <div className={`ds-table-empty ${className ?? ""}`}>{empty}</div>;
  }

  return (
    <div className={`ds-table-wrap ${className ?? ""}`}>
      <table className="ds-table">
        <thead className={stickyHeader ? "ds-table-sticky" : undefined}>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className={col.align && col.align !== "left" ? `ds-th-${col.align}` : undefined}
                style={col.width ? { width: col.width } : undefined}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const key = rowKey(row, index);
            const isActive = activeRowKey != null && activeRowKey === key;
            return (
            <tr
              key={key}
              className={[onRowClick ? "ds-table-clickable" : null, isActive ? "ds-row-active" : null].filter(Boolean).join(" ") || undefined}
              aria-selected={isActive || undefined}
              onClick={onRowClick ? () => onRowClick(row, index) : undefined}
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={col.align && col.align !== "left" ? `ds-td-${col.align}` : undefined}
                >
                  {col.render(row, index)}
                </td>
              ))}
            </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
