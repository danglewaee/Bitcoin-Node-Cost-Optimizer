import argparse
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


PROFILES = {
    "idle": {
        "cpu": (10, 24),
        "ram": (20, 38),
        "disk_io": (2, 18),
        "network": (0.1, 1.2),
        "rpc_p95": (18, 90),
        "sync_lag": (0, 8),
        "mempool": (5000, 25000),
        "disk_gb": (520, 780),
    },
    "initial_sync": {
        "cpu": (55, 92),
        "ram": (60, 94),
        "disk_io": (80, 220),
        "network": (5.5, 22.0),
        "rpc_p95": (180, 700),
        "sync_lag": (35, 180),
        "mempool": (20000, 180000),
        "disk_gb": (600, 950),
    },
    "high_rpc": {
        "cpu": (45, 86),
        "ram": (52, 90),
        "disk_io": (30, 160),
        "network": (3.0, 18.0),
        "rpc_p95": (90, 400),
        "sync_lag": (3, 45),
        "mempool": (40000, 220000),
        "disk_gb": (380, 700),
    },
}


def sample_metric(bounds: dict[str, tuple[float, float]]) -> dict:
    return {
        "cpu_percent": round(random.uniform(*bounds["cpu"]), 2),
        "ram_percent": round(random.uniform(*bounds["ram"]), 2),
        "disk_io_mb_s": round(random.uniform(*bounds["disk_io"]), 2),
        "network_out_mb_s": round(random.uniform(*bounds["network"]), 3),
        "rpc_p95_ms": round(random.uniform(*bounds["rpc_p95"]), 2),
        "sync_lag_blocks": int(random.randint(*bounds["sync_lag"])),
        "mempool_tx_count": int(random.randint(*bounds["mempool"])),
        "disk_used_gb": round(random.uniform(*bounds["disk_gb"]), 2),
    }


def run_profile(
    api_url: str,
    profile_name: str,
    samples: int,
    seed: int,
    read_headers: dict[str, str],
    write_headers: dict[str, str],
) -> dict:
    random.seed(seed)
    requests.delete(f"{api_url}/metrics/reset", headers=write_headers, timeout=10).raise_for_status()

    bounds = PROFILES[profile_name]
    for _ in range(samples):
        metric = sample_metric(bounds)
        requests.post(f"{api_url}/metrics", json=metric, headers=write_headers, timeout=10).raise_for_status()

    summary = requests.get(f"{api_url}/summary", headers=read_headers, timeout=15)
    summary.raise_for_status()
    return summary.json()


def to_markdown(report: dict) -> str:
    lines = []
    lines.append("# Benchmark Report - Bitcoin Node Cost Optimizer")
    lines.append("")
    lines.append(f"Generated at: `{report['generated_at_utc']}`")
    lines.append("")
    lines.append("| Workload | Current Cost (USD/mo) | Optimized Cost (USD/mo) | Savings (USD/mo) | Savings (%) |")
    lines.append("|---|---:|---:|---:|---:|")

    for name, row in report["profiles"].items():
        lines.append(
            f"| {name} | {row['current_monthly_cost_usd']:.2f} | {row['optimized_monthly_cost_usd']:.2f} | {row['projected_monthly_savings_usd']:.2f} | {row['projected_savings_percent']:.2f}% |"
        )

    lines.append("")
    lines.append("## Resume-ready line")
    lines.append(report["resume_bullet"])
    lines.append("")
    lines.append("## Top recommendations by workload")

    for name, row in report["profiles"].items():
        lines.append("")
        lines.append(f"### {name}")
        for rec in row.get("recommendations", []):
            lines.append(f"- {rec['title']}: {rec['rationale']} (~${rec['estimated_monthly_savings_usd']:.2f}/mo)")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Run synthetic workload benchmarks against optimizer API")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Optimizer API base URL")
    parser.add_argument("--samples", type=int, default=120, help="Samples per workload profile")
    parser.add_argument("--seed", type=int, default=42, help="Base RNG seed")
    parser.add_argument("--output-dir", default="benchmarks/output", help="Where report files are written")
    parser.add_argument("--read-key", default=os.getenv("API_READ_KEY", ""), help="Read API key")
    parser.add_argument("--write-key", default=os.getenv("API_WRITE_KEY", ""), help="Write API key")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    read_headers = {"X-API-Key": args.read_key} if args.read_key else {}
    write_headers = {"X-API-Key": args.write_key} if args.write_key else {}

    profiles_result: dict[str, dict] = {}
    for idx, profile in enumerate(PROFILES):
        profiles_result[profile] = run_profile(
            args.api_url,
            profile,
            args.samples,
            args.seed + idx,
            read_headers,
            write_headers,
        )
        time.sleep(0.3)

    avg_savings_pct = sum(x["projected_savings_percent"] for x in profiles_result.values()) / len(profiles_result)
    max_savings_pct = max(x["projected_savings_percent"] for x in profiles_result.values())

    resume_bullet = (
        "Built a Bitcoin node cloud-cost optimizer with workload-aware tuning that achieved "
        f"{avg_savings_pct:.1f}% average projected monthly savings (up to {max_savings_pct:.1f}%) "
        "across idle, initial-sync, and high-RPC benchmark scenarios."
    )

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "samples_per_profile": args.samples,
        "profiles": profiles_result,
        "resume_bullet": resume_bullet,
    }

    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"

    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")

    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print("\n" + resume_bullet)


if __name__ == "__main__":
    main()
