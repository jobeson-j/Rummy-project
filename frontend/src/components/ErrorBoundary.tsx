import { Component, type ReactNode } from 'react';

// Catches rendering crashes and shows a readable message instead of a blank page.
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  // Stores the error so the fallback screen is shown.
  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  // Shows the game, or the error message if something crashed.
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="start">
        <h1 className="start-title" style={{ fontSize: 44 }}>Something went wrong</h1>
        <p className="start-sub">
          {this.state.error.message}. If you just updated the code, restart the backend with
          <code> uvicorn app.main:app --reload --port 8000</code>, then reload this page.
        </p>
        <button type="button" className="btn btn-primary btn-big" onClick={() => window.location.reload()}>
          Reload the game
        </button>
      </main>
    );
  }
}
