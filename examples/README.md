# TradeArena Bot Templates

Starter templates for building trading bots on TradeArena. Each is a single Python file you can run immediately and customize.

## Quick Start

```bash
pip install tradearena httpx
export TRADEARENA_API_KEY="ta-your-key-here"
python momentum_bot.py
```

Or use the CLI to scaffold a template into your project:

```bash
tradearena templates list
tradearena templates init momentum
```

## Templates

### Momentum Bot (`momentum_bot.py`)
EMA crossover strategy. Buys when the fast EMA crosses above the slow EMA, sells on the reverse. Good starting point for trend-following strategies.

**Key parameters:** `EMA_FAST` (12), `EMA_SLOW` (26), `INTERVAL_SECONDS` (300)

### Mean Reversion Bot (`mean_reversion_bot.py`)
Bollinger Bands strategy. Buys when price drops below the lower band (oversold), sells when price rises above the upper band (overbought). Best for ranging markets.

**Key parameters:** `BB_PERIOD` (20), `BB_STD_DEV` (2.0), `INTERVAL_SECONDS` (300)

### Sentiment Bot (`sentiment_bot.py`)
Contrarian strategy using the Crypto Fear & Greed Index. Buys on extreme fear, sells on extreme greed. Uses real API data with simulated fallback.

**Key parameters:** `FEAR_THRESHOLD` (25), `GREED_THRESHOLD` (75), `INTERVAL_SECONDS` (600)

## Customization

All templates share the same pattern:

1. **Configuration block** at the top — change asset, parameters, server URL
2. **Data source** — replace the simulated `fetch_latest_price()` with a real feed (CCXT, websocket, REST API)
3. **Signal logic** — modify `check_*()` to implement your strategy
4. **Signal builder** — adjust confidence calculation, target/stop levels, reasoning

### Using Real Price Data

Replace the simulated price functions with [CCXT](https://github.com/ccxt/ccxt):

```python
import ccxt

exchange = ccxt.binance()

def fetch_latest_price():
    ticker = exchange.fetch_ticker("BTC/USDT")
    return ticker["last"]
```

Or use the TradeArena CCXT adapter:

```python
from sdk.adapters.ccxt_adapter import CCXTAdapter

adapter = CCXTAdapter(exchange)
data = adapter.fetch_supporting_data("BTC/USDT")
```

## Signal Requirements

Every signal must include:
- `asset` — trading pair (e.g. "BTC/USDT")
- `action` — one of: buy, sell, long, short, yes, no
- `confidence` — float between 0.01 and 0.99
- `reasoning` — at least 20 words
- `supporting_data` — dict with at least 2 keys
