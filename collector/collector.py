from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

COLLECTOR_MODE = os.getenv("COLLECTOR_MODE", "mock").strip().lower()

if COLLECTOR_MODE == "mock":
    import mock_collector as active_collector
elif COLLECTOR_MODE in {"market", "coinbase", "coinbase-exchange"}:
    import market_collector as active_collector
else:
    raise RuntimeError("COLLECTOR_MODE must be one of: mock, market, coinbase, coinbase-exchange")


def main() -> None:
    active_collector.main()


if __name__ == "__main__":
    main()
