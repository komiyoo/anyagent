import { ReactNode, useEffect, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";

type CollapsibleSectionProps = {
  title: ReactNode;
  /** 标题右侧的计数或补充文本 */
  count?: ReactNode;
  /** 默认是否展开，默认 false（折叠） */
  defaultOpen?: boolean;
  /** 受控展开状态；传入后组件变为受控 */
  open?: boolean;
  onToggle?: (open: boolean) => void;
  /** 标题行右侧的操作区（如刷新按钮） */
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
};

/**
 * CollapsibleSection — 可折叠区块，默认折叠以节省垂直空间。
 * 支持受控/非受控，标题行带计数与操作槽。
 */
export function CollapsibleSection({
  title,
  count,
  defaultOpen = false,
  open: controlledOpen,
  onToggle,
  actions,
  children,
  className,
}: CollapsibleSectionProps) {
  const isControlled = controlledOpen !== undefined;
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const isOpen = isControlled ? controlledOpen : internalOpen;
  const summaryRef = useRef<HTMLButtonElement>(null);

  const toggle = () => {
    const next = !isOpen;
    if (!isControlled) setInternalOpen(next);
    onToggle?.(next);
  };

  // 受控模式下，defaultOpen 变化时同步内部初始态（仅一次生效场景）
  useEffect(() => {
    if (!isControlled) setInternalOpen(defaultOpen);
  }, [defaultOpen, isControlled]);

  return (
    <details className={`ds-collapsible ${isOpen ? "ds-collapsible--open" : ""} ${className ?? ""}`} open={isOpen}>
      <summary className="ds-collapsible-summary">
        <button
          ref={summaryRef}
          type="button"
          className="ds-collapsible-toggle"
          aria-expanded={isOpen}
          onClick={(event) => {
            event.preventDefault();
            toggle();
          }}
        >
          <ChevronRight size={14} className="ds-collapsible-chevron" aria-hidden="true" />
          <span className="ds-collapsible-title">{title}</span>
          {count !== undefined && count !== null ? <span className="ds-collapsible-count">{count}</span> : null}
        </button>
        {actions ? <span className="ds-collapsible-actions" onClick={(e) => e.stopPropagation()}>{actions}</span> : null}
      </summary>
      <div className="ds-collapsible-content">{children}</div>
    </details>
  );
}
