import pandas as pd
import pyarrow.parquet as pq
import os
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class QuantDataStore:
    def __init__(self, base_dir="./data_cache_lake"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, symbol: str, data_type: str) -> Path:
        dir_path = self.base_dir / data_type
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path / f"{symbol}.parquet"

    def save_data(self, df: pd.DataFrame, symbol: str, data_type: str = "kline", time_col: str = "datetime"):
        if df.empty: return
        df[time_col] = pd.to_datetime(df[time_col])
        file_path = self._get_file_path(symbol, data_type)

        if not file_path.exists():
            df = df.sort_values(by=time_col).drop_duplicates(subset=[time_col], keep='last')
            df.to_parquet(file_path, engine='pyarrow', index=False)
            logger.info(f"[{symbol} - {data_type}] 初始化写入 {len(df)} 行。")
            return

        existing_df = pd.read_parquet(file_path, engine='pyarrow')
        combined_df = pd.concat([existing_df, df], ignore_index=True)
        combined_df = combined_df.drop_duplicates(subset=[time_col], keep='last').sort_values(by=time_col)
        combined_df.to_parquet(file_path, engine='pyarrow', index=False)

    def load_data(self, symbol: str, start_date: str = None, end_date: str = None, 
                  columns: list = None, data_type: str = "kline", time_col: str = "datetime") -> pd.DataFrame:
        file_path = self._get_file_path(symbol, data_type)
        if not file_path.exists(): return pd.DataFrame()
        
        if columns is not None and time_col not in columns: columns.append(time_col)
        df = pd.read_parquet(file_path, columns=columns, engine='pyarrow')

        if start_date: df = df[df[time_col] >= pd.to_datetime(start_date)]
        if end_date: df = df[df[time_col] <= pd.to_datetime(end_date)]
        return df.reset_index(drop=True)

    def get_latest_date(self, symbol: str, data_type: str = "kline", time_col: str = "datetime"):
        file_path = self._get_file_path(symbol, data_type)
        if not file_path.exists(): return None
        df_time = pd.read_parquet(file_path, columns=[time_col], engine='pyarrow')
        return df_time[time_col].max()

class DataUpdateEngine:
    def __init__(self, data_store: QuantDataStore, fetch_func):
        self.store = data_store
        self.fetch_func = fetch_func

    def _update_single_symbol(self, symbol: str, data_type: str = "kline"):
        try:
            latest_date = self.store.get_latest_date(symbol, data_type)
            start_fetch = latest_date.strftime('%Y-%m-%d') if latest_date else "2000-01-01"
            new_data = self.fetch_func(symbol, start_date=start_fetch)
            if new_data is not None and not new_data.empty:
                self.store.save_data(new_data, symbol, data_type=data_type)
            return True
        except Exception as e:
            logger.error(f"[{symbol}] 更新失败: {str(e)}")
            return False

    def run_daily_update(self, symbols: list, data_type: str = "kline", max_workers: int = 5):
        logger.info(f"开始并发更新 {len(symbols)} 个品种 ({data_type})...")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_symbol = {executor.submit(self._update_single_symbol, sym, data_type): sym for sym in symbols}
            for future in as_completed(future_to_symbol):
                pass