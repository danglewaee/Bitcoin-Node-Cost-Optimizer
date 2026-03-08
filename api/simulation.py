from math import sqrt
from schemas import SimulationRequest, SimulationOut
from cost_model import estimate_monthly_cost


TIER_BASELINE_COST = {
    "small": 40.0,
    "medium": 72.0,
    "large": 118.0,
}

TIER_CAPACITY_FACTOR = {
    "small": 1.0,
    "medium": 1.65,
    "large": 2.5,
}

WORKLOAD_MULTIPLIERS = {
    "idle": {"cpu": 0.72, "ram": 0.78, "network": 0.65, "sync": 0.55, "rpc": 0.82, "disk": 1.0},
    "balanced": {"cpu": 1.0, "ram": 1.0, "network": 1.0, "sync": 1.0, "rpc": 1.0, "disk": 1.0},
    "sync": {"cpu": 1.28, "ram": 1.22, "network": 1.35, "sync": 1.85, "rpc": 1.28, "disk": 1.04},
    "high_rpc": {"cpu": 1.18, "ram": 1.1, "network": 1.22, "sync": 1.18, "rpc": 1.42, "disk": 1.02},
}


def simulate_configuration(
    avg_cpu: float,
    avg_ram: float,
    avg_network_mb_s: float,
    avg_sync_lag: float,
    avg_disk_gb: float,
    avg_rpc_p95_ms: float,
    request: SimulationRequest,
) -> SimulationOut:
    baseline = estimate_monthly_cost(avg_cpu, avg_ram, avg_disk_gb, avg_network_mb_s, compute_baseline=40.0)

    multipliers = WORKLOAD_MULTIPLIERS[request.workload_profile]
    capacity = TIER_CAPACITY_FACTOR[request.instance_tier]

    prof_cpu = min(100.0, avg_cpu * multipliers["cpu"])
    prof_ram = min(100.0, avg_ram * multipliers["ram"])
    prof_network = max(0.01, avg_network_mb_s * multipliers["network"])
    prof_sync = max(0.0, avg_sync_lag * multipliers["sync"])
    prof_rpc = max(1.0, avg_rpc_p95_ms * multipliers["rpc"])
    prof_disk = max(5.0, avg_disk_gb * multipliers["disk"])

    tuned_cpu = min(100.0, prof_cpu / capacity)
    tuned_ram = min(100.0, prof_ram / capacity)

    prune_factor = 0.52 if request.pruning_enabled else 1.0
    tuned_disk = max(20.0, prof_disk * prune_factor)

    cache_gain = min(0.45, sqrt(request.dbcache_mb / 1024.0) * 0.18)

    overload_index = max(0.0, max(prof_cpu, prof_ram) - (82.0 * capacity)) / 100.0
    overload_penalty = 1.0 + overload_index

    tuned_rpc = prof_rpc * (1.0 - cache_gain) * overload_penalty
    tuned_sync = prof_sync * (1.0 - min(0.5, cache_gain * 1.15)) * (1.0 + overload_index * 1.25)

    simulated = estimate_monthly_cost(
        tuned_cpu,
        tuned_ram,
        tuned_disk,
        prof_network,
        compute_baseline=TIER_BASELINE_COST[request.instance_tier],
    )

    savings = baseline["total"] - simulated["total"]
    savings_pct = (savings / baseline["total"] * 100.0) if baseline["total"] > 0 else 0.0

    notes: list[str] = []
    notes.append(
        f"Workload profile '{request.workload_profile}' applied to current baseline telemetry before simulation."
    )
    notes.append(
        f"Instance tier '{request.instance_tier}' uses baseline compute cost ${TIER_BASELINE_COST[request.instance_tier]:.0f}/mo."
    )
    if request.pruning_enabled:
        notes.append("Pruning enabled: chain storage footprint reduced for lower storage spend.")
    else:
        notes.append("Pruning disabled: full chain retained, higher storage cost but full history available.")

    notes.append(f"dbcache={request.dbcache_mb}MB used to estimate RPC/sync performance improvements.")

    if overload_index > 0.05:
        notes.append("Selected tier may be under-provisioned for this workload; latency risk increased.")

    return SimulationOut(
        baseline_monthly_cost_usd=round(baseline["total"], 2),
        simulated_monthly_cost_usd=round(simulated["total"], 2),
        projected_monthly_savings_usd=round(savings, 2),
        projected_savings_percent=round(savings_pct, 2),
        baseline_rpc_p95_ms=round(prof_rpc, 2),
        simulated_rpc_p95_ms=round(tuned_rpc, 2),
        baseline_sync_lag_blocks=round(prof_sync, 2),
        simulated_sync_lag_blocks=round(tuned_sync, 2),
        notes=notes,
    )