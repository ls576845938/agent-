import {useState} from 'react';

export function ErrorBoundary({children, fallback}: {children?: unknown; fallback?: unknown}) {
  const [hasError, setHasError] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  if (hasError) {
    return fallback ?? (
      <div style={{padding: '2rem', textAlign: 'center', color: '#ef4444'}}>
        <h3>Something went wrong</h3>
        <pre style={{fontSize: '0.85rem', opacity: 0.7}}>{error?.message}</pre>
        <button onClick={() => { setHasError(false); setError(null); }} style={{marginTop: '1rem', padding: '0.5rem 1rem', cursor: 'pointer'}}>
          Try Again
        </button>
      </div>
    );
  }
  return children;
}
