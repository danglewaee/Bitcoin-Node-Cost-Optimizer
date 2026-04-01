from sqlalchemy import Column, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from database import Base


class PriceCandle(Base):
    __tablename__ = "price_candles"

    id = Column(Integer, primary_key=True, index=True)
    open_price = Column(Float, nullable=False)
    high_price = Column(Float, nullable=False)
    low_price = Column(Float, nullable=False)
    close_price = Column(Float, nullable=False)
    volume_btc = Column(Float, nullable=False)
    source = Column(String(64), nullable=False, default="mock")
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True, server_default=func.now())


class PredictionSignal(Base):
    __tablename__ = "prediction_signals"
    __table_args__ = (
        UniqueConstraint("source", "reference_timestamp", "lookback", "forecast_horizon", name="uq_signal_context"),
    )

    id = Column(Integer, primary_key=True, index=True)
    generated_at = Column(DateTime(timezone=True), nullable=False, index=True, server_default=func.now())
    source = Column(String(64), nullable=False, default="mock", index=True)
    reference_timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    reference_price = Column(Float, nullable=False)
    target_timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    lookback = Column(Integer, nullable=False)
    forecast_horizon = Column(Integer, nullable=False)
    direction = Column(String(16), nullable=False)
    bias = Column(String(16), nullable=False)
    probability_up = Column(Float, nullable=False)
    probability_down = Column(Float, nullable=False)
    confidence_score = Column(Float, nullable=False)
    setup_quality = Column(String(4), nullable=False)
    risk_level = Column(String(16), nullable=False)
    summary = Column(String(255), nullable=False)
    guidance = Column(String(255), nullable=False)
    what_to_watch = Column(String(255), nullable=False)
    model_version = Column(String(64), nullable=True)
    run_id = Column(String(96), nullable=True, index=True)
    entry_plan = Column(String(255), nullable=True)
    entry_level = Column(Float, nullable=True)
    invalidation_plan = Column(String(255), nullable=True)
    invalidation_level = Column(Float, nullable=True)
    target_plan = Column(String(255), nullable=True)
    target_level = Column(Float, nullable=True)
    risk_reward_ratio = Column(Float, nullable=True)
    outcome_status = Column(String(16), nullable=False, default="pending", index=True)
    resolved_direction = Column(String(16), nullable=True)
    resolved_price = Column(Float, nullable=True)
    realized_change_pct = Column(Float, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
