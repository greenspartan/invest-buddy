import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://etf_user:etf_pass@localhost:5432/invest_buddy")
PORTFOLIO_PATH = os.getenv("PORTFOLIO_PATH", "portfolio.yaml")
