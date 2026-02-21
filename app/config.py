import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://etf_user:etf_pass@localhost:5432/invest_buddy")
PORTFOLIO_PATH = os.getenv("PORTFOLIO_PATH", "portfolio.yaml")
TRANSACTIONS_PATH = os.getenv("TRANSACTIONS_PATH", "transactions.yaml")
TARGET_PATH = os.getenv("TARGET_PATH", "target_portfolio.yaml")
BASE_CURRENCY = os.getenv("BASE_CURRENCY", "EUR")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
