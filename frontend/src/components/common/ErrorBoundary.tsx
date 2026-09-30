import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCw, Home, ChevronDown, ChevronRight, Copy, Check } from "lucide-react";
import { logger } from "../../lib/logger";

interface Props {
  children: ReactNode;
  variant?: "fullscreen" | "card";
  title?: string;
  onReset?: () => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
  showDetails: boolean;
  copied: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  override state: State = {
    hasError: false,
    error: null,
    errorInfo: null,
    showDetails: false,
    copied: false,
  };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  override componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    this.setState({ errorInfo });
    logger.error("React ErrorBoundary caught an unhandled exception", error, {
      componentStack: errorInfo.componentStack,
    });
  }

  handleReset = (): void => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
      showDetails: false,
      copied: false,
    });
    this.props.onReset?.();
  };

  handleCopy = async (): Promise<void> => {
    const errorText = [
      `Error: ${this.state.error?.name ?? "Unknown"}: ${this.state.error?.message ?? ""}`,
      `Timestamp: ${new Date().toISOString()}`,
      `URL: ${window.location.href}`,
      `Component Stack:`,
      this.state.errorInfo?.componentStack ?? "N/A",
    ].join("\n");

    try {
      await navigator.clipboard.writeText(errorText);
      this.setState({ copied: true });
      setTimeout(() => this.setState({ copied: false }), 2000);
    } catch {
      // Fallback if clipboard API is restricted
    }
  };

  override render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    const { variant = "card", title } = this.props;
    const isFullscreen = variant === "fullscreen";

    const content = (
      <div
        role="alert"
        className={`flex flex-col items-center text-center ${
          isFullscreen
            ? "max-w-md w-full mx-auto p-8 rounded-2xl border border-line bg-surface shadow-pop"
            : "w-full max-w-2xl mx-auto p-6 my-8 rounded-xl border border-line bg-surface shadow-card"
        }`}
      >
        <div className="w-12 h-12 rounded-xl bg-danger/10 border border-danger/20 flex items-center justify-center text-danger mb-4">
          <AlertTriangle size={24} />
        </div>

        <h2 className="text-lg font-semibold text-fg">
          {title ?? (isFullscreen ? "Application Error" : "Something went wrong")}
        </h2>

        <p className="text-xs text-fg-subtle mt-1.5 max-w-sm">
          {this.state.error?.message ||
            "An unexpected error occurred. Your active session is preserved."}
        </p>

        <div className="flex flex-wrap items-center justify-center gap-2.5 mt-5">
          <button
            type="button"
            onClick={this.handleReset}
            className="btn btn-primary inline-flex items-center gap-1.5 text-xs py-1.5 px-3.5"
          >
            <RefreshCw size={13} />
            Try again
          </button>

          <a
            href="/"
            className="btn btn-secondary inline-flex items-center gap-1.5 text-xs py-1.5 px-3.5"
          >
            <Home size={13} />
            Return to dashboard
          </a>
        </div>

        {/* Technical details toggle */}
        <div className="w-full mt-6 pt-4 border-t border-line text-left">
          <button
            type="button"
            onClick={() => this.setState((prev) => ({ showDetails: !prev.showDetails }))}
            className="inline-flex items-center gap-1 text-[11px] font-medium text-fg-subtle hover:text-fg transition-colors"
          >
            {this.state.showDetails ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            <span>Technical diagnostics</span>
          </button>

          {this.state.showDetails && (
            <div className="mt-2.5 p-3 rounded-lg bg-surface-sunken border border-line text-[11px] font-mono text-fg-subtle relative overflow-hidden">
              <div className="flex items-center justify-between mb-2 pb-1.5 border-b border-line">
                <span className="text-[10px] uppercase font-semibold text-danger">
                  {this.state.error?.name || "Error"}
                </span>
                <button
                  type="button"
                  onClick={this.handleCopy}
                  className="inline-flex items-center gap-1 text-[10px] text-fg-subtle hover:text-fg hover:underline cursor-pointer"
                >
                  {this.state.copied ? <Check size={11} className="text-success" /> : <Copy size={11} />}
                  <span>{this.state.copied ? "Copied" : "Copy error"}</span>
                </button>
              </div>

              <div className="max-h-48 overflow-y-auto whitespace-pre-wrap break-all leading-relaxed">
                <p className="font-semibold text-fg mb-1">{this.state.error?.message}</p>
                <p className="opacity-75">{this.state.errorInfo?.componentStack || "No stack trace available."}</p>
              </div>
            </div>
          )}
        </div>
      </div>
    );

    if (isFullscreen) {
      return (
        <div className="min-h-screen w-full flex items-center justify-center p-4 bg-canvas">
          {content}
        </div>
      );
    }

    return content;
  }
}
