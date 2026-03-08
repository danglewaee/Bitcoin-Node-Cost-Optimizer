from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class MetricCreate(BaseModel):
    cpu_percent: float = Field(ge=0, le=100)
    ram_percent: float = Field(ge=0, le=100)
    disk_io_mb_s: float = Field(ge=0)
    network_out_mb_s: float = Field(ge=0)
    rpc_p95_ms: float = Field(ge=0)
    sync_lag_blocks: int = Field(ge=0)
    mempool_tx_count: int = Field(ge=0)
    disk_used_gb: float = Field(ge=0)


class MetricOut(MetricCreate):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True


class RecommendationOut(BaseModel):
    title: str
    rationale: str
    estimated_monthly_savings_usd: float


class SummaryOut(BaseModel):
    current_monthly_cost_usd: float
    optimized_monthly_cost_usd: float
    projected_monthly_savings_usd: float
    projected_savings_percent: float
    recommendations: list[RecommendationOut]


class SimulationRequest(BaseModel):
    instance_tier: Literal["small", "medium", "large"] = "small"
    pruning_enabled: bool = True
    dbcache_mb: int = Field(default=1024, ge=300, le=16384)
    workload_profile: Literal["idle", "balanced", "sync", "high_rpc"] = "balanced"


class SimulationOut(BaseModel):
    baseline_monthly_cost_usd: float
    simulated_monthly_cost_usd: float
    projected_monthly_savings_usd: float
    projected_savings_percent: float
    baseline_rpc_p95_ms: float
    simulated_rpc_p95_ms: float
    baseline_sync_lag_blocks: float
    simulated_sync_lag_blocks: float
    notes: list[str]


class ActionPlanRequest(BaseModel):
    maintenance_window: Literal["immediate", "off_peak"] = "off_peak"
    include_high_risk: bool = False


class ActionPlanItem(BaseModel):
    action_id: str
    title: str
    priority: Literal["P1", "P2", "P3"]
    risk: Literal["low", "medium", "high"]
    estimated_monthly_savings_usd: float
    apply_steps: list[str]
    rollback_steps: list[str]
    verification_steps: list[str]


class ActionPlanOut(BaseModel):
    generated_at: datetime
    maintenance_window: Literal["immediate", "off_peak"]
    expected_total_monthly_savings_usd: float
    summary: str
    actions: list[ActionPlanItem]