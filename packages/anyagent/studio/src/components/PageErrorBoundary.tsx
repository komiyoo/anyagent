import { Component, ErrorInfo, ReactNode } from "react";

type PageErrorBoundaryProps = {
  children: ReactNode;
  title: string;
};

type PageErrorBoundaryState = {
  error: Error | null;
};

export class PageErrorBoundary extends Component<PageErrorBoundaryProps, PageErrorBoundaryState> {
  state: PageErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): PageErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Studio page failed", { error, componentStack: info.componentStack });
  }

  componentDidUpdate(previousProps: PageErrorBoundaryProps) {
    if (previousProps.title !== this.props.title && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (this.state.error) {
      return (
        <section className="page-error" role="alert">
          <h2>{this.props.title} failed to render</h2>
          <p>{this.state.error.message}</p>
        </section>
      );
    }

    return this.props.children;
  }
}
