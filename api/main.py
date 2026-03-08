import os
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session

from action_engine import build_action_plan
from cost_model import estimate_monthly_cost
from database import Base, DATABASE_URL, engine, get_db
from models import NodeMetric
from optimizer import build_recommendations
from schemas import (
    ActionPlanOut,
    ActionPlanRequest,
    MetricCreate,
    MetricOut,
    SimulationOut,
    SimulationRequest,
    SummaryOut,
)
from simulation import simulate_configuration

DEFAULT_ALLOWED_ORIGINS = "http://127.0.0.1:8899,http://localhost:8899,http://127.0.0.1:8080,http://localhost:8080"

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
READ_API_KEY = os.getenv("READ_API_KEY", "")
WRITE_API_KEY = os.getenv("WRITE_API_KEY", "")
ALLOWED_ORIGINS_RAW = os.getenv("ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS)


def parse_allowed_origins(raw_value: str) -> list[str]:
    origins = [origin.strip() for origin in raw_value.split(",") if origin.strip()]
    if not origins:
        raise RuntimeError("ALLOWED_ORIGINS must include at least one origin")
    if "*" in origins and len(origins) > 1:
        raise RuntimeError("ALLOWED_ORIGINS cannot mix '*' with explicit origins")
    return origins


ALLOWED_ORIGINS = parse_allowed_origins(ALLOWED_ORIGINS_RAW)


def validate_environment() -> None:
    valid_envs = {"development", "test", "production"}
    if APP_ENV not in valid_envs:
        raise RuntimeError("APP_ENV must be one of: development, test, production")

    if APP_ENV == "production":
        if DATABASE_URL.startswith("sqlite"):
            raise RuntimeError("SQLite is not allowed in production. Use PostgreSQL via DATABASE_URL.")
        if not READ_API_KEY or len(READ_API_KEY) < 16:
            raise RuntimeError("READ_API_KEY is required in production and should be at least 16 characters.")
        if not WRITE_API_KEY or len(WRITE_API_KEY) < 16:
            raise RuntimeError("WRITE_API_KEY is required in production and should be at least 16 characters.")
        if "*" in ALLOWED_ORIGINS:
            raise RuntimeError("ALLOWED_ORIGINS cannot be '*' in production")


def _check_api_key(expected_key: str, x_api_key: str | None) -> None:
    if not expected_key:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


def require_read_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    # In development, auth can be disabled by leaving READ_API_KEY empty.
    _check_api_key(READ_API_KEY, x_api_key)


def require_write_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    # In development, auth can be disabled by leaving WRITE_API_KEY empty.
    _check_api_key(WRITE_API_KEY, x_api_key)


validate_environment()

app = FastAPI(title="Bitcoin Node Cost & Performance Optimizer", version="0.8.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)


@app.get("/health")
def health_check():
    return {"status": "ok", "env": APP_ENV}


@app.post("/metrics", response_model=MetricOut)
def ingest_metric(
    payload: MetricCreate,
    db: Session = Depends(get_db),
    _auth: None = Depends(require_write_api_key),
):
    metric = NodeMetric(**payload.model_dump())
    db.add(metric)
    db.commit()
    db.refresh(metric)
    return metric


@app.delete("/metrics/reset")
def reset_metrics(
    db: Session = Depends(get_db),
    _auth: None = Depends(require_write_api_key),
):
    deleted = db.query(NodeMetric).delete()
    db.commit()
    return {"deleted_rows": deleted}


@app.get("/metrics/latest", response_model=MetricOut)
def latest_metric(
    db: Session = Depends(get_db),
    _auth: None = Depends(require_read_api_key),
):
    metric = db.query(NodeMetric).order_by(NodeMetric.timestamp.desc()).first()
    if not metric:
        raise HTTPException(status_code=404, detail="No metrics available")
    return metric


@app.get("/metrics/recent", response_model=list[MetricOut])
def recent_metrics(
    limit: int = Query(default=40, ge=5, le=500),
    db: Session = Depends(get_db),
    _auth: None = Depends(require_read_api_key),
):
    rows = db.query(NodeMetric).order_by(NodeMetric.timestamp.desc()).limit(limit).all()
    return list(reversed(rows))


def get_metric_averages(db: Session):
    row = (
        db.query(
            func.avg(NodeMetric.cpu_percent),
            func.avg(NodeMetric.ram_percent),
            func.avg(NodeMetric.disk_io_mb_s),
            func.avg(NodeMetric.network_out_mb_s),
            func.avg(NodeMetric.sync_lag_blocks),
            func.avg(NodeMetric.disk_used_gb),
            func.avg(NodeMetric.rpc_p95_ms),
        )
        .select_from(NodeMetric)
        .first()
    )

    if not row or row[0] is None:
        raise HTTPException(status_code=404, detail="No metrics available")

    avg_cpu, avg_ram, avg_disk_io, avg_network, avg_sync_lag, avg_disk_gb, avg_rpc_p95 = [float(v) for v in row]
    return {
        "avg_cpu": avg_cpu,
        "avg_ram": avg_ram,
        "avg_disk_io": avg_disk_io,
        "avg_network": avg_network,
        "avg_sync_lag": avg_sync_lag,
        "avg_disk_gb": avg_disk_gb,
        "avg_rpc_p95": avg_rpc_p95,
    }


@app.get("/summary", response_model=SummaryOut)
def summary(
    db: Session = Depends(get_db),
    _auth: None = Depends(require_read_api_key),
):
    avg = get_metric_averages(db)
    current = estimate_monthly_cost(avg["avg_cpu"], avg["avg_ram"], avg["avg_disk_gb"], avg["avg_network"])

    recs = build_recommendations(avg["avg_cpu"], avg["avg_ram"], avg["avg_disk_gb"], avg["avg_sync_lag"])
    rec_savings = sum(max(0.0, r.estimated_monthly_savings_usd) for r in recs)

    optimized_total = max(0.0, current["total"] - rec_savings)
    savings_percent = (rec_savings / current["total"] * 100.0) if current["total"] > 0 else 0.0

    return SummaryOut(
        current_monthly_cost_usd=current["total"],
        optimized_monthly_cost_usd=round(optimized_total, 2),
        projected_monthly_savings_usd=round(rec_savings, 2),
        projected_savings_percent=round(savings_percent, 2),
        recommendations=recs,
    )


@app.post("/simulate", response_model=SimulationOut)
def simulate(
    payload: SimulationRequest,
    db: Session = Depends(get_db),
    _auth: None = Depends(require_read_api_key),
):
    avg = get_metric_averages(db)

    return simulate_configuration(
        avg_cpu=avg["avg_cpu"],
        avg_ram=avg["avg_ram"],
        avg_network_mb_s=avg["avg_network"],
        avg_sync_lag=avg["avg_sync_lag"],
        avg_disk_gb=avg["avg_disk_gb"],
        avg_rpc_p95_ms=avg["avg_rpc_p95"],
        request=payload,
    )


@app.post("/actions/plan", response_model=ActionPlanOut)
def generate_action_plan(
    payload: ActionPlanRequest,
    db: Session = Depends(get_db),
    _auth: None = Depends(require_read_api_key),
):
    avg = get_metric_averages(db)
    recs = build_recommendations(avg["avg_cpu"], avg["avg_ram"], avg["avg_disk_gb"], avg["avg_sync_lag"])

    return build_action_plan(
        recommendations=recs,
        request=payload,
        avg_sync_lag=avg["avg_sync_lag"],
        avg_rpc_p95=avg["avg_rpc_p95"],
    )
