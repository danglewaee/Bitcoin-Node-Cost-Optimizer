import csv
import os
import secrets
from datetime import datetime, timezone
from io import StringIO

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from database import Base, DATABASE_URL, engine, get_db
from models import PredictionSignal, PriceCandle
from schemas import (
    ActionReadOut,
    BacktestReportOut,
    BacktestRunOut,
    CandleCreate,
    CandleOut,
    MultiReadOut,
    PerformanceBucketOut,
    PredictionOut,
    PredictionRequest,
    SignalHistoryOut,
    SignalPerformanceOut,
    SignalStatsOut,
    TrendSummaryOut,
)
from trend_engine import (
    build_prediction,
    build_trend_summary,
    classify_realized_direction,
    estimate_candle_interval,
)

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
    _check_api_key(READ_API_KEY, x_api_key)


def require_write_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    _check_api_key(WRITE_API_KEY, x_api_key)


def normalize_requested_source(source: str | None) -> str | None:
    if source is None:
        return None

    cleaned = source.strip()
    if not cleaned:
        return None
    if cleaned == "mock" or cleaned.startswith("mock-"):
        return "mock"
    return cleaned


def get_recent_candles(db: Session, limit: int, source: str | None = None) -> list[PriceCandle]:
    query = apply_price_source_filter(db.query(PriceCandle), source)
    rows = query.order_by(PriceCandle.timestamp.desc()).limit(limit).all()
    return list(reversed(rows))


def normalize_signal_source(source: str) -> str:
    normalized = normalize_requested_source(source)
    return normalized or source


def apply_price_source_filter(query, source: str | None):
    normalized_source = normalize_requested_source(source)
    if normalized_source is None:
        return query
    if normalized_source == "mock":
        return query.filter(PriceCandle.source.like("mock-%"))
    return query.filter(PriceCandle.source == normalized_source)


def apply_prediction_source_filter(query, source: str | None):
    normalized_source = normalize_requested_source(source)
    if normalized_source is None:
        return query
    return query.filter(PredictionSignal.source == normalized_source)


def resolve_prediction_outcomes(db: Session) -> None:
    pending_signals = (
        db.query(PredictionSignal)
        .filter(PredictionSignal.outcome_status == "pending")
        .order_by(PredictionSignal.generated_at.asc())
        .all()
    )

    updated = False
    for signal in pending_signals:
        outcome_query = db.query(PriceCandle).filter(PriceCandle.timestamp >= signal.target_timestamp)
        outcome_candle = apply_price_source_filter(outcome_query, signal.source).order_by(PriceCandle.timestamp.asc()).first()

        if outcome_candle is None:
            continue

        realized_direction = classify_realized_direction(signal.reference_price, outcome_candle.close_price)
        if realized_direction == signal.direction:
            outcome_status = "right"
        elif realized_direction == "sideways" and signal.direction != "sideways":
            outcome_status = "flat"
        else:
            outcome_status = "wrong"

        signal.outcome_status = outcome_status
        signal.resolved_direction = realized_direction
        signal.resolved_price = outcome_candle.close_price
        signal.realized_change_pct = round(
            ((outcome_candle.close_price - signal.reference_price) / signal.reference_price) * 100.0,
            2,
        )
        signal.resolved_at = outcome_candle.timestamp
        updated = True

    if updated:
        db.commit()


def build_signal_stats(rows: list[PredictionSignal]) -> SignalStatsOut:
    sample_size = len(rows)
    resolved = [row for row in rows if row.outcome_status != "pending"]
    right_signals = sum(1 for row in resolved if row.outcome_status == "right")
    wrong_signals = sum(1 for row in resolved if row.outcome_status == "wrong")
    flat_signals = sum(1 for row in resolved if row.outcome_status == "flat")
    pending_signals = sample_size - len(resolved)

    hit_rate = round((right_signals / len(resolved)) * 100.0, 2) if resolved else 0.0
    resolved_changes = [row.realized_change_pct for row in resolved if row.realized_change_pct is not None]
    right_changes = [row.realized_change_pct for row in resolved if row.outcome_status == "right" and row.realized_change_pct is not None]
    wrong_changes = [row.realized_change_pct for row in resolved if row.outcome_status == "wrong" and row.realized_change_pct is not None]

    avg_resolved_change_pct = round(sum(resolved_changes) / len(resolved_changes), 2) if resolved_changes else 0.0
    avg_right_change_pct = round(sum(right_changes) / len(right_changes), 2) if right_changes else None
    avg_wrong_change_pct = round(sum(wrong_changes) / len(wrong_changes), 2) if wrong_changes else None

    if sample_size == 0:
        summary = "No saved reads yet. Run the action card and the recent edge panel will start building a score."
    elif len(resolved) < 3:
        summary = "The scorecard is still warming up. A few more resolved reads will make the recent edge more useful."
    elif hit_rate >= 65:
        summary = f"Recent reads are holding up well: {hit_rate:.0f}% of resolved calls landed correctly in the latest sample."
    elif hit_rate <= 40:
        summary = f"Recent reads are struggling: only {hit_rate:.0f}% of resolved calls landed correctly in the latest sample."
    else:
        summary = f"Recent reads are mixed: {hit_rate:.0f}% of resolved calls landed correctly, so use the action card with patience."

    return SignalStatsOut(
        sample_size=sample_size,
        resolved_signals=len(resolved),
        pending_signals=pending_signals,
        right_signals=right_signals,
        wrong_signals=wrong_signals,
        flat_signals=flat_signals,
        hit_rate=hit_rate,
        avg_resolved_change_pct=avg_resolved_change_pct,
        avg_right_change_pct=avg_right_change_pct,
        avg_wrong_change_pct=avg_wrong_change_pct,
        summary=summary,
    )


def build_performance_bucket(key: str, rows: list[PredictionSignal]) -> PerformanceBucketOut:
    resolved = [row for row in rows if row.outcome_status != "pending"]
    right = [row for row in resolved if row.outcome_status == "right"]
    resolved_changes = [row.realized_change_pct for row in resolved if row.realized_change_pct is not None]
    avg_change_pct = round(sum(resolved_changes) / len(resolved_changes), 2) if resolved_changes else 0.0
    hit_rate = round((len(right) / len(resolved)) * 100.0, 2) if resolved else 0.0
    return PerformanceBucketOut(
        key=key,
        total_signals=len(rows),
        resolved_signals=len(resolved),
        hit_rate=hit_rate,
        avg_change_pct=avg_change_pct,
    )


def build_signal_performance(rows: list[PredictionSignal]) -> SignalPerformanceOut:
    bias_groups: dict[str, list[PredictionSignal]] = {"long": [], "short": [], "neutral": []}
    setup_groups: dict[str, list[PredictionSignal]] = {"A": [], "B": [], "C": []}

    for row in rows:
        bias_groups.setdefault(row.bias, []).append(row)
        setup_groups.setdefault(row.setup_quality, []).append(row)

    bias_breakdown = [build_performance_bucket(key, bias_groups[key]) for key in ["long", "short", "neutral"] if bias_groups.get(key)]
    setup_breakdown = [build_performance_bucket(key, setup_groups[key]) for key in ["A", "B", "C"] if setup_groups.get(key)]

    best_bias = max(bias_breakdown, key=lambda item: (item.hit_rate, item.resolved_signals), default=None)
    best_setup = max(setup_breakdown, key=lambda item: (item.hit_rate, item.resolved_signals), default=None)

    return SignalPerformanceOut(
        sample_size=len(rows),
        bias_breakdown=bias_breakdown,
        setup_breakdown=setup_breakdown,
        best_bias=best_bias.key if best_bias is not None else None,
        best_setup_quality=best_setup.key if best_setup is not None else None,
    )


def calculate_directional_hit_rate(runs: list[BacktestRunOut], bias: str | None = None) -> float:
    filtered = [run for run in runs if bias is None or run.bias == bias]
    if not filtered:
        return 0.0
    right_runs = sum(1 for run in filtered if run.outcome_status == "right")
    return round((right_runs / len(filtered)) * 100.0, 2)


def calculate_strategy_return(bias: str, realized_change_pct: float) -> float:
    if bias == "long":
        return realized_change_pct
    if bias == "short":
        return round(-realized_change_pct, 2)
    return 0.0


def calculate_max_drawdown(strategy_returns: list[float]) -> float:
    equity_curve = 0.0
    peak_equity = 0.0
    max_drawdown = 0.0
    for strategy_return in strategy_returns:
        equity_curve += strategy_return
        peak_equity = max(peak_equity, equity_curve)
        max_drawdown = max(max_drawdown, peak_equity - equity_curve)
    return round(max_drawdown, 2)


def build_backtest_report(
    candles: list[PriceCandle],
    lookback: int,
    forecast_horizon: int,
    sample_size: int,
) -> BacktestReportOut:
    minimum_candles = lookback + forecast_horizon + 1
    if len(candles) < minimum_candles:
        raise ValueError(
            f"At least {minimum_candles} candles are required for a backtest with lookback={lookback} and horizon={forecast_horizon}."
        )

    eligible_end_indexes = list(range(lookback - 1, len(candles) - forecast_horizon))
    if not eligible_end_indexes:
        raise ValueError("Not enough historical windows are available for the requested backtest.")

    active_indexes = eligible_end_indexes[-sample_size:]
    runs: list[BacktestRunOut] = []

    for end_index in active_indexes:
        history = candles[end_index - lookback + 1 : end_index + 1]
        prediction = build_prediction(history, lookback=lookback, forecast_horizon=forecast_horizon)
        reference_candle = history[-1]
        outcome_candle = candles[end_index + forecast_horizon]
        realized_direction = classify_realized_direction(reference_candle.close_price, outcome_candle.close_price)

        if realized_direction == prediction.direction:
            outcome_status = "right"
        elif realized_direction == "sideways" and prediction.direction != "sideways":
            outcome_status = "flat"
        else:
            outcome_status = "wrong"

        realized_change_pct = round(
            ((outcome_candle.close_price - reference_candle.close_price) / reference_candle.close_price) * 100.0,
            2,
        )
        strategy_return_pct = calculate_strategy_return(prediction.bias, realized_change_pct)

        runs.append(
            BacktestRunOut(
                reference_timestamp=reference_candle.timestamp,
                target_timestamp=outcome_candle.timestamp,
                direction=prediction.direction,
                bias=prediction.bias,
                setup_quality=prediction.setup_quality,
                risk_level=prediction.risk_level,
                confidence_score=prediction.confidence_score,
                entry_level=prediction.entry_level,
                invalidation_level=prediction.invalidation_level,
                target_level=prediction.target_level,
                risk_reward_ratio=prediction.risk_reward_ratio,
                realized_direction=realized_direction,
                realized_change_pct=realized_change_pct,
                strategy_return_pct=strategy_return_pct,
                outcome_status=outcome_status,
            )
        )

    right_runs = sum(1 for run in runs if run.outcome_status == "right")
    wrong_runs = sum(1 for run in runs if run.outcome_status == "wrong")
    flat_runs = sum(1 for run in runs if run.outcome_status == "flat")
    sample_count = len(runs)
    hit_rate = round((right_runs / sample_count) * 100.0, 2) if sample_count else 0.0
    wrong_rate = round((wrong_runs / sample_count) * 100.0, 2) if sample_count else 0.0
    flat_rate = round((flat_runs / sample_count) * 100.0, 2) if sample_count else 0.0
    avg_realized_change_pct = round(sum(run.realized_change_pct for run in runs) / sample_count, 2) if sample_count else 0.0
    strategy_returns = [run.strategy_return_pct for run in runs]
    avg_strategy_return_pct = round(sum(strategy_returns) / sample_count, 2) if sample_count else 0.0
    cumulative_strategy_return_pct = round(sum(strategy_returns), 2)
    max_drawdown_pct = calculate_max_drawdown(strategy_returns)
    avg_confidence_score = round(sum(run.confidence_score for run in runs) / sample_count, 2) if sample_count else 0.0
    rr_values = [run.risk_reward_ratio for run in runs if run.risk_reward_ratio is not None]
    avg_risk_reward_ratio = round(sum(rr_values) / len(rr_values), 2) if rr_values else None
    long_hit_rate = calculate_directional_hit_rate(runs, bias="long")
    short_hit_rate = calculate_directional_hit_rate(runs, bias="short")

    if sample_count < 12:
        summary = "Backtest sample is still small, so use it as a confidence check rather than a final verdict."
    elif hit_rate >= 60 and cumulative_strategy_return_pct > 0:
        summary = (
            f"Recent walk-forward reads are earning trust: {hit_rate:.0f}% hit rate with "
            f"{cumulative_strategy_return_pct:.2f}% cumulative edge across the sample."
        )
    elif cumulative_strategy_return_pct < 0:
        summary = (
            f"Recent walk-forward reads are not earning trust yet: cumulative edge is "
            f"{cumulative_strategy_return_pct:.2f}% across the latest sample."
        )
    else:
        summary = (
            f"Recent walk-forward reads are mixed: {hit_rate:.0f}% hit rate with "
            f"{cumulative_strategy_return_pct:.2f}% cumulative edge."
        )

    return BacktestReportOut(
        lookback=lookback,
        forecast_horizon=forecast_horizon,
        sample_size=sample_count,
        hit_rate=hit_rate,
        wrong_rate=wrong_rate,
        flat_rate=flat_rate,
        avg_realized_change_pct=avg_realized_change_pct,
        avg_strategy_return_pct=avg_strategy_return_pct,
        cumulative_strategy_return_pct=cumulative_strategy_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        avg_confidence_score=avg_confidence_score,
        avg_risk_reward_ratio=avg_risk_reward_ratio,
        long_hit_rate=long_hit_rate,
        short_hit_rate=short_hit_rate,
        summary=summary,
        runs=list(reversed(runs)),
    )


def build_action_read(label: str, candles: list[PriceCandle], lookback: int, forecast_horizon: int) -> ActionReadOut:
    actual_lookback = min(max(12, lookback), len(candles))
    prediction = build_prediction(candles=candles, lookback=actual_lookback, forecast_horizon=forecast_horizon)
    return ActionReadOut(
        label=label,
        lookback=actual_lookback,
        forecast_horizon=forecast_horizon,
        direction=prediction.direction,
        bias=prediction.bias,
        setup_quality=prediction.setup_quality,
        risk_level=prediction.risk_level,
        probability_up=prediction.probability_up,
        probability_down=prediction.probability_down,
        summary=prediction.summary,
        guidance=prediction.guidance,
        what_to_watch=prediction.what_to_watch,
        entry_plan=prediction.entry_plan,
        entry_level=prediction.entry_level,
        invalidation_plan=prediction.invalidation_plan,
        invalidation_level=prediction.invalidation_level,
        target_plan=prediction.target_plan,
        target_level=prediction.target_level,
        risk_reward_ratio=prediction.risk_reward_ratio,
    )


def build_backtest_csv(report: BacktestReportOut, source: str | None) -> str:
    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(
        [
            "source",
            "lookback",
            "forecast_horizon",
            "report_sample_size",
            "report_hit_rate",
            "report_cumulative_strategy_return_pct",
            "report_max_drawdown_pct",
            "report_avg_risk_reward_ratio",
            "reference_timestamp",
            "target_timestamp",
            "bias",
            "direction",
            "setup_quality",
            "risk_level",
            "confidence_score",
            "entry_level",
            "invalidation_level",
            "target_level",
            "risk_reward_ratio",
            "realized_direction",
            "realized_change_pct",
            "strategy_return_pct",
            "outcome_status",
        ]
    )

    export_source = normalize_requested_source(source) or "all"
    for run in report.runs:
        writer.writerow(
            [
                export_source,
                report.lookback,
                report.forecast_horizon,
                report.sample_size,
                report.hit_rate,
                report.cumulative_strategy_return_pct,
                report.max_drawdown_pct,
                report.avg_risk_reward_ratio,
                run.reference_timestamp.isoformat(),
                run.target_timestamp.isoformat(),
                run.bias,
                run.direction,
                run.setup_quality,
                run.risk_level,
                run.confidence_score,
                run.entry_level,
                run.invalidation_level,
                run.target_level,
                run.risk_reward_ratio,
                run.realized_direction,
                run.realized_change_pct,
                run.strategy_return_pct,
                run.outcome_status,
            ]
        )

    return csv_buffer.getvalue()


def build_backtest_response(
    db: Session,
    lookback: int,
    forecast_horizon: int,
    sample_size: int,
    source: str | None,
) -> BacktestReportOut:
    required_candles = lookback + forecast_horizon + sample_size
    candles = get_recent_candles(db, required_candles, source=source)
    if not candles:
        raise HTTPException(status_code=404, detail="No price candles available")
    try:
        return build_backtest_report(
            candles=candles,
            lookback=lookback,
            forecast_horizon=forecast_horizon,
            sample_size=sample_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def ensure_prediction_signal_columns() -> None:
    inspector = inspect(engine)
    if "prediction_signals" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("prediction_signals")}
    column_definitions = {
        "entry_plan": "VARCHAR(255)",
        "entry_level": "FLOAT",
        "invalidation_plan": "VARCHAR(255)",
        "invalidation_level": "FLOAT",
        "target_plan": "VARCHAR(255)",
        "target_level": "FLOAT",
        "risk_reward_ratio": "FLOAT",
    }

    missing_columns = [
        (name, definition)
        for name, definition in column_definitions.items()
        if name not in existing_columns
    ]
    if not missing_columns:
        return

    with engine.begin() as connection:
        for column_name, definition in missing_columns:
            connection.execute(text(f"ALTER TABLE prediction_signals ADD COLUMN {column_name} {definition}"))


def persist_prediction_signal(
    db: Session,
    candles: list[PriceCandle],
    prediction: PredictionOut,
) -> None:
    latest_candle = candles[-1]
    interval = estimate_candle_interval(candles)
    target_timestamp = latest_candle.timestamp + (interval * prediction.forecast_horizon)
    signal_source = normalize_signal_source(latest_candle.source)

    signal = (
        db.query(PredictionSignal)
        .filter(
            PredictionSignal.source == signal_source,
            PredictionSignal.reference_timestamp == latest_candle.timestamp,
            PredictionSignal.lookback == prediction.lookback,
            PredictionSignal.forecast_horizon == prediction.forecast_horizon,
        )
        .first()
    )

    if signal is None:
        signal = PredictionSignal(
            generated_at=prediction.generated_at,
            source=signal_source,
            reference_timestamp=latest_candle.timestamp,
            reference_price=latest_candle.close_price,
            target_timestamp=target_timestamp,
            lookback=prediction.lookback,
            forecast_horizon=prediction.forecast_horizon,
            direction=prediction.direction,
            bias=prediction.bias,
            probability_up=prediction.probability_up,
            probability_down=prediction.probability_down,
            confidence_score=prediction.confidence_score,
            setup_quality=prediction.setup_quality,
            risk_level=prediction.risk_level,
            summary=prediction.summary,
            guidance=prediction.guidance,
            what_to_watch=prediction.what_to_watch,
            entry_plan=prediction.entry_plan,
            entry_level=prediction.entry_level,
            invalidation_plan=prediction.invalidation_plan,
            invalidation_level=prediction.invalidation_level,
            target_plan=prediction.target_plan,
            target_level=prediction.target_level,
            risk_reward_ratio=prediction.risk_reward_ratio,
        )
        db.add(signal)
    else:
        signal.reference_price = latest_candle.close_price
        signal.target_timestamp = target_timestamp
        signal.direction = prediction.direction
        signal.bias = prediction.bias
        signal.probability_up = prediction.probability_up
        signal.probability_down = prediction.probability_down
        signal.confidence_score = prediction.confidence_score
        signal.setup_quality = prediction.setup_quality
        signal.risk_level = prediction.risk_level
        signal.summary = prediction.summary
        signal.guidance = prediction.guidance
        signal.what_to_watch = prediction.what_to_watch
        signal.entry_plan = prediction.entry_plan
        signal.entry_level = prediction.entry_level
        signal.invalidation_plan = prediction.invalidation_plan
        signal.invalidation_level = prediction.invalidation_level
        signal.target_plan = prediction.target_plan
        signal.target_level = prediction.target_level
        signal.risk_reward_ratio = prediction.risk_reward_ratio

    db.commit()
    resolve_prediction_outcomes(db)


validate_environment()

app = FastAPI(title="Bitcoin Trend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)
ensure_prediction_signal_columns()


@app.get("/health")
def health_check():
    return {"status": "ok", "env": APP_ENV, "service": "bitcoin-trend"}


@app.post("/prices", response_model=CandleOut)
def ingest_price_candle(
    payload: CandleCreate,
    db: Session = Depends(get_db),
    _auth: None = Depends(require_write_api_key),
):
    candle = None
    if payload.timestamp is not None:
        candle = (
            db.query(PriceCandle)
            .filter(
                PriceCandle.source == payload.source,
                PriceCandle.timestamp == payload.timestamp,
            )
            .first()
        )

    if candle is None:
        candle = PriceCandle(**payload.model_dump(exclude_none=True))
        db.add(candle)
    else:
        candle.open_price = payload.open_price
        candle.high_price = payload.high_price
        candle.low_price = payload.low_price
        candle.close_price = payload.close_price
        candle.volume_btc = payload.volume_btc

    db.commit()
    db.refresh(candle)
    resolve_prediction_outcomes(db)
    return candle


@app.delete("/prices/reset")
def reset_price_candles(
    db: Session = Depends(get_db),
    _auth: None = Depends(require_write_api_key),
):
    deleted = db.query(PriceCandle).delete()
    db.query(PredictionSignal).delete()
    db.commit()
    return {"deleted_rows": deleted}


@app.get("/prices/latest", response_model=CandleOut)
def latest_price_candle(
    source: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _auth: None = Depends(require_read_api_key),
):
    candle = apply_price_source_filter(db.query(PriceCandle), source).order_by(PriceCandle.timestamp.desc()).first()
    if not candle:
        raise HTTPException(status_code=404, detail="No price candles available")
    return candle


@app.get("/prices/recent", response_model=list[CandleOut])
def recent_price_candles(
    limit: int = Query(default=72, ge=12, le=500),
    source: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _auth: None = Depends(require_read_api_key),
):
    rows = get_recent_candles(db, limit, source=source)
    if not rows:
        raise HTTPException(status_code=404, detail="No price candles available")
    return rows


@app.get("/signals/recent", response_model=list[SignalHistoryOut])
def recent_signals(
    limit: int = Query(default=8, ge=1, le=50),
    source: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _auth: None = Depends(require_read_api_key),
):
    resolve_prediction_outcomes(db)
    rows = (
        apply_prediction_source_filter(db.query(PredictionSignal), source)
        .order_by(PredictionSignal.generated_at.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No prediction signals available")
    return rows


@app.get("/signals/stats", response_model=SignalStatsOut)
def signal_stats(
    limit: int = Query(default=20, ge=1, le=200),
    source: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _auth: None = Depends(require_read_api_key),
):
    resolve_prediction_outcomes(db)
    rows = (
        apply_prediction_source_filter(db.query(PredictionSignal), source)
        .order_by(PredictionSignal.generated_at.desc())
        .limit(limit)
        .all()
    )
    return build_signal_stats(rows)


@app.get("/signals/performance", response_model=SignalPerformanceOut)
def signal_performance(
    limit: int = Query(default=60, ge=1, le=500),
    source: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _auth: None = Depends(require_read_api_key),
):
    resolve_prediction_outcomes(db)
    rows = (
        apply_prediction_source_filter(db.query(PredictionSignal), source)
        .order_by(PredictionSignal.generated_at.desc())
        .limit(limit)
        .all()
    )
    return build_signal_performance(rows)


@app.get("/trend/summary", response_model=TrendSummaryOut)
@app.get("/summary", response_model=TrendSummaryOut)
def trend_summary(
    lookback: int = Query(default=48, ge=12, le=500),
    source: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _auth: None = Depends(require_read_api_key),
):
    candles = get_recent_candles(db, lookback, source=source)
    if not candles:
        raise HTTPException(status_code=404, detail="No price candles available")
    try:
        return build_trend_summary(candles, lookback=lookback)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/predict", response_model=PredictionOut)
def predict_direction(
    payload: PredictionRequest,
    source: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _auth: None = Depends(require_read_api_key),
):
    candles = get_recent_candles(db, payload.lookback, source=source)
    if not candles:
        raise HTTPException(status_code=404, detail="No price candles available")
    try:
        prediction = build_prediction(
            candles=candles,
            lookback=payload.lookback,
            forecast_horizon=payload.forecast_horizon,
        )
        persist_prediction_signal(db, candles, prediction)
        return prediction
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/reads/multi", response_model=MultiReadOut)
def multi_reads(
    source: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _auth: None = Depends(require_read_api_key),
):
    candles = get_recent_candles(db, 72, source=source)
    if not candles:
        raise HTTPException(status_code=404, detail="No price candles available")
    if len(candles) < 12:
        raise HTTPException(status_code=400, detail="At least 12 candles are required to build multi-read action cards.")

    reads = [
        build_action_read("Fast", candles, lookback=24, forecast_horizon=3),
        build_action_read("Core", candles, lookback=48, forecast_horizon=6),
        build_action_read("Bigger Picture", candles, lookback=72, forecast_horizon=12),
    ]
    return MultiReadOut(generated_at=datetime.now(timezone.utc), reads=reads)


@app.get("/backtest/report", response_model=BacktestReportOut)
def backtest_report(
    lookback: int = Query(default=48, ge=12, le=500),
    forecast_horizon: int = Query(default=6, ge=1, le=72),
    sample_size: int = Query(default=36, ge=5, le=240),
    source: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _auth: None = Depends(require_read_api_key),
):
    return build_backtest_response(
        db=db,
        lookback=lookback,
        forecast_horizon=forecast_horizon,
        sample_size=sample_size,
        source=source,
    )


@app.get("/backtest/export.csv")
def backtest_export_csv(
    lookback: int = Query(default=48, ge=12, le=500),
    forecast_horizon: int = Query(default=6, ge=1, le=72),
    sample_size: int = Query(default=36, ge=5, le=240),
    source: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _auth: None = Depends(require_read_api_key),
):
    report = build_backtest_response(
        db=db,
        lookback=lookback,
        forecast_horizon=forecast_horizon,
        sample_size=sample_size,
        source=source,
    )
    normalized_source = normalize_requested_source(source) or "all-sources"
    filename_source = normalized_source.replace(":", "-")
    csv_text = build_backtest_csv(report, source)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="bitcoin-trend-backtest-{filename_source}.csv"'
        },
    )
