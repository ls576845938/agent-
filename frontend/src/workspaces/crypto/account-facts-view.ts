// Presentation only. Never feeds operator authorization or order decisions.
export function finiteAccountNumber(value: unknown): number | null {
  if (!['number','string'].includes(typeof value) || String(value).trim() === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function accountFactsView(snapshot: unknown, reconciled: boolean) {
  const row = snapshot && typeof snapshot === 'object' ? snapshot as Record<string, unknown> : {};
  const usable = reconciled && typeof row.captured_at_utc === 'string'
    && Number.isFinite(Date.parse(row.captured_at_utc));
  const count = (value: unknown) => usable && Array.isArray(value) ? String(value.length) : '未知';
  let position = '未知 · 账户事实缺失';
  if (usable && Array.isArray(row.positions) && row.positions.every(item => item &&
    ['number','string'].includes(typeof item.contracts) && String(item.contracts).trim() !== '' &&
    Number.isFinite(Number(item.contracts)) && ['long','short','net'].includes(item.position_side))) {
    const held = row.positions.filter(item => Number(item.contracts) !== 0);
    position = held.length ? held.map(item => `${item.position_side.toUpperCase()} ${item.contracts} 张`).join(' / ') : 'FLAT';
  }
  const protectionCount = count(row.pending_algo_orders);
  return {usable, position, pendingOrders:count(row.pending_orders),
    protection:protectionCount === '未知' ? '保护单未知' : `保护单 ${protectionCount} 个`,
    orders:count(row.orders), fills:count(row.fills), fundingBills:count(row.bills)};
}
