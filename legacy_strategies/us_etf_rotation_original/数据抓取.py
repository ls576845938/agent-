import time
import datetime
import pandas as pd
import akshare as ak
import pandas_datareader.data as web

def akshare_price_fetcher(symbol: str, start_date: str) -> pd.DataFrame:
    max_retries = 3
    for i in range(max_retries):
        try:
            df = ak.stock_us_daily(symbol=symbol, adjust="qfq")
            if df is None or df.empty:
                time.sleep(1)
                continue
            
            df.rename(columns={'date': 'datetime', 'open': 'Open', 'close': 'Close', 'high': 'High', 'low': 'Low', 'volume': 'Volume'}, inplace=True)
            df['datetime'] = pd.to_datetime(df['datetime'])
            
            cols = ['Open', 'Close', 'High', 'Low']
            df[cols] = df[cols].apply(pd.to_numeric, errors='coerce')
            return df
        except Exception:
            time.sleep(2)
    return pd.DataFrame()

def fred_macro_fetcher(symbol: str, start_date: str) -> pd.DataFrame:
    fred_tickers = ['WALCL', 'WTREGEN', 'RRPONTSYD', 'BAMLC0A0CM', 'DGS10', 'DGS2']
    try:
        start = pd.to_datetime(start_date) - pd.Timedelta(days=5)
        end = datetime.datetime.now()
        
        df = web.DataReader(fred_tickers, 'fred', start, end)
        df = df.resample('D').ffill().reset_index()
        df.rename(columns={'DATE': 'datetime'}, inplace=True)
        return df
    except Exception as e:
        print(f"FRED 数据拉取异常: {e}")
        return pd.DataFrame()