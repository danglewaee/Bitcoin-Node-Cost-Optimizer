from __future__ import annotations

import os
import random
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("API_URL", "http://api:8000")
API_WRITE_KEY = os.getenv("API_WRITE_KEY", "")
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "10"))
TREND_MODE = os.getenv("TREND_MODE", "auto").strip().lower()
START_PRICE_USD = float(os.getenv("START_PRICE_USD", "65000"))
BASE_VOLUME_BTC = float(os.getenv("BASE_VOLUME_BTC", "1200"))
VOLATILITY_PCT = float(os.getenv("VOLATILITY_PCT", "0.75"))
CANDLE_INTERVAL_MINUTES = int(os.getenv("CANDLE_INTERVAL_MINUTES", "60"))
BOOTSTRAP_CANDLES = int(os.getenv("BOOTSTRAP_CANDLES", "72"))

_current_price = START_PRICE_USD
_next_timestamp = datetime.now(timezone.utc) - timedelta(hours=96)
_candle_count = 0
_active_regime = "bull"


def validate_env() -> None:
    if INTERVAL_SECONDS <= 0:
        raise RuntimeError("INTERVAL_SECONDS must be > 0")
    if CANDLE_INTERVAL_MINUTES <= 0:
        raise RuntimeError("CANDLE_INTERVAL_MINUTES must be > 0")
    if START_PRICE_USD <= 0:
        raise RuntimeError("START_PRICE_USD must be > 0")
    if VOLATILITY_PCT <= 0:
        raise RuntimeError("VOLATILITY_PCT must be > 0")
    if BOOTSTRAP_CANDLES < 0:
        raise RuntimeError("BOOTSTRAP_CANDLES must be >= 0")
    if TREND_MODE not in {"auto", "bull", "bear", "sideways"}:
        raise RuntimeError("TREND_MODE must be one of: auto, bull, bear, sideways")


def _pick_regime() -> str:
    global _active_regime

    if TREND_MODE != "auto":
        return TREND_MODE

    if _candle_count % 24 == 0:
        _active_regime = random.choice(["bull", "bull", "sideways", "bear"])
    return _active_regime


def generate_mock_candle() -> dict:
    global _current_price, _next_timestamp, _candle_count

    regime = _pick_regime()
    drift_map = {
        "bull": 0.45,
        "bear": -0.45,
        "sideways": 0.0,
    }
    drift_pct = drift_map[regime]
    shock_pct = random.gauss(0, VOLATILITY_PCT)
    move_pct = drift_pct + shock_pct

    open_price = _current_price
    close_price = max(1000.0, open_price * (1 + move_pct / 100.0))
    wick_pct = abs(random.gauss(0.18, 0.08))
    high_price = max(open_price, close_price) * (1 + wick_pct / 100.0)
    low_price = min(open_price, close_price) * max(0.7, 1 - wick_pct / 100.0)

    volume_multiplier = 1 + (abs(move_pct) / 3.5) + random.uniform(-0.12, 0.18)
    volume_btc = max(100.0, BASE_VOLUME_BTC * volume_multiplier)

    payload = {
        "open_price": round(open_price, 2),
        "high_price": round(high_price, 2),
        "low_price": round(low_price, 2),
        "close_price": round(close_price, 2),
        "volume_btc": round(volume_btc, 2),
        "source": f"mock-{regime}",
        "timestamp": _next_timestamp.isoformat(),
    }

    _current_price = close_price
    _next_timestamp = _next_timestamp + timedelta(minutes=CANDLE_INTERVAL_MINUTES)
    _candle_count += 1
    return payload


def wait_for_api() -> None:
    while True:
        try:
            response = requests.get(f"{API_URL}/health", timeout=3)
            if response.ok:
                return
        except requests.RequestException:
            pass
        time.sleep(2)


def post_candle(payload: dict) -> None:
    headers = {"X-API-Key": API_WRITE_KEY} if API_WRITE_KEY else None
    try:
        requests.post(f"{API_URL}/prices", json=payload, headers=headers, timeout=5).raise_for_status()
    except requests.RequestException:
        pass


def bootstrap_history() -> None:
    for _ in range(BOOTSTRAP_CANDLES):
        post_candle(generate_mock_candle())


def run_forever() -> None:
    while True:
        candle = generate_mock_candle()
        post_candle(candle)
        time.sleep(INTERVAL_SECONDS)


def main() -> None:
    validate_env()
    wait_for_api()
    bootstrap_history()
    run_forever()


if __name__ == "__main__":
    main()
