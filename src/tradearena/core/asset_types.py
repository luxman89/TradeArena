"""Asset type classification for multi-asset support.

Classifies assets as crypto, stock, or forex based on symbol patterns.
Used by the oracle to route to the correct price provider chain.
"""

from __future__ import annotations

from enum import StrEnum

# Common crypto quote currencies
_CRYPTO_QUOTES = {"USDT", "BUSD", "USDC", "BTC", "ETH", "BNB"}

# Well-known crypto base symbols (non-exhaustive, covers majors)
_CRYPTO_BASES = {
    "BTC",
    "ETH",
    "BNB",
    "SOL",
    "XRP",
    "DOGE",
    "ADA",
    "AVAX",
    "DOT",
    "MATIC",
    "LINK",
    "UNI",
    "ATOM",
    "LTC",
    "BCH",
    "NEAR",
    "APT",
    "ARB",
    "OP",
    "FIL",
    "ICP",
    "HBAR",
    "VET",
    "ALGO",
    "FTM",
    "SAND",
    "MANA",
    "AXS",
    "CRV",
    "AAVE",
    "MKR",
    "SNX",
    "COMP",
    "SUSHI",
    "YFI",
    "SHIB",
    "PEPE",
    "WIF",
    "BONK",
    "FLOKI",
    "TRX",
    "EOS",
    "XLM",
    "XMR",
    "ZEC",
    "DASH",
    "ETC",
    "NEO",
    "WAVES",
    "THETA",
    "RUNE",
    "INJ",
    "SUI",
    "SEI",
    "TIA",
    "JUP",
    "WLD",
    "PYTH",
    "JTO",
    "STRK",
}

# Common forex pairs (base currencies)
_FOREX_BASES = {"EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"}
_FOREX_QUOTES = {"USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"}

# Common stock exchange suffixes
_STOCK_SUFFIXES = {".US", ".NYSE", ".NASDAQ", ".L", ".T", ".HK", ".SS", ".SZ"}


class AssetType(StrEnum):
    CRYPTO = "crypto"
    STOCK = "stock"
    FOREX = "forex"


def classify_asset(asset: str) -> AssetType:
    """Classify an asset string into crypto, stock, or forex.

    Heuristics (in order):
    1. Explicit forex pattern: contains "/" with both sides in forex currency sets,
       or ends with "=X" (Yahoo Finance forex convention)
    2. Explicit crypto: ends with a known crypto quote currency (USDT, BUSD, etc.)
       or contains "/" with a crypto quote, or base is a known crypto symbol
    3. Stock suffix: ends with a known exchange suffix (.US, .L, etc.)
    4. Forex pair: 6-char string where both 3-char halves are forex currencies
    5. Default: treat as stock (most conservative for unknown symbols like AAPL, TSLA)
    """
    upper = asset.upper().replace(" ", "")

    # Yahoo Finance forex convention: EURUSD=X
    if upper.endswith("=X"):
        return AssetType.FOREX

    # Slash-separated pair: BTC/USDT or EUR/USD
    if "/" in upper:
        parts = upper.split("/", 1)
        base, quote = parts[0], parts[1]
        # Forex if both sides are fiat currencies
        if base in _FOREX_BASES | {"USD"} and quote in _FOREX_QUOTES:
            return AssetType.FOREX
        # Crypto if quote is a crypto currency
        if quote in _CRYPTO_QUOTES or base in _CRYPTO_BASES:
            return AssetType.CRYPTO
        return AssetType.STOCK

    # Explicit crypto quote suffix
    for quote in sorted(_CRYPTO_QUOTES, key=len, reverse=True):
        if upper.endswith(quote) and len(upper) > len(quote):
            return AssetType.CRYPTO

    # Known crypto base
    if upper in _CRYPTO_BASES:
        return AssetType.CRYPTO

    # Stock exchange suffix
    for suffix in _STOCK_SUFFIXES:
        if upper.endswith(suffix.upper()):
            return AssetType.STOCK

    # 6-char potential forex pair (e.g., EURUSD, GBPJPY)
    if len(upper) == 6:
        potential_base = upper[:3]
        potential_quote = upper[3:]
        if potential_base in _FOREX_BASES | {"USD"} and potential_quote in _FOREX_QUOTES:
            return AssetType.FOREX

    # Default: stock (covers tickers like AAPL, TSLA, MSFT)
    return AssetType.STOCK
