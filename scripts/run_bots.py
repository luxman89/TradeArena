"""One-shot bot runner -- registers bots, submits signals, prints oracle instructions.

Usage:
    uv run python scripts/run_bots.py [--base-url http://localhost:8000]
"""

from __future__ import annotations

import argparse
import sys

from bots.bb_bot import BollingerBot
from bots.ema_bot import EMACrossBot
from bots.rsi_bot import RSIRangerBot

SEP = "=" * 44


def main(base_url: str, force: bool = False) -> None:
    bots = [RSIRangerBot(base_url), EMACrossBot(base_url), BollingerBot(base_url)]

    # -- Register -------------------------------------------------------
    print(f"\n{SEP}")
    print("  TRADEARENA BOT RUNNER")
    print(f"{SEP}\n")
    print(">> Registering bots...\n")

    for bot in bots:
        try:
            bot.register()
            print(f"  [OK] {bot.name}")
            print(f"    creator_id : {bot.creator_id}")
            print(f"    api_key    : {bot.api_key}\n")
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAIL] {bot.name} -- registration failed: {exc}")
            sys.exit(1)

    # -- Generate & submit signals --------------------------------------
    print(">> Generating and submitting signals...\n")
    all_results: list[dict] = []
    for bot in bots:
        print(f"  {bot.name} ({', '.join(bot.assets)}):")
        results = bot.run(force=force)
        all_results.extend(results)
        print()

    # -- Summary table --------------------------------------------------
    print(SEP)
    print(f"  SUBMITTED {len(all_results)} SIGNAL(S)")
    print(SEP)
    if all_results:
        print(f"  {'BOT':<14} {'ASSET':<12} {'ACTION':<6} {'CONF':>6}  SIGNAL ID")
        print(f"  {'-'*14} {'-'*12} {'-'*6} {'-'*6}  {'-'*10}")
        for r in all_results:
            sig_id = (r.get("signal_id", "?") or "?")[:10] + "..."
            print(
                f"  {r.get('creator_id','?'):<14} "
                f"{r.get('asset','?'):<12} "
                f"{r.get('action','?'):<6} "
                f"{r.get('confidence', 0):>6.2f}  "
                f"{sig_id}"
            )
    else:
        print("  No signals generated -- market conditions did not trigger any strategy.")
        print("  (Try again later or check Binance data availability.)")

    # -- Oracle instructions --------------------------------------------
    print(f"\n{SEP}")
    print("  NEXT STEPS -- ORACLE RESOLUTION")
    print(SEP)
    print("\n  Signals use timeframe=1h. The background loop resolves them")
    print("  automatically every 5 min once 1h has elapsed.")
    print("\n  To check pending signals:")
    print(f"    curl {base_url}/oracle/status\n")
    print("  To force-resolve now (fetches live Binance prices):")
    print(f"    curl -X POST {base_url}/oracle/resolve\n")
    print("  To view updated leaderboard:")
    print(f"    curl {base_url}/leaderboard/crypto\n")
    print(f"  Arena UI: {base_url}/")
    print("  (New bot sprites appear on the trading floor after the next data refresh)\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TradeArena bot runner")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="TradeArena server base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force signal submission even when strategy conditions are not met",
    )
    args = parser.parse_args()
    main(args.base_url, force=args.force)
