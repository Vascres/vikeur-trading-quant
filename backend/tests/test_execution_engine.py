"""Tests de la Phase 12 : signature HTX et modes d'exécution."""

import base64
import hashlib
import hmac
from decimal import Decimal
from unittest.mock import AsyncMock
from urllib.parse import quote

import pytest

from data_collector.adapters.htx import HTX_REST_BASE_URL, HTXAdapter
from execution_engine.factory import get_execution_mode
from execution_engine.modes.backtest import BacktestExecutionMode
from execution_engine.modes.paper import PaperExecutionMode
from shared.exchange_adapter import OrderSide


def _recompute_expected_signature(secret: str, method: str, path: str, params: dict) -> str:
    sorted_items = sorted(params.items())
    encoded = "&".join(f"{quote(str(k), safe='')}={quote(str(v), safe='')}" for k, v in sorted_items)
    host = HTX_REST_BASE_URL.replace("https://", "")
    payload = f"{method}\n{host}\n{path}\n{encoded}"
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def test_sign_request_raises_without_api_keys():
    adapter = HTXAdapter()
    with pytest.raises(RuntimeError, match="Clés API HTX non configurées"):
        adapter._sign_request("GET", "/v1/account/accounts")


def test_sign_request_produces_verifiable_signature():
    adapter = HTXAdapter(api_key="test-key", api_secret="test-secret")
    signed = adapter._sign_request("GET", "/v1/account/accounts", {"foo": "bar"})

    assert signed["AccessKeyId"] == "test-key"
    assert signed["SignatureMethod"] == "HmacSHA256"
    assert signed["SignatureVersion"] == "2"
    assert "Signature" in signed

    params_without_signature = {k: v for k, v in signed.items() if k != "Signature"}
    expected_signature = _recompute_expected_signature(
        "test-secret", "GET", "/v1/account/accounts", params_without_signature
    )
    assert signed["Signature"] == expected_signature


def test_sign_request_post_excludes_extra_params_from_signature():
    """Pour un POST, seuls les 4 paramètres d'authentification entrent dans la signature (Phase 12, §5)."""
    adapter = HTXAdapter(api_key="test-key", api_secret="test-secret")
    signed = adapter._sign_request("POST", "/v1/order/orders/place", {"amount": "1.0"})

    assert "amount" not in signed  # les paramètres de l'ordre ne sont jamais dans la querystring signée
    assert set(signed.keys()) == {
        "AccessKeyId",
        "SignatureMethod",
        "SignatureVersion",
        "Timestamp",
        "Signature",
    }


@pytest.mark.asyncio
async def test_backtest_mode_requires_explicit_price():
    mode = BacktestExecutionMode(db_pool=None)
    with pytest.raises(ValueError, match="prix historique explicite"):
        await mode.execute(
            risk_check_id=1,
            decision_id=1,
            exchange="htx",
            symbol="BTC/USDT",
            side="buy",
            quantity=Decimal("0.01"),
            price=None,
        )


def test_factory_rejects_invalid_mode():
    with pytest.raises(ValueError, match="Mode d'exécution invalide"):
        get_execution_mode("not-a-real-mode", db_pool=None)


def test_factory_requires_adapter_for_real_mode():
    with pytest.raises(ValueError, match="nécessite au moins un ExchangeAdapter"):
        get_execution_mode("real", db_pool=None, exchange_adapters=None)


def test_factory_returns_paper_mode_by_default():
    mode = get_execution_mode("paper", db_pool=None)
    assert isinstance(mode, PaperExecutionMode)


@pytest.mark.asyncio
async def test_place_order_converts_canonical_symbol_to_native(monkeypatch):
    """Corrige un bug pré-existant découvert en ADR-0012 : place_order
    recevait le symbole canonique (ex. 'BTC/USDT') et faisait .lower()
    directement, produisant un symbole invalide côté HTX."""
    from unittest.mock import AsyncMock, MagicMock

    adapter = HTXAdapter(api_key="test-key", api_secret="test-secret")
    monkeypatch.setattr(adapter, "_get_account_id", AsyncMock(return_value="123"))

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"status": "ok", "data": "order-1"}
    adapter._http_client.post = AsyncMock(return_value=fake_response)

    await adapter.place_order(
        symbol="BTC/USDT", side=OrderSide.BUY, quantity=Decimal("0.01"), price=Decimal("60000")
    )

    _, kwargs = adapter._http_client.post.call_args
    assert kwargs["json"]["symbol"] == "btcusdt"


@pytest.mark.asyncio
async def test_real_execution_mode_selects_adapter_by_exchange():
    """ADR-0012 : RealExecutionMode doit servir plusieurs exchanges, en
    sélectionnant l'adaptateur correspondant à `exchange` à chaque appel,
    jamais un adaptateur unique figé à la construction."""
    from unittest.mock import AsyncMock

    from execution_engine.modes.real import RealExecutionMode

    htx_adapter = AsyncMock()
    htx_adapter.place_order.return_value = "htx-order-1"
    htx_adapter.get_order_status.return_value = {"state": "filled", "filled_amount": "0.01"}

    binance_adapter = AsyncMock()

    mode = RealExecutionMode(db_pool=None, exchange_adapters={"htx": htx_adapter, "binance": binance_adapter})

    # Monkeypatch de apply_fill/insert_order_row non nécessaire ici : on
    # vérifie uniquement la sélection d'adaptateur, pas la persistance.
    import execution_engine.modes.real as real_module

    real_module.apply_fill = AsyncMock()
    real_module.insert_order_row = AsyncMock()

    await mode.execute(
        risk_check_id=1,
        decision_id=1,
        exchange="htx",
        symbol="BTC/USDT",
        side="buy",
        quantity=Decimal("0.01"),
        price=Decimal("60000"),
    )

    htx_adapter.place_order.assert_called_once()
    binance_adapter.place_order.assert_not_called()


def test_real_execution_mode_adapter_for_raises_when_exchange_unconfigured():
    from execution_engine.modes.real import RealExecutionMode

    mode = RealExecutionMode(db_pool=None, exchange_adapters={"htx": object()})

    with pytest.raises(ValueError, match="Aucun adaptateur configuré"):
        mode._adapter_for("binance")


# --- Étape 9 (16/08/2026) : triptyque d'ordres futures ---


def _make_futures_mode(futures_adapter):
    from execution_engine.modes.real import RealExecutionMode

    events = []
    mode = RealExecutionMode(
        db_pool=None,
        exchange_adapters={"htx": AsyncMock()},
        futures_exchange_adapters={"htx": futures_adapter},
        publish_journal_event=lambda t, p: events.append((t, p)),
    )
    return mode, events


@pytest.mark.asyncio
async def test_futures_entry_attaches_stop_loss_when_adapter_supports_it():
    """Le cas nominal du triptyque : ouverture -> stop-loss posé
    immédiatement après, jamais dans le même appel API (Binance ne le
    permet pas, cf. docstring de binance_futures.py)."""
    import execution_engine.modes.real as real_module
    from execution_engine.positions import FuturesFillResult
    from shared.futures_adapter import PositionSide, SupportsConditionalOrders

    class _FakeConditionalAdapter:
        """Duck-type minimal de SupportsConditionalOrders + FuturesExchangeAdapter."""

        def __init__(self):
            self.place_order = AsyncMock(return_value="entry-order-1")
            self.place_stop_loss = AsyncMock(return_value="stop-order-1")
            self.cancel_order = AsyncMock()

    assert isinstance(_FakeConditionalAdapter(), SupportsConditionalOrders)  # vérifie le typage structurel

    futures_adapter = _FakeConditionalAdapter()
    mode, events = _make_futures_mode(futures_adapter)

    real_module.insert_order_row = AsyncMock()
    real_module.apply_fill = AsyncMock(
        return_value=FuturesFillResult(position_id=42, opened=True, closed=False)
    )
    record_mock = AsyncMock()
    real_module.record_conditional_order_ids = record_mock

    real_module.is_futures_real_trading_enabled = AsyncMock(return_value=True)

    await mode.execute(
        risk_check_id=1,
        decision_id=1,
        exchange="htx",
        symbol="ETH/USDT",
        side="buy",
        quantity=Decimal("0.05"),
        price=Decimal("3000"),
        market_type="futures_perpetual",
    )

    futures_adapter.place_stop_loss.assert_awaited_once()
    call_args = futures_adapter.place_stop_loss.call_args.args
    assert call_args[1] == PositionSide.LONG
    assert call_args[2] < Decimal("3000")  # stop en dessous de l'entrée pour un LONG
    record_mock.assert_awaited_once_with(mode._db_pool, 42, stop_loss_order_id="stop-order-1")
    assert any(t == "execution_engine.futures_stop_loss_attached" for t, _ in events)


@pytest.mark.asyncio
async def test_futures_entry_journals_loudly_when_adapter_lacks_conditional_orders():
    """HTX aujourd'hui : aucune capacité de stop-loss automatique -
    jamais silencieux, une position sans filet doit être visible."""
    import execution_engine.modes.real as real_module
    from execution_engine.positions import FuturesFillResult

    futures_adapter = AsyncMock()  # AsyncMock nu : ne satisfait PAS SupportsConditionalOrders
    futures_adapter.place_order.return_value = "entry-order-1"
    mode, events = _make_futures_mode(futures_adapter)

    real_module.insert_order_row = AsyncMock()
    real_module.apply_fill = AsyncMock(
        return_value=FuturesFillResult(position_id=7, opened=True, closed=False)
    )

    real_module.is_futures_real_trading_enabled = AsyncMock(return_value=True)

    await mode.execute(
        risk_check_id=1,
        decision_id=1,
        exchange="htx",
        symbol="ETH/USDT",
        side="buy",
        quantity=Decimal("0.05"),
        price=Decimal("3000"),
        market_type="futures_perpetual",
    )

    assert any(t == "execution_engine.futures_position_without_stop_loss_capability" for t, _ in events)


@pytest.mark.asyncio
async def test_futures_entry_journals_when_stop_loss_placement_fails():
    import execution_engine.modes.real as real_module
    from execution_engine.positions import FuturesFillResult

    class _FailingConditionalAdapter:
        def __init__(self):
            self.place_order = AsyncMock(return_value="entry-order-1")
            self.place_stop_loss = AsyncMock(side_effect=RuntimeError("panne réseau"))
            self.cancel_order = AsyncMock()

    futures_adapter = _FailingConditionalAdapter()
    mode, events = _make_futures_mode(futures_adapter)

    real_module.insert_order_row = AsyncMock()
    real_module.apply_fill = AsyncMock(
        return_value=FuturesFillResult(position_id=7, opened=True, closed=False)
    )
    record_mock = AsyncMock()
    real_module.record_conditional_order_ids = record_mock

    real_module.is_futures_real_trading_enabled = AsyncMock(return_value=True)

    await mode.execute(
        risk_check_id=1,
        decision_id=1,
        exchange="htx",
        symbol="ETH/USDT",
        side="buy",
        quantity=Decimal("0.05"),
        price=Decimal("3000"),
        market_type="futures_perpetual",
    )

    assert any(t == "execution_engine.futures_stop_loss_placement_failed" for t, _ in events)
    record_mock.assert_not_awaited()  # aucun ordre posé -> rien à enregistrer


@pytest.mark.asyncio
async def test_futures_close_cancels_dangling_conditional_orders():
    """Mandat : "annulant au passage le Stop et le TP restants" - le cas
    où la position se ferme (agent ou stop) doit annuler tout ordre
    conditionnel encore ouvert."""
    import execution_engine.modes.real as real_module
    from execution_engine.positions import FuturesFillResult

    class _FakeConditionalAdapter:
        def __init__(self):
            self.place_order = AsyncMock(return_value="entry-order-1")
            self.place_stop_loss = AsyncMock()
            self.cancel_order = AsyncMock()

    futures_adapter = _FakeConditionalAdapter()
    mode, events = _make_futures_mode(futures_adapter)

    real_module.insert_order_row = AsyncMock()
    real_module.apply_fill = AsyncMock(
        return_value=FuturesFillResult(
            position_id=9,
            opened=False,
            closed=True,
            previous_stop_loss_order_id="stop-order-old",
            previous_take_profit_order_id="tp-order-old",
        )
    )

    real_module.is_futures_real_trading_enabled = AsyncMock(return_value=True)

    await mode.execute(
        risk_check_id=1,
        decision_id=1,
        exchange="htx",
        symbol="ETH/USDT",
        side="sell",
        quantity=Decimal("0.05"),
        price=Decimal("2900"),
        market_type="futures_perpetual",
    )

    futures_adapter.place_stop_loss.assert_not_awaited()  # pas une ouverture, pas de nouveau stop
    assert futures_adapter.cancel_order.await_count == 2
    cancelled_ids = {c.args[1] for c in futures_adapter.cancel_order.call_args_list}
    assert cancelled_ids == {"stop-order-old", "tp-order-old"}


@pytest.mark.asyncio
async def test_futures_reinforcement_does_not_attempt_new_stop_loss():
    """Renforcement (même sens) : ni ouverture ni clôture - aucune
    tentative de stop-loss ni d'annulation."""
    import execution_engine.modes.real as real_module
    from execution_engine.positions import FuturesFillResult

    class _FakeConditionalAdapter:
        def __init__(self):
            self.place_order = AsyncMock(return_value="entry-order-1")
            self.place_stop_loss = AsyncMock()
            self.cancel_order = AsyncMock()

    futures_adapter = _FakeConditionalAdapter()
    mode, events = _make_futures_mode(futures_adapter)

    real_module.insert_order_row = AsyncMock()
    real_module.apply_fill = AsyncMock(
        return_value=FuturesFillResult(position_id=9, opened=False, closed=False)
    )

    real_module.is_futures_real_trading_enabled = AsyncMock(return_value=True)

    await mode.execute(
        risk_check_id=1,
        decision_id=1,
        exchange="htx",
        symbol="ETH/USDT",
        side="buy",
        quantity=Decimal("0.05"),
        price=Decimal("3000"),
        market_type="futures_perpetual",
    )

    futures_adapter.place_stop_loss.assert_not_awaited()
    futures_adapter.cancel_order.assert_not_awaited()
