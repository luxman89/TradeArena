"""TradeArena CLI — submit signals, check status, and compete from the terminal."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import httpx

CONFIG_DIR = Path.home() / ".tradearena"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_BASE_URL = "https://tradearena.duckdns.org"


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


def _require_creator_id(cfg: dict) -> str:
    creator_id = cfg.get("creator_id")
    if not creator_id:
        click.echo("Error: creator_id not set. Submit a signal first or run:", err=True)
        click.echo("  tradearena init --api-key <key> --creator-id <id>", err=True)
        sys.exit(1)
    return creator_id


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
    creator_id = _require_creator_id(cfg)

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
# battles (legacy top-level command kept for backward compatibility)
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--all", "show_all", is_flag=True, help="Include resolved battles.")
def battles(show_all: bool) -> None:
    """Show active battles (shortcut for 'battle list')."""
    cfg = _require_config("api_key")
    _show_battle_list(cfg, show_all)


def _show_battle_list(cfg: dict, show_all: bool) -> None:
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
        click.echo(f"{'ID':<10} {'Creator 1':<20} {'Creator 2':<20} {'Status'}")
        click.echo("-" * 60)
        for b in active:
            bid = b.get("battle_id", b.get("id", "?"))[:8]
            click.echo(
                f"{bid:<10} "
                f"{b.get('creator1_id', b.get('creator_1_id', '?')):<20} "
                f"{b.get('creator2_id', b.get('creator_2_id', '?')):<20} "
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
                    bid = b.get("battle_id", b.get("id", "?"))[:8]
                    winner = b.get("winner_id", "draw")
                    click.echo(f"  {bid}  winner={winner}  status={b.get('status', '?')}")


# ---------------------------------------------------------------------------
# battle (group)
# ---------------------------------------------------------------------------


@cli.group()
def battle() -> None:
    """Manage 1v1 battles."""


@battle.command("challenge")
@click.argument("bot_id")
def battle_challenge(bot_id: str) -> None:
    """Challenge a bot to a 1v1 battle."""
    cfg = _require_config("api_key")
    creator_id = _require_creator_id(cfg)

    resp = _api(
        cfg,
        "POST",
        "/battle/create",
        json={"creator1_id": creator_id, "creator2_id": bot_id},
    )
    if resp.status_code == 404:
        click.echo(f"Error: bot '{bot_id}' not found.", err=True)
        sys.exit(1)
    if resp.status_code == 409:
        click.echo(f"Error: active battle already exists with '{bot_id}'.", err=True)
        sys.exit(1)
    if resp.status_code == 422:
        click.echo("Error: cannot battle against yourself.", err=True)
        sys.exit(1)
    if resp.status_code not in (200, 201):
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    result = resp.json()
    click.echo("Battle created!")
    click.echo(f"  Battle ID: {result.get('battle_id')}")
    click.echo(f"  You:       {result.get('creator1_id')}")
    click.echo(f"  Opponent:  {result.get('creator2_id')}")
    click.echo(f"  Window:    {result.get('window_days', 7)} days")
    click.echo(f"  Status:    {result.get('status')}")


@battle.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include resolved battles.")
def battle_list(show_all: bool) -> None:
    """Show your recent battles."""
    cfg = _require_config("api_key")
    _show_battle_list(cfg, show_all)


@battle.command("status")
@click.argument("battle_id")
def battle_status(battle_id: str) -> None:
    """Show battle details and result."""
    cfg = _require_config("api_key")

    resp = _api(cfg, "GET", f"/battle/{battle_id}")
    if resp.status_code == 404:
        click.echo(f"Error: battle '{battle_id}' not found.", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    b = resp.json()
    click.echo(f"Battle: {b.get('battle_id')}")
    click.echo(f"  Status:     {b.get('status')}")
    click.echo(f"  Creator 1:  {b.get('creator1_id')}")
    click.echo(f"  Creator 2:  {b.get('creator2_id')}")
    click.echo(f"  Window:     {b.get('window_days')} days")
    click.echo(f"  Type:       {b.get('battle_type')}")
    click.echo(f"  Created:    {b.get('created_at', '')[:19]}")

    if b.get("status") == "RESOLVED":
        click.echo(f"  Resolved:   {(b.get('resolved_at') or '')[:19]}")
        click.echo(f"  Winner:     {b.get('winner_id') or 'draw'}")
        click.echo(f"  Score:      {b.get('creator1_score', 0):.4f} vs {b.get('creator2_score', 0):.4f}")
        click.echo(f"  Margin:     {b.get('margin', 0):.4f}")

        for label, key in [("Creator 1", "creator1_details"), ("Creator 2", "creator2_details")]:
            details = b.get(key)
            if details and isinstance(details, dict):
                click.echo(f"  {label} details:")
                for dk, dv in details.items():
                    if isinstance(dv, float):
                        click.echo(f"    {dk}: {dv:.4f}")
                    else:
                        click.echo(f"    {dk}: {dv}")


# ---------------------------------------------------------------------------
# matchmaking (group)
# ---------------------------------------------------------------------------


@cli.group()
def matchmaking() -> None:
    """ELO matchmaking queue."""


@matchmaking.command("join")
def matchmaking_join() -> None:
    """Enter the matchmaking queue."""
    cfg = _require_config("api_key")
    creator_id = _require_creator_id(cfg)

    resp = _api(cfg, "POST", "/matchmaking/queue", params={"bot_id": creator_id})
    if resp.status_code == 404:
        click.echo(f"Error: creator '{creator_id}' not found.", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    result = resp.json()
    click.echo(result.get("message", "Joined matchmaking queue."))


@matchmaking.command("status")
def matchmaking_status() -> None:
    """Check your matchmaking status and ELO rating."""
    cfg = _require_config("api_key")
    creator_id = _require_creator_id(cfg)

    resp = _api(cfg, "GET", f"/bots/{creator_id}/rating")
    if resp.status_code == 404:
        click.echo(f"Error: creator '{creator_id}' not found.", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    r = resp.json()
    click.echo(f"ELO Rating: {r.get('elo', 1200)}")
    click.echo(f"  Matches: {r.get('matches_played', 0)}")
    click.echo(f"  Wins:    {r.get('wins', 0)}")
    click.echo(f"  Losses:  {r.get('losses', 0)}")
    click.echo(f"  Draws:   {r.get('draws', 0)}")


# ---------------------------------------------------------------------------
# tournament (group)
# ---------------------------------------------------------------------------


@cli.group()
def tournament() -> None:
    """Browse and compete in tournaments."""


@tournament.command("list")
@click.option(
    "--status",
    "tournament_status",
    default=None,
    type=click.Choice(["registering", "in_progress", "completed"], case_sensitive=False),
    help="Filter by tournament status.",
)
def tournament_list(tournament_status: str | None) -> None:
    """Show upcoming and active tournaments."""
    cfg = _require_config("api_key")

    params: dict = {}
    if tournament_status:
        params["tournament_status"] = tournament_status

    resp = _api(cfg, "GET", "/tournaments", params=params)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    data = resp.json()
    tournaments = data.get("tournaments", [])
    if not tournaments:
        click.echo("No tournaments found.")
        return

    click.echo(f"Tournaments ({data.get('total', len(tournaments))}):")
    click.echo(f"{'ID':<10} {'Name':<25} {'Format':<20} {'Status':<14} {'Participants'}")
    click.echo("-" * 80)
    for t in tournaments:
        tid = t.get("id", "?")[:8]
        entries = t.get("entries", [])
        max_p = t.get("max_participants", "?")
        click.echo(
            f"{tid:<10} "
            f"{t.get('name', '?'):<25} "
            f"{t.get('format', '?'):<20} "
            f"{t.get('status', '?'):<14} "
            f"{len(entries)}/{max_p}"
        )


@tournament.command("register")
@click.argument("tournament_id")
def tournament_register(tournament_id: str) -> None:
    """Register your bot in a tournament."""
    cfg = _require_config("api_key")
    creator_id = _require_creator_id(cfg)

    resp = _api(
        cfg,
        "POST",
        f"/tournament/{tournament_id}/join",
        json={"creator_id": creator_id},
    )
    if resp.status_code == 404:
        click.echo(f"Error: tournament or creator not found.", err=True)
        sys.exit(1)
    if resp.status_code == 409:
        detail = resp.json().get("detail", "Registration conflict.")
        click.echo(f"Error: {detail}", err=True)
        sys.exit(1)
    if resp.status_code not in (200, 201):
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    result = resp.json()
    entries = result.get("entries", [])
    click.echo(f"Registered in tournament '{result.get('name')}'!")
    click.echo(f"  Tournament ID: {result.get('id')}")
    click.echo(f"  Format:        {result.get('format')}")
    click.echo(f"  Participants:  {len(entries)}/{result.get('max_participants')}")
    click.echo(f"  Status:        {result.get('status')}")


@tournament.command("bracket")
@click.argument("tournament_id")
def tournament_bracket(tournament_id: str) -> None:
    """Show tournament bracket."""
    cfg = _require_config("api_key")

    resp = _api(cfg, "GET", f"/tournament/{tournament_id}")
    if resp.status_code == 404:
        click.echo(f"Error: tournament '{tournament_id}' not found.", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    t = resp.json()
    click.echo(f"Tournament: {t.get('name')}")
    click.echo(f"  Format: {t.get('format')}  |  Status: {t.get('status')}  |  Round: {t.get('current_round', 0)}")

    entries = t.get("entries", [])
    if entries:
        click.echo(f"\nParticipants ({len(entries)}):")
        click.echo(f"  {'Seed':<6} {'Creator':<25} {'Points':>7} {'Status'}")
        click.echo("  " + "-" * 55)
        for e in sorted(entries, key=lambda x: x.get("seed", 999)):
            elim = "eliminated" if e.get("eliminated_at") else "active"
            click.echo(
                f"  {e.get('seed', '?'):<6} "
                f"{e.get('creator_id', '?'):<25} "
                f"{e.get('points', 0):>7} "
                f"{elim}"
            )

    matches = t.get("matches", [])
    if matches:
        # Group by round
        rounds: dict[int, list] = {}
        for m in matches:
            r = m.get("round", 0)
            rounds.setdefault(r, []).append(m)

        click.echo("\nMatches:")
        for r in sorted(rounds):
            click.echo(f"  Round {r}:")
            for m in sorted(rounds[r], key=lambda x: x.get("match_order", 0)):
                winner = m.get("winner_bot_id") or "pending"
                click.echo(
                    f"    Match {m.get('match_order')}: "
                    f"battle={m.get('battle_id', '?')[:8]}  "
                    f"winner={winner}"
                )


# ---------------------------------------------------------------------------
# templates (group)
# ---------------------------------------------------------------------------

TEMPLATES = {
    "momentum": {
        "file": "momentum_bot.py",
        "description": "EMA crossover — trend-following with fast/slow moving averages",
    },
    "mean-reversion": {
        "file": "mean_reversion_bot.py",
        "description": "Bollinger Bands — buys oversold, sells overbought conditions",
    },
    "sentiment": {
        "file": "sentiment_bot.py",
        "description": "Contrarian — uses Fear & Greed Index against crowd sentiment",
    },
}


def _get_templates_dir() -> Path:
    """Locate the bundled templates directory."""
    # Check relative to this file (installed package)
    pkg_dir = Path(__file__).resolve().parent.parent.parent / "examples"
    if pkg_dir.is_dir():
        return pkg_dir
    # Fallback: check current working directory
    cwd_dir = Path.cwd() / "examples"
    if cwd_dir.is_dir():
        return cwd_dir
    return pkg_dir  # return expected path even if missing


@cli.group()
def templates() -> None:
    """Browse and scaffold starter bot templates."""


@templates.command("list")
def templates_list() -> None:
    """Show available bot templates."""
    click.echo("Available templates:\n")
    for name, info in TEMPLATES.items():
        click.echo(f"  {name:<18} {info['description']}")
    click.echo("\nScaffold one into your project:")
    click.echo("  tradearena templates init <name>")


@templates.command("init")
@click.argument("name", type=click.Choice(list(TEMPLATES.keys()), case_sensitive=False))
@click.option("--output", "-o", default=None, help="Output path (default: <template>.py in cwd).")
def templates_init(name: str, output: str | None) -> None:
    """Copy a bot template into the current directory."""
    template = TEMPLATES[name.lower()]
    src = _get_templates_dir() / template["file"]

    if not src.exists():
        click.echo(f"Error: template file not found at {src}", err=True)
        click.echo("Templates may not be installed. Check your tradearena installation.", err=True)
        sys.exit(1)

    dst = Path(output) if output else Path.cwd() / template["file"]
    if dst.exists():
        if not click.confirm(f"{dst.name} already exists. Overwrite?"):
            click.echo("Aborted.")
            return

    dst.write_text(src.read_text())
    click.echo(f"Created {dst}")
    click.echo("\nNext steps:")
    click.echo("  1. export TRADEARENA_API_KEY='ta-your-key-here'")
    click.echo(f"  2. Edit {dst.name} to customize parameters")
    click.echo(f"  3. python {dst.name}")


# ---------------------------------------------------------------------------
# rating
# ---------------------------------------------------------------------------


@cli.command()
def rating() -> None:
    """Show your current ELO rating and rank."""
    cfg = _require_config("api_key")
    creator_id = _require_creator_id(cfg)

    # Get rating
    resp = _api(cfg, "GET", f"/bots/{creator_id}/rating")
    if resp.status_code == 404:
        click.echo(f"Error: creator '{creator_id}' not found.", err=True)
        sys.exit(1)
    if resp.status_code != 200:
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    r = resp.json()
    click.echo(f"ELO Rating: {r.get('elo', 1200)}")
    click.echo(f"  Matches: {r.get('matches_played', 0)}  W: {r.get('wins', 0)}  L: {r.get('losses', 0)}  D: {r.get('draws', 0)}")

    # Get leaderboard position
    lb_resp = _api(cfg, "GET", "/leaderboard/elo", params={"limit": 100})
    if lb_resp.status_code == 200:
        lb = lb_resp.json()
        entries = lb.get("entries", [])
        rank = None
        for i, entry in enumerate(entries, 1):
            if entry.get("bot_id") == creator_id:
                rank = i
                break
        if rank:
            click.echo(f"  Rank:    #{rank} of {lb.get('total', len(entries))}")
        else:
            click.echo(f"  Rank:    unranked ({lb.get('total', 0)} rated players)")


# ---------------------------------------------------------------------------
# webhook (group)
# ---------------------------------------------------------------------------


@cli.group()
def webhook() -> None:
    """Manage webhook notifications."""


@webhook.command("set")
@click.argument("url", required=False, default=None)
@click.option("--clear", is_flag=True, help="Remove the webhook URL.")
def webhook_set(url: str | None, clear: bool) -> None:
    """Set your webhook URL for real-time event notifications.

    Pass a URL to register, or --clear to remove it.
    """
    cfg = _require_config("api_key")

    if clear:
        payload: dict = {"url": None}
    elif url:
        payload = {"url": url}
    else:
        click.echo("Error: provide a URL or use --clear.", err=True)
        sys.exit(1)

    resp = _api(cfg, "POST", "/creator/webhook", json=payload)
    if resp.status_code not in (200, 201):
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    result = resp.json()
    click.echo(result.get("message", "Done."))
    if result.get("webhook_url"):
        click.echo(f"  Webhook URL: {result['webhook_url']}")


@webhook.command("test")
def webhook_test() -> None:
    """Send a test event to your registered webhook URL."""
    cfg = _require_config("api_key")

    resp = _api(cfg, "POST", "/creator/webhook/test")
    if resp.status_code not in (200, 201):
        click.echo(f"Error ({resp.status_code}): {resp.text}", err=True)
        sys.exit(1)

    result = resp.json()
    if result.get("success"):
        click.echo(f"Test webhook delivered successfully (HTTP {result.get('status_code')}).")
    else:
        error = result.get("error") or f"HTTP {result.get('status_code')}"
        click.echo(f"Test webhook failed: {error}")
    click.echo(f"  URL: {result.get('webhook_url')}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
