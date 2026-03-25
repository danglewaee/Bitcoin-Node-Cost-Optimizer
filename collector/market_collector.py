from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("API_URL", "http://api:8000")
API_WRITE_KEY = os.getenv("API_WRITE_KEY", "")
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "60"))
CANDLE_INTERVAL_MINUTES = int(os.getenv("CANDLE_INTERVAL_MINUTES", "60"))
BOOTSTRAP_CANDLES = int(os.getenv("BOOTSTRAP_CANDLES", "72"))
MARKET_API_BASE_URL = os.getenv("MARKET_API_BASE_URL", "https://api.exchange.coinbase.com").rstrip("/")
MARKET_PRODUCT_ID = os.getenv("MARKET_PRODUCT_ID", "BTC-USD").strip().upper()
MARKET_SOURCE = os.getenv("MARKET_SOURCE", "coinbase-exchange").strip() or "coinbase-exchange"

SUPPORTED_GRANULARITIES = {
    1: 60,
    5: 300,
    15: 900,
    60: 3600,
    360: 21600,
    1440: 86400,
}
MAX_CANDLES_PER_REQUEST = 300
REQUEST_TIMEOUT_SECONDS = 12
DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "bitcoin-trend-market-collector/1.0",
}


def validate_env() -> None:
    if INTERVAL_SECONDS <= 0:
        raise RuntimeError("INTERVAL_SECONDS must be > 0")
    if BOOTSTRAP_CANDLES < 0:
        raise RuntimeError("BOOTSTRAP_CANDLES must be >= 0")
    if CANDLE_INTERVAL_MINUTES not in SUPPORTED_GRANULARITIES:
        allowed = ", ".join(str(value) for value in sorted(SUPPORTED_GRANULARITIES))
        raise RuntimeError(f"CANDLE_INTERVAL_MINUTES must be one of: {allowed}")
    if not MARKET_PRODUCT_ID:
        raise RuntimeError("MARKET_PRODUCT_ID is required")


def granularity_seconds() -> int:
    return SUPPORTED_GRANULARITIES[CANDLE_INTERVAL_MINUTES]


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
    except requests.RequestException as exc:
        print(f"price ingest failed: {exc}", flush=True)


def _normalize_candle(raw_row: list[float | int]) -> dict:
    bucket_start = datetime.fromtimestamp(int(raw_row[0]), tz=timezone.utc)
    return {
        "open_price": round(float(raw_row[3]), 2),
        "high_price": round(float(raw_row[2]), 2),
        "low_price": round(float(raw_row[1]), 2),
        "close_price": round(float(raw_row[4]), 2),
        "volume_btc": round(float(raw_row[5]), 8),
        "source": f"{MARKET_SOURCE}:{MARKET_PRODUCT_ID}",
        "timestamp": bucket_start.isoformat(),
    }


def fetch_candle_range(start: datetime, end: datetime) -> list[dict]:
    response = requests.get(
        f"{MARKET_API_BASE_URL}/products/{MARKET_PRODUCT_ID}/candles",
        params={
            "granularity": granularity_seconds(),
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        headers=DEFAULT_HEADERS,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    rows = response.json()
    candles = [_normalize_candle(row) for row in rows if isinstance(row, list) and len(row) >= 6]
    candles.sort(key=lambda candle: candle["timestamp"])
    return candles


def fetch_historical_candles(total_candles: int) -> list[dict]:
    if total_candles <= 0:
        return []

    window_seconds = granularity_seconds()
    end = datetime.now(timezone.utc)
    candles_by_timestamp: dict[str, dict] = {}
    remaining = total_candles

    while remaining > 0:
        batch_size = min(remaining, MAX_CANDLES_PER_REQUEST)
        start = end - timedelta(seconds=window_seconds * batch_size)
        for candle in fetch_candle_range(start=start, end=end):
            candles_by_timestamp[candle["timestamp"]] = candle
        end = start
        remaining -= batch_size

    candles = sorted(candles_by_timestamp.values(), key=lambda candle: candle["timestamp"])
    return candles[-total_candles:]


def fetch_latest_market_candles(window_candles: int = 3) -> list[dict]:
    candle_count = max(2, window_candles)
    window_seconds = granularity_seconds()
    end = datetime.now(timezone.utc)
    start = end - timedelta(seconds=window_seconds * candle_count)
    candles = fetch_candle_range(start=start, end=end)
    return candles[-candle_count:]


def bootstrap_history() -> None:
    for candle in fetch_historical_candles(BOOTSTRAP_CANDLES):
        post_candle(candle)


def run_forever() -> None:
    while True:
        try:
            for candle in fetch_latest_market_candles():
                post_candle(candle)
        except requests.RequestException as exc:
            print(f"market fetch failed: {exc}", flush=True)
        time.sleep(INTERVAL_SECONDS)


def main() -> None:
    validate_env()
    wait_for_api()
    bootstrap_history()
    run_forever()


if __name__ == "__main__":
    main()
