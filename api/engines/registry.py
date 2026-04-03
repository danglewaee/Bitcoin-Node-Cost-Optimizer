from __future__ import annotations

import os

from engines.base import BaseSignalEngine
from engines.heuristic_engine import HeuristicSignalEngine
from engines.ml_challenger_engine import MLChallengerSignalEngine


def get_signal_engine(engine_name: str | None = None) -> BaseSignalEngine:
    selected_engine = (engine_name or os.getenv("SIGNAL_ENGINE", "heuristic")).strip().lower()
    if selected_engine == "heuristic":
        return HeuristicSignalEngine()
    if selected_engine in {"ml_challenger", "ml-challenger"}:
        return MLChallengerSignalEngine()
    raise RuntimeError(
        f"Unsupported SIGNAL_ENGINE '{selected_engine}'. Supported engines: heuristic, ml_challenger."
    )
