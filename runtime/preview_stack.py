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


def stream_preview_candles(collector, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        collector.post_candle(collector.generate_mock_candle())
        stop_event.wait(1.0)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    api_dir = root / "api"
    collector_path = root / "collector" / "mock_collector.py"
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

    handler = partial(SimpleHTTPRequestHandler, directory=str(root / "dashboard"))
    dashboard_server = ThreadingHTTPServer(("127.0.0.1", 8899), handler)
    dashboard_thread = threading.Thread(target=dashboard_server.serve_forever, daemon=True)
    dashboard_thread.start()

    os.environ["API_URL"] = "http://127.0.0.1:8765"
    os.environ["API_WRITE_KEY"] = "dev-write-key"
    os.environ["INTERVAL_SECONDS"] = "1"
    os.environ["TREND_MODE"] = "auto"
    os.environ["BOOTSTRAP_CANDLES"] = "72"
    os.environ["START_PRICE_USD"] = "65000"
    os.environ["BASE_VOLUME_BTC"] = "1200"
    os.environ["VOLATILITY_PCT"] = "0.75"
    os.environ["CANDLE_INTERVAL_MINUTES"] = "60"

    spec = importlib.util.spec_from_file_location("collector_preview", collector_path)
    collector = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(collector)
    collector.validate_env()
    collector.bootstrap_history()
    for _ in range(6):
        collector.post_candle(collector.generate_mock_candle())
    feed_stop = threading.Event()
    feed_thread = threading.Thread(target=stream_preview_candles, args=(collector, feed_stop), daemon=True)
    feed_thread.start()

    print("PREVIEW_READY http://127.0.0.1:8899/?read_api_key=dev-read-key", flush=True)
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
