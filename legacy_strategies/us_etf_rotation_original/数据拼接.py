import pandas as pd
from 量化引擎 import QuantDataStore

def build_price_matrix(db: QuantDataStore, tickers: list, start_date: str):
    results = {}
    for ticker in tickers:
        df = db.load_data(symbol=ticker, start_date=start_date, columns=['datetime', 'Close'], data_type="kline")
        if not df.empty:
            df.set_index('datetime', inplace=True)
            df.index.name = 'Date' 
            results[ticker] = df['Close']
            
    if not results:
        raise ValueError("本地数据库无数据，请检查网络拉取环节。")

    print("\n🧩 正在拼接价格数据矩阵...")
    close_df = pd.concat(results, axis=1)
    close_df = close_df.where(close_df > 2.0)
    close_df.ffill(inplace=True)
    return close_df

def build_macro_matrix(db: QuantDataStore, start_date: str):
    df = db.load_data(symbol="FRED_MACRO", start_date=start_date, data_type="macro")
    if not df.empty:
        df.set_index('datetime', inplace=True)
        df.index.name = 'Date'
        return df
    return pd.DataFrame()