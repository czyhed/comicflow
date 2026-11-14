import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error?: Error
}

/** Catch workspace render crashes so the UI shows a retryable message instead of freezing. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = {}

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error): void {
    console.error('[workspace crashed]', error)
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children
    return (
      <div className="error-boundary" role="alert">
        <strong>工作区渲染出错，预览未丢失，请重试或刷新。</strong>
        <code>{this.state.error.message}</code>
        <button onClick={() => this.setState({ error: undefined })}>重试</button>
        <button onClick={() => window.location.reload()}>刷新页面</button>
      </div>
    )
  }
}
