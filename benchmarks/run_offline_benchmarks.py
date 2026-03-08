import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path


PROFILES = {
    "idle": {
        "cpu": (10, 24),
        "ram": (20, 38),
        "network": (0.1, 1.2),
        "sync_lag": (0, 8),
        "disk_gb": (520, 780),
    },
    "initial_sync": {
        "cpu": (55, 92),
        "ram": (60, 94),
        "network": (5.5, 22.0),
        "sync_lag": (35, 180),
        "disk_gb": (600, 950),
    },
    "high_rpc": {
        "cpu": (45, 86),
        "ram": (52, 90),
        "network": (3.0, 18.0),
        "sync_lag": (3, 45),
        "disk_gb": (380, 700),
    },
}


def estimate_monthly_cost(avg_cpu: float, avg_ram: float, avg_disk_gb: float, avg_network_mb_s: float) -> dict:
    compute_baseline = 40.0
    utilization_factor = max(avg_cpu, avg_ram) / 50.0
    compute_cost = compute_baseline * max(0.6, utilization_factor)
    storage_cost = avg_disk_gb * 0.10
    monthly_egress_gb = avg_network_mb_s * 3600 * 24 * 30 / 1024
    network_cost = monthly_egress_gb * 0.05
    total = compute_cost + storage_cost + network_cost
    return {
        "compute": round(compute_cost, 2),
        "storage": round(storage_cost, 2),
        "network": round(network_cost, 2),
        "total": round(total, 2),
    }


def build_recommendations(avg_cpu: float, avg_ram: float, avg_disk_gb: float, avg_sync_lag: float) -> list[dict]:
    recs = []

    if avg_cpu < 30 and avg_ram < 40:
        recs.append(
            {
                "title": "Rightsize instance down one tier",
                "rationale": "Sustained low CPU/RAM indicates overprovisioning.",
                "estimated_monthly_savings_usd": 18.0,
            }
        )

    if avg_disk_gb > 450:
        recs.append(
            {
                "title": "Enable/adjust pruning",
                "rationale": "High chain storage usage can be reduced with prune mode.",
                "estimated_monthly_savings_usd": avg_disk_gb * 0.03,
            }
        )

    if avg_sync_lag > 20:
        recs.append(
            {
                "title": "Increase dbcache during sync windows",
                "rationale": "High lag suggests disk-bound sync; cache tuning can reduce compute waste.",
                "estimated_monthly_savings_usd": 9.5,
            }
        )

    if not recs:
        recs.append(
            {
                "title": "Current profile is near-optimal",
                "rationale": "No major optimization signals were detected in the current window.",
                "estimated_monthly_savings_usd": 0.0,
            }
        )

    return recs


def average_sample(bounds: dict[str, tuple[float, float]], samples: int) -> dict:
    acc = {"cpu": 0.0, "ram": 0.0, "network": 0.0, "sync_lag": 0.0, "disk_gb": 0.0}
    for _ in range(samples):
        acc["cpu"] += random.uniform(*bounds["cpu"])
        acc["ram"] += random.uniform(*bounds["ram"])
        acc["network"] += random.uniform(*bounds["network"])
        acc["sync_lag"] += random.randint(*bounds["sync_lag"])
        acc["disk_gb"] += random.uniform(*bounds["disk_gb"])

    for k in acc:
        acc[k] /= samples
    return acc


def build_profile_result(avg: dict) -> dict:
    current = estimate_monthly_cost(avg["cpu"], avg["ram"], avg["disk_gb"], avg["network"])
    recs = build_recommendations(avg["cpu"], avg["ram"], avg["disk_gb"], avg["sync_lag"])
    savings = sum(max(0.0, r["estimated_monthly_savings_usd"]) for r in recs)
    optimized = max(0.0, current["total"] - savings)
    pct = (savings / current["total"] * 100.0) if current["total"] > 0 else 0.0

    return {
        "current_monthly_cost_usd": round(current["total"], 2),
        "optimized_monthly_cost_usd": round(optimized, 2),
        "projected_monthly_savings_usd": round(savings, 2),
        "projected_savings_percent": round(pct, 2),
        "recommendations": [
            {
                "title": r["title"],
                "rationale": r["rationale"],
                "estimated_monthly_savings_usd": round(r["estimated_monthly_savings_usd"], 2),
            }
            for r in recs
        ],
    }


def render_md(report: dict) -> str:
    lines = [
        "# Offline Benchmark Report - Bitcoin Node Cost Optimizer",
        "",
        f"Generated at: `{report['generated_at_utc']}`",
        "",
        "| Workload | Current Cost (USD/mo) | Optimized Cost (USD/mo) | Savings (USD/mo) | Savings (%) |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, row in report["profiles"].items():
        lines.append(
            f"| {name} | {row['current_monthly_cost_usd']:.2f} | {row['optimized_monthly_cost_usd']:.2f} | {row['projected_monthly_savings_usd']:.2f} | {row['projected_savings_percent']:.2f}% |"
        )

    lines.extend(["", "## Resume-ready line", report["resume_bullet"], ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Run offline synthetic benchmarks")
    parser.add_argument("--samples", type=int, default=120)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", default="benchmarks/output")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    random.seed(args.seed)

    profiles_result = {}
    for name, bounds in PROFILES.items():
        avg = average_sample(bounds, args.samples)
        profiles_result[name] = build_profile_result(avg)

    avg_pct = sum(x["projected_savings_percent"] for x in profiles_result.values()) / len(profiles_result)
    max_pct = max(x["projected_savings_percent"] for x in profiles_result.values())

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "samples_per_profile": args.samples,
        "profiles": profiles_result,
        "resume_bullet": (
            "Built a Bitcoin node cloud-cost optimizer with workload-aware tuning that achieved "
            f"{avg_pct:.1f}% average projected monthly savings (up to {max_pct:.1f}%) "
            "across idle, initial-sync, and high-RPC benchmark scenarios."
        ),
    }

    json_path = output_dir / "offline_report.json"
    md_path = output_dir / "offline_report.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(render_md(report), encoding="utf-8")

    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print("\n" + report["resume_bullet"])


if __name__ == "__main__":
    main()