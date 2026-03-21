"""TradeArena CLI — submit signals, check status, and view battles from the terminal."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import httpx

CONFIG_DIR = Path.home() / ".tradearena"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_BASE_URL = "https://tradearena.io"


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def _save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n")


def _require_config(*keys: str) -> dict:
    cfg = _load_config()
    missing = [k for k in keys if not cfg.get(k)]
    if missing:
        click.echo(f"Error: missing config key(s): {', '.join(missing)}", err=True)
        click.echo("Run `tradearena init --api-key <key>` first.", err=True)
        sys.exit(1)
    return cfg


def _api(cfg: dict, method: str, path: str, **kwargs) -> httpx.Response:
    url = cfg.get("base_url", DEFAULT_BASE_URL).rstrip("/") + path
    headers = kwargs.pop("headers", {})
    if cfg.get("api_key"):
        headers["X-API-Key"] = cfg["api_key"]
    try:
        return httpx.request(method, url, headers=headers, timeout=30.0, **kwargs)
    except httpx.ConnectError:
        base = cfg.get("base_url", DEFAULT_BASE_URL)
        click.echo(f"Error: cannot connect to {base}", err=True)
        click.echo("Check that the server is running or use --url to set a different address.", err=True)
        sys.exit(1)
    except httpx.TimeoutException:
        click.echo(f"Error: request to {url} timed out.", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(package_name="tradearena")
def cli() -> None:
    """TradeArena — trustless trading signal competition platform.

    Submit signals, track your score, and compete in battles from the terminal.
    """


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--api-key", required=True, help="Your TradeArena API key (starts with ta-).")
@click.option("--url", default=None, help=f"Server URL (default: {DEFAULT_BASE_URL}).")
@click.option("--creator-id", default=None, help="Your creator ID (auto-detected on first submit).")
def init(api_key: str, url: str | None, creator_id: str | None) -> None:
    """Set up local TradeArena config."""
    cfg = _load_config()
    cfg["api_key"] = api_key
    if url:
        cfg["base_url"] = url.rstrip("/")
    if creator_id:
        cfg["creator_id"] = creator_id
    _save_config(cfg)
    click.echo(f"Config saved to {CONFIG_FILE}")
    click.echo(f"  API key: {api_key[:6]}...{api_key[-4:]}")
    click.echo(f"  Server:  {cfg.get('base_url', DEFAULT_BASE_URL)}")
    if cfg.get("creator_id"):
        click.echo(f"  Creator: {cfg['creator_id']}")


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--asset", required=True, help="Trading pair (e.g. BTC/USDT).")
@click.option(
    "--action",
    required=True,
    type=click.Choice(["buy", "sell", "yes", "no", "long", "short"], case_sensitive=False),
    help="Signal action.",
)
@click.option("--confidence", required=True, type=float, help="Confidence 0.01-0.99.")
@click.option("--reasoning", required=True, help="Signal reasoning (min 20 words).")
@click.option("--data", multiple=True, help="Supporting data as key=value (at least 2).")
@click.option("--target-price", type=float, default=None, help="Target price.")
@click.option("--stop-loss", type=float, default=None, help="Stop loss price.")
@click.option("--timeframe", default=None, help="Timeframe (e.g. 1h, 4h, 1d).")
def submit(
    asset: str,
    action: str,
    confidence: float,
    reasoning: str,
    data: tuple[str, ...],
    target_price: float | None,
    stop_loss: float | None,
    timeframe: str | None,
) -> None:
    """Submit a trading signal."""
    cfg = _require_config("api_key")

    # Parse supporting_data from key=value pairs
    supporting_data: dict[str, str] = {}
    for item in data:
        if "=" not in item:
            click.echo(f"Error: --data must be key=value, got: {item}", err=True)
            sys.exit(1)
        k, v = item.split("=", 1)
        supporting_data[k.strip()] = v.strip()

    if len(supporting_data) < 2:
        click.echo("Error: at least 2 --data key=value pairs required.", err=True)
        sys.exit(1)

    payload: dict = {
        "asset": asset,
        "action": action.lower(),
        "confidence": confidence,
        "reasoning": reasoning,
        "supporting_data": supporting_data,
    }
    if target_price is not None:
        payload["target_price"] = target_price
    if stop_loss is not None:
        payload["stop_loss"] = stop_loss
    if timeframe is not None:
        payload["timeframe"] = timeframe

    resp = _api(cfg, "POST", "/signal", json=payload)
    if resp.status_code not in (200, 201):
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    result = resp.json()
    # Cache creator_id for status command
    if result.get("creator_id") and not cfg.get("creator_id"):
        cfg["creator_id"] = result["creator_id"]
        _save_config(cfg)

    click.echo("Signal submitted!")
    click.echo(f"  Signal ID: {result.get('signal_id')}")
    click.echo(f"  Asset:     {result.get('asset')}")
    click.echo(f"  Action:    {result.get('action')}")
    click.echo(f"  Hash:      {result.get('commitment_hash', '')[:16]}...")
    click.echo(f"  Creator:   {result.get('creator_id')}")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--limit", default=10, type=int, help="Number of recent signals to show.")
def status(limit: int) -> None:
    """Show your recent signals and scores."""
    cfg = _require_config("api_key")
    creator_id = cfg.get("creator_id")
    if not creator_id:
        click.echo("Error: creator_id not set. Submit a signal first or run:", err=True)
        click.echo("  tradearena init --api-key <key> --creator-id <id>", err=True)
        sys.exit(1)

    # Fetch profile
    resp = _api(cfg, "GET", f"/creator/{creator_id}")
    if resp.status_code != 200:
        click.echo(f"Error fetching profile ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    profile = resp.json()
    scores = profile.get("scores") or {}

    click.echo(f"Creator: {profile.get('display_name', creator_id)} ({creator_id})")
    click.echo(f"Division: {profile.get('division', 'unknown')}")
    if scores:
        click.echo(f"Composite Score: {scores.get('composite_score', 0):.4f}")
        click.echo(f"  Win Rate:      {scores.get('win_rate', 0):.2%}")
        click.echo(f"  Risk-Adj Ret:  {scores.get('risk_adjusted_return', 0):.4f}")
        click.echo(f"  Consistency:   {scores.get('consistency', 0):.4f}")
        click.echo(f"  Calibration:   {scores.get('confidence_calibration', 0):.4f}")
        click.echo(f"  Total Signals: {scores.get('total_signals', 0)}")

    # Fetch recent signals
    resp = _api(cfg, "GET", f"/creator/{creator_id}/signals", params={"limit": limit})
    if resp.status_code != 200:
        click.echo(f"Error fetching signals ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    signals = resp.json()
    if isinstance(signals, dict):
        signals = signals.get("signals", signals.get("items", []))

    if not signals:
        click.echo("\nNo signals yet.")
        return

    click.echo(f"\nRecent signals (last {limit}):")
    click.echo(f"{'Asset':<12} {'Action':<8} {'Conf':>6} {'Outcome':<10} {'Time'}")
    click.echo("-" * 60)
    for s in signals:
        outcome = s.get("outcome") or "pending"
        click.echo(
            f"{s.get('asset', '?'):<12} "
            f"{s.get('action', '?'):<8} "
            f"{s.get('confidence', 0):>5.2f}  "
            f"{outcome:<10} "
            f"{s.get('committed_at', '')[:19]}"
        )


# ---------------------------------------------------------------------------
# battles
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--all", "show_all", is_flag=True, help="Include resolved battles.")
def battles(show_all: bool) -> None:
    """Show active battles."""
    cfg = _require_config("api_key")

    resp = _api(cfg, "GET", "/battles/active")
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    active = resp.json()
    if isinstance(active, dict):
        active = active.get("battles", active.get("items", []))

    if not active:
        click.echo("No active battles.")
    else:
        click.echo(f"Active battles ({len(active)}):")
        click.echo(f"{'ID':<10} {'Creator 1':<20} {'Creator 2':<20} {'Asset':<12} {'Status'}")
        click.echo("-" * 75)
        for b in active:
            bid = b.get("id", b.get("battle_id", "?"))[:8]
            click.echo(
                f"{bid:<10} "
                f"{b.get('creator_1_id', '?'):<20} "
                f"{b.get('creator_2_id', '?'):<20} "
                f"{b.get('asset', '?'):<12} "
                f"{b.get('status', '?')}"
            )

    if show_all:
        resp = _api(cfg, "GET", "/battles/history", params={"limit": 20})
        if resp.status_code == 200:
            history = resp.json()
            if isinstance(history, dict):
                history = history.get("battles", history.get("items", []))
            if history:
                click.echo(f"\nRecent history ({len(history)}):")
                for b in history:
                    bid = b.get("id", b.get("battle_id", "?"))[:8]
                    winner = b.get("winner_id", "?")
                    click.echo(f"  {bid}  winner={winner}  status={b.get('status', '?')}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
