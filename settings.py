import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    EXCHANGE      = os.getenv("EXCHANGE", "bybit")
    MARKET_TYPE   = os.getenv("MARKET_TYPE", "swap")   # 'spot' | 'swap'
    QUOTE         = os.getenv("QUOTE", "USDT")

    # Таймфреймы
    WORK_TF       = os.getenv("WORK_TF", "1h")
    VOL_TF        = os.getenv("VOL_TF", "1d")
    TREND_TF1     = os.getenv("TREND_TF1", "4h")
    TREND_TF2     = os.getenv("TREND_TF2", "1d")

    # RSI
    RSI_LEN       = int(os.getenv("RSI_LEN", 14))
    RSI_OVERBOUGHT= float(os.getenv("RSI_OVERBOUGHT", 70))
    RSI_OVERSOLD  = float(os.getenv("RSI_OVERSOLD", 30))

    # Волатильность
    ATR_LEN       = int(os.getenv("ATR_LEN", 14))
    TOP_N_BY_VOL  = int(os.getenv("TOP_N_BY_VOL", 100))

    # Периодичность
    ITER_SECONDS  = int(os.getenv("ITER_SECONDS", 1800))

    # Telegram
    TG_REPORT_BOT_TOKEN = os.getenv("TG_REPORT_BOT_TOKEN", "")
    TG_REPORT_CHAT_ID   = os.getenv("TG_REPORT_CHAT_ID", "")
    TG_SIGNAL_BOT_TOKEN = os.getenv("TG_SIGNAL_BOT_TOKEN", "")
    TG_SIGNAL_CHAT_ID   = os.getenv("TG_SIGNAL_CHAT_ID", "")

    # Директория данных
    DATA_DIR = os.getenv("DATA_DIR", "./data")

    # Аномальные пампы/дампы
    ANOMALY_FILTER_ENABLED = os.getenv("ANOMALY_FILTER_ENABLED", "true").lower() == "true"
    MAX_24H_ABS_CHANGE_PCT = float(os.getenv("MAX_24H_ABS_CHANGE_PCT", 80))
    MAX_7D_ABS_CHANGE_PCT  = float(os.getenv("MAX_7D_ABS_CHANGE_PCT", 300))
