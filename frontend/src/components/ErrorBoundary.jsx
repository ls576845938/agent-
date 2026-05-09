import React from 'react';

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error('ErrorBoundary caught:', error.message, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return React.createElement('div', {
        style: { padding: '2rem', textAlign: 'center', color: '#ef4444' }
      },
        React.createElement('h3', null, 'Something went wrong'),
        React.createElement('pre', {
          style: { fontSize: '0.85rem', opacity: 0.7, whiteSpace: 'pre-wrap' }
        }, this.state.error?.message),
        React.createElement('button', {
          onClick: () => this.setState({ hasError: false, error: null }),
          style: {
            marginTop: '1rem', padding: '0.5rem 1rem', cursor: 'pointer',
            background: 'rgba(255,255,255,0.1)', color: '#e2e8f0',
            border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4,
          }
        }, 'Try Again')
      );
    }
    return this.props.children;
  }
}
