import datetime

class Config:
    DB_DIR = './data_cache_lake'
    SIGNAL_FILE = './daily_target_weights_v8.2.csv'
    
    TICKERS = [
        'QQQ', 'VOO', 'MTUM', 'QMOM', 'SOXX', 'IGV', 'XBI',
        'XLK', 'XLF', 'XLV', 'XLE', 'XLI', 'XLY', 'XLP', 'XLU', 'XLB',
        'BITO', 'PDBC', 'GLD', 'USO'
    ]
    BENCHMARK = 'SPY'      
    DEFENSE_ASSETS = ['IEF', 'GLD', 'DBMF', 'SHV']
    
    BETA_WINDOW = 63               
    DEFENSE_MOM_WINDOW = 20        
    DEFENSE_TARGET_VOL = 0.07              
    VOL_WINDOW = 21        
    COV_LOOKBACK = 63      
    W_LIQUIDITY = 0.4      
    W_CREDIT    = 0.4     
    W_TREND     = 0.20     
    TOP_N = 2              
    MOM_LOOKBACKS = [21, 63, 126, 252]
    MOM_WEIGHTS = [0.1, 0.2, 0.3, 0.4]
    TARGET_VOL = 0.20              
    TARGET_VOL_INVERTED = 0.15     
    RATE_SHOCK_WINDOW = 21         
    RATE_SHOCK_THRESHOLD = 0.40    
    RATE_SHOCK_PENALTY = 0.4       
    VOL_SHORT_WINDOW = 21          
    VOL_LONG_WINDOW = 63           
    VOL_EXPANSION_THRESHOLD = 1.1  
    MACRO_MODE = 'CONTINUOUS' 
    MACRO_THRESHOLD = 0.4
    MACRO_CONT_LOWER = 0.2   
    MACRO_CONT_UPPER = 0.4   
    START_DATE = '2018-01-01'  
    END_DATE = datetime.datetime.now().strftime('%Y-%m-%d')  
    COST_BPS = 0.0015       
    MACRO_LAG_DAYS = 2      
    
    @property
    def UNIQUE_ASSETS(self):
        return list(set(self.TICKERS + self.DEFENSE_ASSETS + [self.BENCHMARK]))