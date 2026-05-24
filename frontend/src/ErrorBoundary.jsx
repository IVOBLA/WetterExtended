// ErrorBoundary.jsx — React Error-Boundary für WetterExtended Admin-Panel
// Fängt JS-Fehler in Child-Komponenten ab und zeigt lesbaren Fallback.

import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null, info: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, info) {
    this.setState({ info })
    console.error('[ErrorBoundary]', error, info?.componentStack)
  }

  render() {
    if (!this.state.hasError) return this.props.children

    const msg = this.state.error?.message || 'Unbekannter Fehler'
    const stack = this.state.info?.componentStack || ''

    return (
      <div style={{
        margin: '2rem auto',
        maxWidth: 640,
        padding: '1.5rem',
        background: '#fff5f5',
        border: '1px solid #fc8181',
        borderRadius: 8,
        fontFamily: 'monospace',
      }}>
        <h2 style={{ color: '#c53030', marginTop: 0 }}>
          ⚠ Seitenfehler
        </h2>
        <p style={{ color: '#742a2a' }}>{msg}</p>
        <button
          onClick={() => this.setState({ hasError: false, error: null, info: null })}
          style={{
            background: '#e53e3e',
            color: '#fff',
            border: 'none',
            padding: '0.4rem 1rem',
            borderRadius: 4,
            cursor: 'pointer',
            marginBottom: '1rem',
          }}
        >
          Erneut versuchen
        </button>
        {stack && (
          <details style={{ fontSize: '0.75rem', color: '#9b2c2c' }}>
            <summary>Technische Details</summary>
            <pre style={{ whiteSpace: 'pre-wrap', overflowX: 'auto' }}>{stack}</pre>
          </details>
        )}
      </div>
    )
  }
}
