import os
import random
import time
from typing import Any

import requests
from dotenv import load_dotenv

try:
    import psutil
except Exception:
    psutil = None

load_dotenv()

API_URL = os.getenv("API_URL", "http://api:8000")
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "10"))
COLLECTOR_MODE = os.getenv("COLLECTOR_MODE", "auto").lower()
API_WRITE_KEY = os.getenv("API_WRITE_KEY", "")

BITCOIN_RPC_URL = os.getenv("BITCOIN_RPC_URL", "http://127.0.0.1:8332")
BITCOIN_RPC_USER = os.getenv("BITCOIN_RPC_USER", "")
BITCOIN_RPC_PASSWORD = os.getenv("BITCOIN_RPC_PASSWORD", "")

_prev_disk_bytes: float | None = None
_prev_net_bytes: float | None = None


def validate_env() -> None:
    if INTERVAL_SECONDS <= 0:
        raise RuntimeError("INTERVAL_SECONDS must be > 0")

    if COLLECTOR_MODE not in {"auto", "mock", "rpc"}:
        raise RuntimeError("COLLECTOR_MODE must be one of: auto, mock, rpc")

    if COLLECTOR_MODE == "rpc" and (not BITCOIN_RPC_USER or not BITCOIN_RPC_PASSWORD):
        raise RuntimeError("BITCOIN_RPC_USER and BITCOIN_RPC_PASSWORD are required when COLLECTOR_MODE=rpc")


def generate_mock_metric() -> dict:
    return {
        "cpu_percent": round(random.uniform(15, 88), 2),
        "ram_percent": round(random.uniform(25, 92), 2),
        "disk_io_mb_s": round(random.uniform(5, 140), 2),
        "network_out_mb_s": round(random.uniform(0.2, 14), 3),
        "rpc_p95_ms": round(random.uniform(30, 550), 2),
        "sync_lag_blocks": random.randint(0, 120),
        "mempool_tx_count": random.randint(5000, 120000),
        "disk_used_gb": round(random.uniform(120, 850), 2),
    }


def bitcoin_rpc(method: str, params: list[Any] | None = None, req_id: int = 1) -> tuple[dict, float]:
    payload = {"jsonrpc": "1.0", "id": req_id, "method": method, "params": params or []}
    start = time.perf_counter()
    response = requests.post(
        BITCOIN_RPC_URL,
        json=payload,
        auth=(BITCOIN_RPC_USER, BITCOIN_RPC_PASSWORD),
        timeout=5,
    )
    latency_ms = (time.perf_counter() - start) * 1000
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise RuntimeError(f"RPC error for {method}: {data['error']}")
    return data["result"], latency_ms


def get_system_metrics(interval_seconds: int) -> tuple[float, float, float, float]:
    global _prev_disk_bytes, _prev_net_bytes

    if psutil is None:
        return (
            round(random.uniform(20, 70), 2),
            round(random.uniform(30, 80), 2),
            round(random.uniform(1, 50), 2),
            round(random.uniform(0.1, 8.0), 3),
        )

    cpu_percent = float(psutil.cpu_percent(interval=None))
    ram_percent = float(psutil.virtual_memory().percent)

    disk_counters = psutil.disk_io_counters()
    net_counters = psutil.net_io_counters()

    disk_total_bytes = float(disk_counters.read_bytes + disk_counters.write_bytes) if disk_counters else 0.0
    net_out_bytes = float(net_counters.bytes_sent) if net_counters else 0.0

    if _prev_disk_bytes is None:
        _prev_disk_bytes = disk_total_bytes
    if _prev_net_bytes is None:
        _prev_net_bytes = net_out_bytes

    disk_io_mb_s = max(0.0, (disk_total_bytes - _prev_disk_bytes) / (1024 * 1024 * max(1, interval_seconds)))
    network_out_mb_s = max(0.0, (net_out_bytes - _prev_net_bytes) / (1024 * 1024 * max(1, interval_seconds)))

    _prev_disk_bytes = disk_total_bytes
    _prev_net_bytes = net_out_bytes

    return cpu_percent, ram_percent, round(disk_io_mb_s, 3), round(network_out_mb_s, 3)


def generate_rpc_metric() -> dict:
    blockchain_info, latency_1 = bitcoin_rpc("getblockchaininfo", req_id=1)
    mempool_info, latency_2 = bitcoin_rpc("getmempoolinfo", req_id=2)
    _net_info, latency_3 = bitcoin_rpc("getnetworkinfo", req_id=3)

    cpu_percent, ram_percent, disk_io_mb_s, network_out_mb_s = get_system_metrics(INTERVAL_SECONDS)

    blocks = int(blockchain_info.get("blocks", 0))
    headers = int(blockchain_info.get("headers", blocks))
    sync_lag_blocks = max(0, headers - blocks)

    mempool_tx_count = int(mempool_info.get("size", 0))
    disk_used_gb = float(blockchain_info.get("size_on_disk", 0)) / (1024 ** 3)

    rpc_p95_ms = round((latency_1 + latency_2 + latency_3) / 3.0, 2)

    return {
        "cpu_percent": round(cpu_percent, 2),
        "ram_percent": round(ram_percent, 2),
        "disk_io_mb_s": round(disk_io_mb_s, 2),
        "network_out_mb_s": round(network_out_mb_s, 3),
        "rpc_p95_ms": rpc_p95_ms,
        "sync_lag_blocks": sync_lag_blocks,
        "mempool_tx_count": mempool_tx_count,
        "disk_used_gb": round(disk_used_gb, 2),
    }


def generate_metric() -> dict:
    if COLLECTOR_MODE == "mock":
        return generate_mock_metric()

    if COLLECTOR_MODE == "rpc":
        return generate_rpc_metric()

    try:
        return generate_rpc_metric()
    except Exception:
        return generate_mock_metric()


def wait_for_api() -> None:
    while True:
        try:
            r = requests.get(f"{API_URL}/health", timeout=3)
            if r.ok:
                return
        except requests.RequestException:
            pass
        time.sleep(2)


def post_metric(payload: dict) -> None:
    headers = {"X-API-Key": API_WRITE_KEY} if API_WRITE_KEY else None
    try:
        requests.post(f"{API_URL}/metrics", json=payload, headers=headers, timeout=5)
    except requests.RequestException:
        pass


if __name__ == "__main__":
    validate_env()
    wait_for_api()

    get_system_metrics(INTERVAL_SECONDS)

    while True:
        metric = generate_metric()
        post_metric(metric)
        time.sleep(INTERVAL_SECONDS)
