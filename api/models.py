from sqlalchemy import Column, DateTime, Float, Integer
from sqlalchemy.sql import func

from database import Base


class NodeMetric(Base):
    __tablename__ = "node_metrics"

    id = Column(Integer, primary_key=True, index=True)
    cpu_percent = Column(Float, nullable=False)
    ram_percent = Column(Float, nullable=False)
    disk_io_mb_s = Column(Float, nullable=False)
    network_out_mb_s = Column(Float, nullable=False)
    rpc_p95_ms = Column(Float, nullable=False)
    sync_lag_blocks = Column(Integer, nullable=False)
    mempool_tx_count = Column(Integer, nullable=False)
    disk_used_gb = Column(Float, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)