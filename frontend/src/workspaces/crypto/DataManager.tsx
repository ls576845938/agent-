import type {DatabaseStatusResponse, KlinePreviewResponse, DataSyncRunResponse, SchedulerStatusResponse} from '../../lib/view-model';
import type {ValueEvent} from '../../lib/shared-types';
import {formatIso, formatPrice} from '../../lib/utils';

type DataFormState = {
  symbol: string; interval: '1m' | '5m' | '15m' | '1h' | '4h' | '1d';
  startDate: string; endDate: string; dbPath: string;
};

interface DataManagerProps {
  dataForm: DataFormState;
  database: DatabaseStatusResponse | null;
  klinePreview: KlinePreviewResponse | null;
  syncRuns: DataSyncRunResponse[];
  scheduler: SchedulerStatusResponse | null;
  dataLoading: boolean;
  dataMessage: string;
  onChangeDataForm: (form: DataFormState) => void;
  onRefresh: () => void;
  onSync: () => void;
  onUpdateLatest: () => void;
  onStartScheduler: () => void;
  onStopScheduler: () => void;
}

export type {DataFormState};

export default function DataManager({
  dataForm, database, klinePreview, syncRuns, scheduler,
  dataLoading, dataMessage,
  onChangeDataForm, onRefresh, onSync, onUpdateLatest,
  onStartScheduler, onStopScheduler,
}: DataManagerProps) {
  return (
    <section className="panel data-panel">
      <div className="panel-header"><h2>数据管理</h2><span>{database?.initialized ? 'SQLite 已就绪' : '等待初始化'}</span></div>
      <div className="data-status-grid">
        <div><span>数据库</span><strong>{database?.exists ? '已创建' : '未创建'}</strong></div>
        <div><span>覆盖组合</span><strong>{database?.coverage.length ?? 0}</strong></div>
        <div><span>日更任务</span><strong>{scheduler?.running ? '运行中' : '停止'}</strong></div>
      </div>

      <label className="wide-field">数据库路径
        <input value={dataForm.dbPath} placeholder={database?.db_path ?? '留空使用默认库'} onChange={(e: ValueEvent) => {
          const n = {...dataForm, dbPath: e.target.value}; onChangeDataForm(n);
        }} />
      </label>

      <div className="form-grid data-form-grid">
        <label>标的<input value={dataForm.symbol} onChange={(e: ValueEvent) => onChangeDataForm({...dataForm, symbol: e.target.value.toUpperCase()})} /></label>
        <label>周期
          <select value={dataForm.interval} onChange={(e: ValueEvent) => onChangeDataForm({...dataForm, interval: e.target.value as DataFormState['interval']})}>
            {['1m', '5m', '15m', '1h', '4h', '1d'].map((i) => <option key={i} value={i}>{i}</option>)}
          </select>
        </label>
        <label>下载开始<input type="date" value={dataForm.startDate} onChange={(e: ValueEvent) => onChangeDataForm({...dataForm, startDate: e.target.value})} /></label>
        <label>下载结束<input type="date" value={dataForm.endDate} onChange={(e: ValueEvent) => onChangeDataForm({...dataForm, endDate: e.target.value})} /></label>
      </div>

      <div className="data-actions">
        <button type="button" className="secondary-button" disabled={dataLoading} onClick={onSync}>下载区间</button>
        <button type="button" className="secondary-button" disabled={dataLoading} onClick={onUpdateLatest}>更新到最新</button>
        <button type="button" className="secondary-button" disabled={dataLoading || scheduler?.running} onClick={onStartScheduler}>启动日更</button>
        <button type="button" className="secondary-button danger" disabled={dataLoading || !scheduler?.running} onClick={onStopScheduler}>停止日更</button>
      </div>

      {dataMessage ? <p className="data-message">{dataMessage}</p> : null}

      <div className="coverage-list">
        {(database?.coverage ?? []).slice(0, 4).map((item) => (
          <div key={`${item.exchange}-${item.symbol}-${item.interval}`} className="coverage-row">
            <strong>{item.symbol} {item.interval}</strong>
            <span>{item.rows.toLocaleString('en-US')} 根</span>
            <span>{formatIso(item.start)} - {formatIso(item.end)}</span>
          </div>
        ))}
      </div>

      <div className="panel-header compact-header"><h3>数据库预览</h3><button type="button" className="ghost-button" onClick={onRefresh}>刷新</button></div>
      <div className="table-scroll">
        <table className="data-table"><thead><tr><th>时间</th><th>开</th><th>高</th><th>低</th><th>收</th><th>量</th></tr></thead>
          <tbody>{(klinePreview?.rows ?? []).map((row) => (
            <tr key={row.open_time_ms}><td>{formatIso(row.time)}</td><td>{formatPrice(row.open)}</td><td>{formatPrice(row.high)}</td><td>{formatPrice(row.low)}</td><td>{formatPrice(row.close)}</td><td>{row.volume.toFixed(3)}</td></tr>
          ))}</tbody>
        </table>
      </div>

      <div className="sync-log">
        {syncRuns.map((item) => (
          <div key={item.run_id} className="sync-row">
            <span className={`status-tag ${item.status === 'completed' ? 'good' : item.status === 'failed' ? 'bad' : 'neutral'}`}>{item.status}</span>
            <span>{item.symbol} {item.interval}</span>
            <span>{item.rows_written.toLocaleString('en-US')} 根</span>
          </div>
        ))}
      </div>
    </section>
  );
}
