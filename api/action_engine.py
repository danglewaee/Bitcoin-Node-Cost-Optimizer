from datetime import datetime, timezone

from schemas import ActionPlanItem, ActionPlanOut, ActionPlanRequest, RecommendationOut


def _action_from_recommendation(rec: RecommendationOut, maintenance_window: str) -> ActionPlanItem:
    title_lower = rec.title.lower()

    if "rightsize" in title_lower:
        return ActionPlanItem(
            action_id="ACT-RIGHTSIZE-001",
            title="Resize compute instance one tier down",
            priority="P2",
            risk="medium",
            estimated_monthly_savings_usd=round(rec.estimated_monthly_savings_usd, 2),
            apply_steps=[
                "Capture current instance type, CPU/RAM averages, and node uptime baseline.",
                "Schedule maintenance window and snapshot the current node volume.",
                "Scale instance down one tier and restart bitcoind with unchanged config.",
                "Monitor RPC p95 and sync lag for 30 minutes before closing the change.",
            ],
            rollback_steps=[
                "Revert to previous instance tier from saved infrastructure config.",
                "Restart services and verify node catches up to prior sync level.",
            ],
            verification_steps=[
                "RPC p95 does not degrade by more than 20%.",
                "Sync lag remains below pre-change 95th percentile.",
            ],
        )

    if "pruning" in title_lower:
        prune_target = "550MB" if maintenance_window == "immediate" else "1200MB"
        return ActionPlanItem(
            action_id="ACT-PRUNE-001",
            title="Enable prune mode and reduce chain storage footprint",
            priority="P1",
            risk="low",
            estimated_monthly_savings_usd=round(rec.estimated_monthly_savings_usd, 2),
            apply_steps=[
                "Backup wallet/datadir metadata and current bitcoin.conf.",
                f"Set `prune={prune_target}` in bitcoin.conf and restart bitcoind.",
                "Wait for disk usage stabilization and confirm node remains healthy.",
            ],
            rollback_steps=[
                "Restore previous bitcoin.conf with prune disabled.",
                "Restart node and resync full data policy if required.",
            ],
            verification_steps=[
                "Disk usage drops to expected threshold within one sync cycle.",
                "No increase in orphan/rejected block alerts.",
            ],
        )

    if "dbcache" in title_lower:
        return ActionPlanItem(
            action_id="ACT-DBCACHE-001",
            title="Increase dbcache during sync-heavy periods",
            priority="P1",
            risk="low",
            estimated_monthly_savings_usd=round(rec.estimated_monthly_savings_usd, 2),
            apply_steps=[
                "Record current dbcache value and memory headroom.",
                "Increase `dbcache` by 25-50% during sync window and restart node.",
                "Observe sync throughput and RPC latency over 20-30 minutes.",
            ],
            rollback_steps=[
                "Restore previous dbcache value in bitcoin.conf.",
                "Restart bitcoind and validate memory pressure returns to baseline.",
            ],
            verification_steps=[
                "Sync lag trend decreases after config update.",
                "Host memory usage stays below 85% sustained.",
            ],
        )

    return ActionPlanItem(
        action_id="ACT-GENERIC-001",
        title=rec.title,
        priority="P3",
        risk="low",
        estimated_monthly_savings_usd=round(rec.estimated_monthly_savings_usd, 2),
        apply_steps=["Apply configuration change during maintenance window."],
        rollback_steps=["Revert to last known-good configuration snapshot."],
        verification_steps=["Confirm node health and cost projection after change."],
    )


def build_action_plan(
    recommendations: list[RecommendationOut],
    request: ActionPlanRequest,
    avg_sync_lag: float,
    avg_rpc_p95: float,
) -> ActionPlanOut:
    actions = [_action_from_recommendation(rec, request.maintenance_window) for rec in recommendations]

    if not request.include_high_risk:
        actions = [a for a in actions if a.risk != "high"]

    expected_total = round(sum(max(0.0, a.estimated_monthly_savings_usd) for a in actions), 2)

    summary = (
        f"Generated {len(actions)} actionable changes for {request.maintenance_window} execution. "
        f"Current risk posture: sync_lag={avg_sync_lag:.1f} blocks, rpc_p95={avg_rpc_p95:.1f}ms. "
        f"Expected monthly savings ~${expected_total:.2f}."
    )

    return ActionPlanOut(
        generated_at=datetime.now(timezone.utc),
        maintenance_window=request.maintenance_window,
        expected_total_monthly_savings_usd=expected_total,
        summary=summary,
        actions=actions,
    )