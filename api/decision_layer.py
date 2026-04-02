from __future__ import annotations


def build_factors(features: dict[str, float]) -> list[str]:
    factors: list[str] = []
    if features["short_sma"] > features["long_sma"]:
        factors.append("Short-term price action is still trading above the base trend.")
    elif features["short_sma"] < features["long_sma"]:
        factors.append("Short-term price action is still sitting below the base trend.")

    if features["momentum_pct"] > 0:
        factors.append("Recent candles are still pushing upward.")
    elif features["momentum_pct"] < 0:
        factors.append("Recent candles are still losing ground.")

    if features["recent_change_pct"] > 0:
        factors.append("Price has been climbing across the current read.")
    elif features["recent_change_pct"] < 0:
        factors.append("Price has been weakening across the current read.")

    if features["volatility_pct"] >= 2.5:
        factors.append("The move is noisy right now, so conviction is lower.")

    if features["volume_ratio_pct"] > 10:
        factors.append("Volume is backing the move instead of fading.")
    elif features["volume_ratio_pct"] < -10:
        factors.append("Volume is fading, so the move has less support behind it.")

    if not factors:
        factors.append("Signals are mixed, so patience matters more than speed here.")
    return factors


def build_market_read(features: dict[str, float]) -> str:
    if features["trend_direction"] == "up":
        return "Buyers still have control, but cleaner entries usually come on pullbacks rather than chasing straight into strength."
    if features["trend_direction"] == "down":
        return "Sellers still have control, so weak bounces can fade fast unless price starts reclaiming lost ground."
    return "This market is chopping sideways, so waiting for a cleaner break is better than forcing a trade."


def build_watch_text(features: dict[str, float]) -> str:
    support_level = f"${features['support_level']:,.2f}"
    resistance_level = f"${features['resistance_level']:,.2f}"
    if features["trend_direction"] == "up":
        return f"Watch whether BTC can keep holding above {support_level} and press into {resistance_level} without losing momentum."
    if features["trend_direction"] == "down":
        return f"Watch whether BTC loses {support_level} again or gets rejected before it can reclaim {resistance_level}."
    return f"Watch for a clean break outside the {support_level} to {resistance_level} range before taking fresh risk."


def build_setup_quality(direction: str, confidence_score: float, volatility_pct: float) -> str:
    score = 0
    if direction != "sideways":
        score += 1
    if confidence_score >= 75:
        score += 2
    elif confidence_score >= 60:
        score += 1
    if volatility_pct <= 1.8:
        score += 1
    elif volatility_pct >= 3.0:
        score -= 1

    if score >= 3:
        return "A"
    if score >= 1:
        return "B"
    return "C"


def build_risk_level(direction: str, confidence_score: float, volatility_pct: float, recent_change_pct: float) -> str:
    risk_points = 0
    if direction == "sideways":
        risk_points += 1
    if confidence_score < 60:
        risk_points += 1
    if volatility_pct >= 2.5:
        risk_points += 1
    if abs(recent_change_pct) >= 6:
        risk_points += 1

    if risk_points >= 3:
        return "high"
    if risk_points >= 1:
        return "medium"
    return "low"


def build_guidance(direction: str, setup_quality: str, risk_level: str) -> str:
    if direction == "up":
        if setup_quality == "A" and risk_level == "low":
            return "Long bias stays intact. Pullbacks are cleaner than chasing extended green candles."
        if risk_level == "high":
            return "Bias still leans long, but this is a messy spot. Wait for a calmer pullback or stronger reclaim."
        return "Long bias is still on, but entries look cleaner on patience than on impulse."
    if direction == "down":
        if setup_quality == "A" and risk_level == "low":
            return "Short bias stays intact. Failed bounces are cleaner than forcing entries after a heavy flush."
        if risk_level == "high":
            return "Bias still leans short, but the move is unstable. Wait for a cleaner rejection or fresh weakness."
        return "Short bias is still on, but the better trade usually comes after a weak bounce, not panic selling."
    return "Best read is to stay patient. Let price break the range cleanly before taking fresh risk."


def direction_to_bias(direction: str) -> str:
    if direction == "up":
        return "long"
    if direction == "down":
        return "short"
    return "neutral"


def build_risk_reward_ratio(
    direction: str,
    entry_level: float | None,
    invalidation_level: float | None,
    target_level: float | None,
) -> float | None:
    if entry_level is None or invalidation_level is None or target_level is None:
        return None

    if direction == "up":
        risk = entry_level - invalidation_level
        reward = target_level - entry_level
    elif direction == "down":
        risk = invalidation_level - entry_level
        reward = entry_level - target_level
    else:
        return None

    if risk <= 0 or reward <= 0:
        return None
    return round(reward / risk, 2)


def build_trade_plan(direction: str, risk_level: str, features: dict[str, float]) -> dict[str, float | str | None]:
    latest_close = float(features["latest_close_price"])
    short_sma = float(features["short_sma"])
    support_level = float(features["support_level"])
    resistance_level = float(features["resistance_level"])
    volatility_pct = max(0.5, float(features["volatility_pct"]) * 0.6)
    buffer_multiplier = 1.15 if risk_level == "high" else 1.0
    stop_buffer_pct = volatility_pct * buffer_multiplier

    if direction == "up":
        entry_level = support_level if risk_level == "high" else max(support_level, min(latest_close, short_sma))
        invalidation_level = min(support_level, entry_level) * (1.0 - (stop_buffer_pct / 100.0))
        stop_distance = max(entry_level - invalidation_level, latest_close * 0.005)
        target_level = resistance_level if resistance_level > latest_close else entry_level + (stop_distance * 1.8)
        return {
            "entry_plan": f"Prefer long entries on a pullback near ${entry_level:,.2f} instead of chasing straight strength.",
            "entry_level": round(entry_level, 2),
            "invalidation_plan": f"If BTC loses ${invalidation_level:,.2f}, the long read is no longer clean.",
            "invalidation_level": round(invalidation_level, 2),
            "target_plan": f"First upside target sits near ${target_level:,.2f} if buyers keep control.",
            "target_level": round(target_level, 2),
        }

    if direction == "down":
        entry_level = resistance_level if risk_level == "high" else min(resistance_level, max(latest_close, short_sma))
        invalidation_level = max(resistance_level, entry_level) * (1.0 + (stop_buffer_pct / 100.0))
        stop_distance = max(invalidation_level - entry_level, latest_close * 0.005)
        target_level = support_level if support_level < latest_close else entry_level - (stop_distance * 1.8)
        return {
            "entry_plan": f"Prefer short entries on a weak bounce toward ${entry_level:,.2f} instead of selling the flush.",
            "entry_level": round(entry_level, 2),
            "invalidation_plan": f"If BTC reclaims ${invalidation_level:,.2f}, the short read weakens fast.",
            "invalidation_level": round(invalidation_level, 2),
            "target_plan": f"First downside target sits near ${target_level:,.2f} if sellers stay in control.",
            "target_level": round(target_level, 2),
        }

    return {
        "entry_plan": (
            f"Wait for BTC to break above ${resistance_level:,.2f} or below ${support_level:,.2f} before taking fresh directional risk."
        ),
        "entry_level": None,
        "invalidation_plan": (
            f"If price snaps back inside the ${support_level:,.2f} to ${resistance_level:,.2f} range, step back and wait again."
        ),
        "invalidation_level": None,
        "target_plan": "No clean target yet while BTC is still range-bound.",
        "target_level": None,
    }
