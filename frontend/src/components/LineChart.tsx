function createLinePath(points: Array<{time: number; value: number}>, width: number, height: number): string {
  if (points.length === 0) return '';
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return points
    .map((point, index) => {
      const x = (index / Math.max(1, points.length - 1)) * width;
      const y = height - ((point.value - min) / range) * height;
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(' ');
}

export type LineChartProps = {
  title: string;
  points: Array<{time: number; value: number}>;
  accentClass: string;
};

export default function LineChart({title, points, accentClass}: LineChartProps) {
  const width = 480;
  const height = 120;
  const path = createLinePath(points, width, height);
  const lastValue = points.length > 0 ? points[points.length - 1].value : null;
  const firstValue = points.length > 0 ? points[0].value : null;
  const change = firstValue && lastValue && firstValue !== 0
    ? ((lastValue - firstValue) / Math.abs(firstValue) * 100).toFixed(2)
    : null;
  return (
    <article className="panel chart-panel">
      <div className="panel-header">
        <h3>{title}</h3>
        {lastValue != null && (
          <span>
            {lastValue.toLocaleString('en-US', {maximumFractionDigits: 4})}
            {change !== null ? ` (${Number(change) >= 0 ? '+' : ''}${change}%)` : ''}
          </span>
        )}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className={`line-chart ${accentClass}`}>
        <path d={path} fill="none" stroke="currentColor" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
      </svg>
    </article>
  );
}
