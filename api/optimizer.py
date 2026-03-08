from schemas import RecommendationOut


def build_recommendations(avg_cpu: float, avg_ram: float, avg_disk_gb: float, avg_sync_lag: float) -> list[RecommendationOut]:
    recs: list[RecommendationOut] = []

    if avg_cpu < 30 and avg_ram < 40:
        recs.append(
            RecommendationOut(
                title="Rightsize instance down one tier",
                rationale="Sustained low CPU/RAM indicates overprovisioning.",
                estimated_monthly_savings_usd=18.0,
            )
        )

    if avg_disk_gb > 450:
        recs.append(
            RecommendationOut(
                title="Enable/adjust pruning",
                rationale="High chain storage usage can be reduced with prune mode.",
                estimated_monthly_savings_usd=avg_disk_gb * 0.03,
            )
        )

    if avg_sync_lag > 20:
        recs.append(
            RecommendationOut(
                title="Increase dbcache during sync windows",
                rationale="High lag suggests disk-bound sync; cache tuning can reduce compute waste.",
                estimated_monthly_savings_usd=9.5,
            )
        )

    if not recs:
        recs.append(
            RecommendationOut(
                title="Current profile is near-optimal",
                rationale="No major optimization signals were detected in the current window.",
                estimated_monthly_savings_usd=0.0,
            )
        )

    return recs