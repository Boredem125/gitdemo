export function StatusPill({ status, progress }: { status: string; progress?: number }) {
  const running = status === "scanning" || status === "processing";
  return (
    <span className={`pill pill-${status}`}>
      {status}
      {running && progress !== undefined ? ` ${Math.round(progress * 100)}%` : ""}
    </span>
  );
}

export function Bar({ value }: { value: number }) {
  return (
    <div className="bar" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      <div style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  );
}
