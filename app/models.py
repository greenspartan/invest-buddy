from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func

from app.database import Base


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, nullable=False)
    qty = Column(Float, nullable=False)
    avg_price = Column(Float, nullable=False)
    account = Column(String, nullable=False)
    current_price = Column(Float)
    market_value = Column(Float)
    pnl = Column(Float)
    pnl_pct = Column(Float)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
