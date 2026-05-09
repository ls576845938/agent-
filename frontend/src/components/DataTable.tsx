import {useState} from 'react';

export interface Column {
  key: string;
  label: string;
  sortable?: boolean;
  render?: (value: unknown, row: Record<string, unknown>) => unknown;
  width?: string;
}

const headerStyle = {
  textAlign: 'left' as const,
  padding: '10px 8px',
  borderBottom: '1px solid rgba(255,255,255,0.1)',
  color: '#94a3b8',
  fontWeight: 600,
  userSelect: 'none' as const,
};

const cellStyle = {
  padding: '8px',
  borderBottom: '1px solid rgba(255,255,255,0.04)',
  verticalAlign: 'middle' as const,
};

export function DataTable({columns, data, onRowClick, emptyText}: {
  columns: Column[];
  data: Record<string, unknown>[];
  onRowClick?: (row: Record<string, unknown>) => void;
  emptyText?: string;
}) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir(prev => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  const sortedData = sortKey
    ? [...data].sort((a: any, b: any) => {
        const av = a[sortKey];
        const bv = b[sortKey];
        if (av == null) return 1;
        if (bv == null) return -1;
        if (av < bv) return sortDir === 'asc' ? -1 : 1;
        if (av > bv) return sortDir === 'asc' ? 1 : -1;
        return 0;
      })
    : data;

  if (data.length === 0) {
    return <div style={{padding: 24, textAlign: 'center', color: '#94a3b8'}}>{emptyText || '暂无数据'}</div>;
  }

  return (
    <div style={{overflowX: 'auto'}}>
      <table style={{width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem'}}>
        <thead>
          <tr>
            {columns.map(col => (
              <th
                key={col.key}
                onClick={col.sortable ? () => handleSort(col.key) : undefined}
                style={{
                  ...headerStyle,
                  cursor: col.sortable ? 'pointer' : undefined,
                  width: col.width || undefined,
                }}
              >
                {col.label}
                {sortKey === col.key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedData.map((row, i) => {
            const rowKey = (row.id || row.candidate_id || row.experiment_id || i) as string | number;
            return (
              <tr
                key={rowKey}
                onClick={() => onRowClick?.(row)}
                style={{cursor: onRowClick ? 'pointer' : undefined}}
                onMouseEnter={(e: any) => { if (onRowClick) e.currentTarget.style.background = 'rgba(255,255,255,0.05)'; }}
                onMouseLeave={(e: any) => { if (onRowClick) e.currentTarget.style.background = ''; }}
              >
                {columns.map(col => (
                  <td key={col.key} style={cellStyle}>
                    {col.render ? col.render(row[col.key], row) : String(row[col.key] ?? '')}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
