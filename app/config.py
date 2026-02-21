import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://etf_user:etf_pass@localhost:5432/invest_buddy")
PORTFOLIO_PATH = os.getenv("PORTFOLIO_PATH", "portfolio.yaml")
TRANSACTIONS_PATH = os.getenv("TRANSACTIONS_PATH", "transactions.yaml")
TARGET_PATH = os.getenv("TARGET_PATH", "target_portfolio.yaml")
BASE_CURRENCY = os.getenv("BASE_CURRENCY", "EUR")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
MACRO_CONFIG_PATH = os.getenv("MACRO_CONFIG_PATH", "macro_config.yaml")
LYN_ALDEN_DIR = os.getenv("LYN_ALDEN_DIR", "context/macro/Lyn Alden")
SELL_SIDE_DIR = os.getenv("SELL_SIDE_DIR", "context/macro/sell-side")
