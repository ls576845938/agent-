from 配置参数 import Config
from 量化引擎 import QuantDataStore, DataUpdateEngine
from 数据抓取 import akshare_price_fetcher, fred_macro_fetcher

if __name__ == "__main__":
    cfg = Config()
    db = QuantDataStore(base_dir=cfg.DB_DIR)
    
    print("🕒 开始执行每日自动增量更新...")
    
    kline_engine = DataUpdateEngine(db, akshare_price_fetcher)
    kline_engine.run_daily_update(cfg.UNIQUE_ASSETS, data_type="kline", max_workers=8)
    
    macro_engine = DataUpdateEngine(db, fred_macro_fetcher)
    macro_engine.run_daily_update(["FRED_MACRO"], data_type="macro", max_workers=1)
    
    print("✅ 今日数据自动化增量更新完成。")