"""Tests for multi-asset support: asset classification, provider routing, symbol conversion."""

from __future__ import annotations

import pytest

from tradearena.core.asset_types import AssetType, classify_asset
from tradearena.core.exchanges import (
    CRYPTO_PROVIDERS,
    FOREX_PROVIDERS,
    STOCK_PROVIDERS,
    YahooFinanceProvider,
)
from tradearena.core.oracle import _providers_for_asset, asset_to_symbol

# ---------------------------------------------------------------------------
# Asset classification tests
# ---------------------------------------------------------------------------


class TestClassifyAsset:
    """Test classify_asset heuristics."""

    @pytest.mark.parametrize(
        "asset",
        ["BTCUSDT", "ETHUSDT", "BTC/USDT", "ETH", "BTC", "SOLUSDT", "DOGEBUSD", "BNBUSDC"],
    )
    def test_crypto_assets(self, asset: str):
        assert classify_asset(asset) == AssetType.CRYPTO

    @pytest.mark.parametrize(
        "asset",
        ["AAPL", "TSLA", "MSFT", "GOOGL", "AMZN", "NVDA", "AAPL.US", "META.NASDAQ"],
    )
    def test_stock_assets(self, asset: str):
        assert classify_asset(asset) == AssetType.STOCK

    @pytest.mark.parametrize(
        "asset",
        ["EURUSD", "GBPJPY", "EUR/USD", "GBP/JPY", "AUDUSD", "USDCAD", "EURUSD=X"],
    )
    def test_forex_assets(self, asset: str):
        assert classify_asset(asset) == AssetType.FOREX

    def test_unknown_defaults_to_stock(self):
        """Unknown symbols default to stock (conservative)."""
        assert classify_asset("XYZ123") == AssetType.STOCK

    def test_case_insensitive(self):
        assert classify_asset("btcusdt") == AssetType.CRYPTO
        assert classify_asset("aapl") == AssetType.STOCK
        assert classify_asset("eurusd") == AssetType.FOREX

    def test_known_crypto_base_without_quote(self):
        """Bare crypto symbols like 'SOL' should classify as crypto."""
        assert classify_asset("SOL") == AssetType.CRYPTO
        assert classify_asset("LINK") == AssetType.CRYPTO


# ---------------------------------------------------------------------------
# Symbol conversion tests
# ---------------------------------------------------------------------------


class TestAssetToSymbol:
    """Test asset_to_symbol with different asset types."""

    def test_crypto_appends_usdt(self):
        assert asset_to_symbol("BTC", AssetType.CRYPTO) == "BTCUSDT"

    def test_crypto_already_has_usdt(self):
        assert asset_to_symbol("BTCUSDT", AssetType.CRYPTO) == "BTCUSDT"

    def test_crypto_slash_pair(self):
        assert asset_to_symbol("ETH/USDT", AssetType.CRYPTO) == "ETHUSDT"

    def test_stock_plain_ticker(self):
        assert asset_to_symbol("AAPL", AssetType.STOCK) == "AAPL"

    def test_stock_strips_suffix(self):
        assert asset_to_symbol("AAPL.US", AssetType.STOCK) == "AAPL"
        assert asset_to_symbol("TSLA.NASDAQ", AssetType.STOCK) == "TSLA"

    def test_forex_appends_x(self):
        assert asset_to_symbol("EURUSD", AssetType.FOREX) == "EURUSD=X"

    def test_forex_slash_pair(self):
        assert asset_to_symbol("EUR/USD", AssetType.FOREX) == "EURUSD=X"

    def test_forex_already_has_x(self):
        assert asset_to_symbol("EURUSD=X", AssetType.FOREX) == "EURUSD=X"

    def test_auto_classification_when_none(self):
        """When asset_type is None, classify automatically."""
        assert asset_to_symbol("BTCUSDT") == "BTCUSDT"
        assert asset_to_symbol("AAPL") == "AAPL"


# ---------------------------------------------------------------------------
# Provider routing tests
# ---------------------------------------------------------------------------


class TestProviderRouting:
    """Test _providers_for_asset returns correct provider chains."""

    def test_crypto_providers(self):
        providers = _providers_for_asset(AssetType.CRYPTO)
        assert providers is CRYPTO_PROVIDERS
        assert len(providers) == 3
        assert all(p.name in ("binance", "okx", "kraken") for p in providers)

    def test_stock_providers(self):
        providers = _providers_for_asset(AssetType.STOCK)
        assert providers is STOCK_PROVIDERS
        assert len(providers) == 1
        assert isinstance(providers[0], YahooFinanceProvider)

    def test_forex_providers(self):
        providers = _providers_for_asset(AssetType.FOREX)
        assert providers is FOREX_PROVIDERS
        assert len(providers) == 1
        assert isinstance(providers[0], YahooFinanceProvider)


# ---------------------------------------------------------------------------
# AssetType enum tests
# ---------------------------------------------------------------------------


class TestAssetTypeEnum:
    def test_values(self):
        assert AssetType.CRYPTO == "crypto"
        assert AssetType.STOCK == "stock"
        assert AssetType.FOREX == "forex"

    def test_from_string(self):
        assert AssetType("crypto") == AssetType.CRYPTO
        assert AssetType("stock") == AssetType.STOCK
        assert AssetType("forex") == AssetType.FOREX


# ---------------------------------------------------------------------------
# Yahoo Finance symbol mapping tests
# ---------------------------------------------------------------------------


class TestYahooFinanceSymbolMapping:
    def test_yf_symbol_stock(self):
        from tradearena.core.exchanges import _yf_symbol

        assert _yf_symbol("AAPL") == "AAPL"
        assert _yf_symbol("AAPL.US") == "AAPL"
        assert _yf_symbol("TSLA.NASDAQ") == "TSLA"

    def test_yf_symbol_forex(self):
        from tradearena.core.exchanges import _yf_symbol

        # Forex symbols are passed as-is (=X suffix added by asset_to_symbol)
        assert _yf_symbol("EURUSD=X") == "EURUSD=X"

    def test_yf_symbol_preserves_case(self):
        from tradearena.core.exchanges import _yf_symbol

        assert _yf_symbol("aapl") == "AAPL"
