def estimate_monthly_cost(
    avg_cpu: float,
    avg_ram: float,
    avg_disk_gb: float,
    avg_network_mb_s: float,
    compute_baseline: float = 40.0,
) -> dict:
    """Simple cost model for MVP.

    Uses rough on-demand assumptions:
    - Compute baseline varies by instance tier (default small).
    - Scale compute linearly with utilization pressure.
    - Storage: $0.10 per GB-month.
    - Network egress: $0.05 per GB.
    """
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