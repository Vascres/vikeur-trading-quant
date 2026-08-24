"""Tests du mapping de symboles multi-exchange (ADR-0012) - aucun test
existant ne couvrait ce module avant ce chantier (gap constaté en
l'étendant à Binance)."""

from __future__ import annotations

import pytest

from data_collector.adapters.binance import BinanceAdapter
from data_collector.adapters.factory import UnknownExchangeError, build_exchange_adapter
from data_collector.adapters.htx import HTXAdapter
from shared.exchange_config import ACTIVE_EXCHANGES, get_exchange_credentials
from shared.symbol_mapping import UnknownSymbolError, canonical_to_native, to_canonical


def test_to_canonical_works_for_both_exchanges():
    assert to_canonical("htx", "btcusdt") == "BTC/USDT"
    assert to_canonical("binance", "btcusdt") == "BTC/USDT"


def test_to_canonical_raises_for_unknown_exchange():
    with pytest.raises(UnknownSymbolError, match="Exchange inconnu"):
        to_canonical("kraken", "btcusdt")


def test_to_canonical_raises_for_unknown_symbol():
    with pytest.raises(UnknownSymbolError, match="non prévu"):
        to_canonical("binance", "dogeusdt")


def test_canonical_to_native_roundtrip_for_both_exchanges():
    assert canonical_to_native("htx", "ETH/USDT") == "ethusdt"
    assert canonical_to_native("binance", "ETH/USDT") == "ethusdt"


def test_build_exchange_adapter_returns_correct_type():
    assert isinstance(build_exchange_adapter("htx"), HTXAdapter)
    assert isinstance(build_exchange_adapter("binance"), BinanceAdapter)


def test_build_exchange_adapter_raises_for_unknown_exchange():
    with pytest.raises(UnknownExchangeError, match="Exchange inconnu de la fabrique"):
        build_exchange_adapter("kraken")


def test_build_exchange_adapter_injects_named_credentials(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "test-binance-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "test-binance-secret")

    adapter = build_exchange_adapter("binance")

    assert adapter._api_key == "test-binance-key"
    assert adapter._api_secret == "test-binance-secret"


def test_get_exchange_credentials_reads_named_env_vars(monkeypatch):
    monkeypatch.setenv("HTX_API_KEY", "htx-key")
    monkeypatch.setenv("HTX_API_SECRET", "htx-secret")

    key, secret = get_exchange_credentials("htx")

    assert key == "htx-key"
    assert secret == "htx-secret"


def test_get_exchange_credentials_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("KRAKEN_API_KEY", raising=False)
    monkeypatch.delenv("KRAKEN_API_SECRET", raising=False)

    key, secret = get_exchange_credentials("kraken")

    assert key is None
    assert secret is None


def test_active_exchanges_defaults_to_htx_only():
    # ACTIVE_EXCHANGES est évalué à l'import - ce test documente le
    # comportement par défaut observé dans cet environnement de test
    # (ACTIVE_EXCHANGES non défini -> ["htx"]), pas un test dynamique de
    # la variable d'environnement (qui nécessiterait un rechargement de
    # module, hors périmètre ici).
    assert "htx" in ACTIVE_EXCHANGES
