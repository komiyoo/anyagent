type PageSkeletonProps = {
  title: string;
};

export function PageSkeleton({ title }: PageSkeletonProps) {
  return (
    <div className="page-skeleton" aria-label={`${title} loading`} aria-live="polite">
      <div className="skeleton-band">
        <span />
        <strong />
        <em />
      </div>
      <div className="skeleton-grid">
        <div className="skeleton-panel">
          <span />
          <strong />
          <p />
          <p />
          <p />
        </div>
        <div className="skeleton-panel">
          <span />
          <strong />
          <p />
          <p />
          <p />
        </div>
      </div>
    </div>
  );
}
