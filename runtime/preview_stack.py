import importlib.util
import os
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests
import uvicorn


def load_collector_module(module_name: str, collector_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, collector_path)
    collector = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(collector)
    return collector


def configure_preview_collector(preview_mode: str) -> Path:
    root = Path(__file__).resolve().parents[1]
    os.environ["API_URL"] = "http://127.0.0.1:8765"
    os.environ["API_WRITE_KEY"] = "dev-write-key"

    if preview_mode == "market":
        os.environ["INTERVAL_SECONDS"] = os.getenv("PREVIEW_POLL_SECONDS", "30")
        os.environ["BOOTSTRAP_CANDLES"] = os.getenv("PREVIEW_BOOTSTRAP_CANDLES", "96")
        os.environ["CANDLE_INTERVAL_MINUTES"] = os.getenv("PREVIEW_CANDLE_INTERVAL_MINUTES", "15")
        os.environ["MARKET_API_BASE_URL"] = os.getenv("PREVIEW_MARKET_API_BASE_URL", "https://api.exchange.coinbase.com")
        os.environ["MARKET_PRODUCT_ID"] = os.getenv("PREVIEW_MARKET_PRODUCT_ID", "BTC-USD")
        os.environ["MARKET_SOURCE"] = os.getenv("PREVIEW_MARKET_SOURCE", "coinbase-exchange")
        return root / "collector" / "market_collector.py"

    if preview_mode == "mock":
        os.environ["INTERVAL_SECONDS"] = os.getenv("PREVIEW_POLL_SECONDS", "1")
        os.environ["TREND_MODE"] = os.getenv("PREVIEW_TREND_MODE", "auto")
        os.environ["BOOTSTRAP_CANDLES"] = os.getenv("PREVIEW_BOOTSTRAP_CANDLES", "72")
        os.environ["START_PRICE_USD"] = os.getenv("PREVIEW_START_PRICE_USD", "65000")
        os.environ["BASE_VOLUME_BTC"] = os.getenv("PREVIEW_BASE_VOLUME_BTC", "1200")
        os.environ["VOLATILITY_PCT"] = os.getenv("PREVIEW_VOLATILITY_PCT", "0.75")
        os.environ["CANDLE_INTERVAL_MINUTES"] = os.getenv("PREVIEW_CANDLE_INTERVAL_MINUTES", "60")
        return root / "collector" / "mock_collector.py"

    raise RuntimeError("PREVIEW_DATA_MODE must be one of: market, mock")


def stream_preview_candles(collector, preview_mode: str, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            if preview_mode == "market":
                for candle in collector.fetch_latest_market_candles(window_candles=2):
                    collector.post_candle(candle)
            else:
                collector.post_candle(collector.generate_mock_candle())
        except requests.RequestException as exc:
            print(f"preview feed failed: {exc}", flush=True)
        stop_event.wait(float(os.getenv("INTERVAL_SECONDS", "1")))


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    api_dir = root / "api"
    preview_mode = os.getenv("PREVIEW_DATA_MODE", "market").strip().lower()
    collector_path = configure_preview_collector(preview_mode)
    runtime_db = api_dir / "preview_stack.db"
    if runtime_db.exists():
        runtime_db.unlink()

    os.environ["APP_ENV"] = "development"
    os.environ["READ_API_KEY"] = "dev-read-key"
    os.environ["WRITE_API_KEY"] = "dev-write-key"
    os.environ["ALLOWED_ORIGINS"] = "http://127.0.0.1:8899,http://localhost:8899"
    os.environ["DATABASE_URL"] = "sqlite:///./preview_stack.db"

    sys.path.insert(0, str(api_dir))
    os.chdir(api_dir)
    import main as api_main  # noqa: PLC0415

    config = uvicorn.Config(api_main.app, host="127.0.0.1", port=8765, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    api_thread = threading.Thread(target=server.run, daemon=True)
    api_thread.start()

    for _ in range(50):
        try:
            response = requests.get("http://127.0.0.1:8765/health", timeout=1)
            if response.ok:
                break
        except requests.RequestException:
            time.sleep(0.2)
    else:
        raise RuntimeError("API did not start")

    collector = load_collector_module("collector_preview", collector_path)
    collector.validate_env()
    collector.bootstrap_history()
    if preview_mode == "mock":
        for _ in range(6):
            collector.post_candle(collector.generate_mock_candle())

    handler = partial(SimpleHTTPRequestHandler, directory=str(root / "dashboard"))
    dashboard_server = ThreadingHTTPServer(("127.0.0.1", 8899), handler)
    dashboard_thread = threading.Thread(target=dashboard_server.serve_forever, daemon=True)
    dashboard_thread.start()

    feed_stop = threading.Event()
    feed_thread = threading.Thread(target=stream_preview_candles, args=(collector, preview_mode, feed_stop), daemon=True)
    feed_thread.start()

    print(f"PREVIEW_READY mode={preview_mode} http://127.0.0.1:8899/?read_api_key=dev-read-key", flush=True)
    try:
        while True:
            time.sleep(60)
    finally:
        feed_stop.set()
        server.should_exit = True
        dashboard_server.shutdown()
        feed_thread.join(timeout=5)
        api_thread.join(timeout=5)
        dashboard_thread.join(timeout=5)


if __name__ == "__main__":
    main()
