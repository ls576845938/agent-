export function LoadingSpinner({ text = 'Loading...' }: { text?: string }) {
  return (
    <div style={{display:'flex',alignItems:'center',justifyContent:'center',gap:'0.75rem',padding:'2rem'}}>
      <div className="spinner" />
      <span style={{opacity:0.7}}>{text}</span>
      <style>{`
        .spinner {
          width: 24px; height: 24px;
          border: 3px solid rgba(255,255,255,0.1);
          border-top-color: var(--accent, #6366f1);
          border-radius: 50%;
          animation: spin 0.6s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
