"""Tests de la Phase 13 : chaque règle de risque en isolation."""

from datetime import timedelta
from decimal import Decimal

from risk_engine.rules.daily_loss_limit import DailyLossLimitRule
from risk_engine.rules.futures_notional_exposure_cap import FuturesNotionalExposureCapRule
from risk_engine.rules.kill_switch import KillSwitchRule
from risk_engine.rules.liquidity_slippage_fees import LiquiditySlippageFeesRule
from risk_engine.rules.max_consecutive_loss import MaxConsecutiveLossRule
from risk_engine.rules.max_exposure import MaxExposureRule
from risk_engine.rules.position_sizing import PositionSizingRule
from shared.risk_rule import RiskContext
from shared.strategy import Side


def _context(**overrides) -> RiskContext:
    base = dict(
        decision_id=1,
        exchange="htx",
        symbol="BTC/USDT",
        suggested_side=Side.BUY,
        success_probability=0.6,
        expected_value=0.01,
        risk_reward_ratio=2.0,
        available_capital=Decimal(1000),
        current_price=Decimal(60000),
        current_exposure_notional=Decimal(0),
        daily_realized_pnl=Decimal(0),
        consecutive_losses=0,
        order_book_bids=[(Decimal(59990), Decimal(1))],
        order_book_asks=[(Decimal(60010), Decimal(1))],
        kill_switch_active=False,
    )
    base.update(overrides)
    return RiskContext(**base)


# --- KillSwitchRule ---


def test_kill_switch_blocks_when_active():
    result = KillSwitchRule().check(_context(kill_switch_active=True))
    assert result.passed is False


def test_kill_switch_allows_when_inactive():
    result = KillSwitchRule().check(_context(kill_switch_active=False))
    assert result.passed is True


# --- PositionSizingRule ---


def test_position_sizing_computes_positive_quantity():
    context = _context(risk_reward_ratio=2.0)
    result = PositionSizingRule().check(context)
    assert result.passed is True
    assert context.suggested_quantity is not None
    assert context.suggested_quantity > 0


def test_position_sizing_caps_at_max_risk_fraction():
    context = _context(risk_reward_ratio=100.0)  # ferait exploser une Kelly non plafonnée
    PositionSizingRule().check(context)
    max_notional = context.available_capital * Decimal("0.02")
    assert context.suggested_quantity * context.current_price <= max_notional * Decimal("1.0001")


def test_position_sizing_rejects_invalid_price():
    result = PositionSizingRule().check(_context(current_price=Decimal(0)))
    assert result.passed is False


# --- MaxExposureRule ---


def test_max_exposure_rejects_without_prior_sizing():
    context = _context()  # suggested_quantity jamais rempli
    result = MaxExposureRule().check(context)
    assert result.passed is False


def test_max_exposure_passes_within_limit():
    context = _context(current_exposure_notional=Decimal(0))
    context.suggested_quantity = Decimal("0.001")  # notional ~60, largement sous 30% de 1000
    result = MaxExposureRule().check(context)
    assert result.passed is True


def test_max_exposure_rejects_beyond_limit():
    context = _context(current_exposure_notional=Decimal(290))
    context.suggested_quantity = Decimal("0.01")  # ajoute ~600 de notional -> dépasse 30% de 1000
    result = MaxExposureRule().check(context)
    assert result.passed is False


# --- DailyLossLimitRule ---


def test_daily_loss_limit_passes_when_within_bounds():
    result = DailyLossLimitRule().check(_context(daily_realized_pnl=Decimal(-10)))
    assert result.passed is True


def test_daily_loss_limit_blocks_when_exceeded():
    result = DailyLossLimitRule().check(_context(daily_realized_pnl=Decimal(-60)))  # > 5% de 1000
    assert result.passed is False


# --- MaxConsecutiveLossRule ---


def test_max_consecutive_loss_passes_below_threshold():
    result = MaxConsecutiveLossRule().check(_context(consecutive_losses=2))
    assert result.passed is True


def test_max_consecutive_loss_blocks_at_threshold():
    result = MaxConsecutiveLossRule().check(_context(consecutive_losses=3))
    assert result.passed is False


def test_max_consecutive_loss_never_blocks_closing_an_already_open_position():
    """Le cœur du correctif du 19/08/2026 (question légitime soulevée
    par l'opérateur) : si une position est DÉJÀ ouverte
    (`open_position_quantity > 0`), cette décision la clôture - jamais
    une nouvelle prise de risque. La bloquer créerait un risque de
    blocage permanent, en particulier côté spot (aucun stop-loss
    automatique à l'exchange, contrairement au futures) : la seule
    façon de sortir d'une position bloquée serait qu'une AUTRE
    clôture rompe la série de pertes en premier - impossible si toutes
    les clôtures sont elles-mêmes bloquées."""
    context = _context(consecutive_losses=5)  # bien au-dessus du seuil
    context.open_position_quantity = Decimal("0.01")

    result = MaxConsecutiveLossRule().check(context)

    assert result.passed is True


def test_max_consecutive_loss_still_blocks_a_brand_new_position_during_the_pause():
    """Le comportement protecteur original reste intact : une décision
    qui ouvrirait une position ENTIÈREMENT NOUVELLE (aucune position
    déjà ouverte sur ce symbole) est toujours bloquée pendant la pause."""
    context = _context(consecutive_losses=5)
    context.open_position_quantity = Decimal("0")

    result = MaxConsecutiveLossRule().check(context)

    assert result.passed is False


def test_max_consecutive_loss_pause_expires_after_the_configured_delay():
    """Second correctif du 19/08/2026 : sans position ouverte à
    clôturer, rien ne pouvait jamais rompre la série - la pause était
    DÉFINITIVE, pas temporaire. Vérifie qu'une perte suffisamment
    ancienne (au-delà de PAUSE_EXPIRY) lève la pause d'elle-même, sans
    qu'aucun trade n'ait eu besoin de clôturer gagnant entre-temps."""
    from datetime import UTC, datetime, timedelta

    from risk_engine.rules.max_consecutive_loss import PAUSE_EXPIRY

    context = _context(consecutive_losses=5)
    context.open_position_quantity = Decimal("0")
    context.most_recent_loss_closed_at = datetime.now(tz=UTC) - PAUSE_EXPIRY - timedelta(minutes=1)

    result = MaxConsecutiveLossRule().check(context)

    assert result.passed is True


def test_max_consecutive_loss_pause_still_active_just_before_expiry():
    from datetime import UTC, datetime, timedelta

    from risk_engine.rules.max_consecutive_loss import PAUSE_EXPIRY

    context = _context(consecutive_losses=5)
    context.open_position_quantity = Decimal("0")
    context.most_recent_loss_closed_at = datetime.now(tz=UTC) - PAUSE_EXPIRY + timedelta(minutes=1)

    result = MaxConsecutiveLossRule().check(context)

    assert result.passed is False


def test_max_consecutive_loss_no_timestamp_never_crashes_and_stays_blocked():
    """Robustesse : si `most_recent_loss_closed_at` n'a jamais été
    fourni (None), la règle doit rester prudente (bloquer), jamais
    lever une exception ni autoriser par défaut."""
    context = _context(consecutive_losses=5)
    context.open_position_quantity = Decimal("0")
    context.most_recent_loss_closed_at = None

    result = MaxConsecutiveLossRule().check(context)

    assert result.passed is False


# --- LiquiditySlippageFeesRule ---


def test_liquidity_rule_passes_with_sufficient_depth_and_expected_value():
    context = _context(expected_value=0.01)  # 100 bps, net de frais mesurés (ADR-0016)
    context.suggested_quantity = Decimal("0.5")
    result = LiquiditySlippageFeesRule().check(context)
    assert result.passed is True


def test_liquidity_rule_rejects_insufficient_depth():
    context = _context()
    context.suggested_quantity = Decimal(10)  # bien plus que les 1.0 disponibles au carnet
    result = LiquiditySlippageFeesRule().check(context)
    assert result.passed is False
    assert "Liquidité insuffisante" in result.reason


def test_liquidity_rule_rejects_when_net_margin_not_positive():
    """ADR-0016 : plus de constante de frais fixe ici - `expected_value` est
    désormais déjà net de frais réels mesurés (meta_engine/cost_estimation.py) ;
    cette règle rejette simplement si la marge nette restante n'est pas
    positive, sans réappliquer un second filtre de frais non synchronisé."""
    context = _context(expected_value=0.0)
    context.suggested_quantity = Decimal("0.1")
    result = LiquiditySlippageFeesRule().check(context)
    assert result.passed is False
    assert "espérance nette" in result.reason.lower()


def test_liquidity_rule_passes_with_small_but_positive_net_margin():
    """Avant ADR-0016, une marge nette de 10 bps aurait été rejetée par la
    constante fixe de 20 bps même si les frais réels avaient déjà été
    déduits en amont - désormais acceptée, la marge étant déjà nette."""
    context = _context(expected_value=0.001)  # 10 bps, déjà net de frais mesurés
    context.suggested_quantity = Decimal("0.1")
    result = LiquiditySlippageFeesRule().check(context)
    assert result.passed is True


def test_liquidity_rule_rejects_without_prior_sizing():
    result = LiquiditySlippageFeesRule().check(_context())
    assert result.passed is False


# --- FuturesNotionalExposureCapRule (ADR-0018, révisé décision CTO 16/08/2026) ---


def test_futures_cap_passes_for_spot_market_type():
    context = _context()
    context.market_type = "spot"
    result = FuturesNotionalExposureCapRule().check(context)
    assert result.passed is True


def test_futures_cap_rejects_without_prior_sizing():
    context = _context()
    context.market_type = "futures_perpetual"
    context.suggested_quantity = None
    result = FuturesNotionalExposureCapRule().check(context)
    assert result.passed is False


def test_futures_cap_passes_when_margin_within_available_capital():
    context = _context(available_capital=Decimal("1000"), current_price=Decimal("100"))
    context.market_type = "futures_perpetual"
    context.suggested_quantity = Decimal("5")  # notionnel 500, marge à 2x = 250 <= 1000
    result = FuturesNotionalExposureCapRule().check(context)
    assert result.passed is True


def test_futures_cap_rejects_when_margin_exceeds_available_capital():
    context = _context(available_capital=Decimal("100"), current_price=Decimal("100"))
    context.market_type = "futures_perpetual"
    context.suggested_quantity = Decimal("5")  # notionnel 500, marge à 2x = 250 > 100
    result = FuturesNotionalExposureCapRule().check(context)
    assert result.passed is False
    assert "marge requise" in result.reason.lower()


def test_futures_cap_allows_notional_above_capital_when_margin_fits():
    """Le changement concret de la décision CTO du 16/08/2026 : un
    notionnel supérieur au capital disponible est désormais accepté,
    tant que la MARGE (notionnel / 2x) reste couverte - impossible avant
    cette révision (ADR-0018 imposait notionnel <= capital)."""
    context = _context(available_capital=Decimal("250"), current_price=Decimal("100"))
    context.market_type = "futures_perpetual"
    context.suggested_quantity = Decimal("5")  # notionnel 500 > 250 (capital), marge 250 <= 250
    result = FuturesNotionalExposureCapRule().check(context)
    assert result.passed is True


# --- Ordre réel d'exécution (19/08/2026) ---
#
# Bug réel trouvé le soir de l'activation de FUTURES_ROUTING_ENABLED
# (ADR-0019) : chaque décision futures échouait systématiquement avec
# "Aucune quantité dimensionnée à vérifier", jamais détecté avant faute
# de décision futures réelle ayant atteint le Risk Engine. Les tests
# ci-dessus (test_futures_cap_*) posent `context.suggested_quantity` à
# la main AVANT d'appeler la règle en isolation - ils ne pouvaient donc
# jamais révéler un problème d'ORDRE d'exécution entre règles. Les
# tests suivants exercent `ACTIVE_RULES` tel qu'il tourne réellement en
# production, dans son ordre réel, jamais une liste reconstruite à la main.


def test_active_rules_runs_position_sizing_before_rules_that_need_quantity():
    """Vérifie l'ordre RÉEL de production (import direct de
    `risk_engine.main.ACTIVE_RULES`, jamais une copie) - ce test à lui
    seul aurait empêché la régression du 19/08/2026."""
    from risk_engine.main import ACTIVE_RULES

    rule_names = [rule.rule_name for rule in ACTIVE_RULES]
    position_sizing_index = rule_names.index("position_sizing")

    quantity_dependent_rules = ["futures_notional_exposure_cap", "max_exposure", "liquidity_slippage_fees"]
    for rule_name in quantity_dependent_rules:
        assert rule_name in rule_names, f"{rule_name} devrait être dans ACTIVE_RULES."
        assert position_sizing_index < rule_names.index(rule_name), (
            f"position_sizing doit tourner avant {rule_name} (qui lit context.suggested_quantity), "
            f"or il est positionné après dans ACTIVE_RULES."
        )


def test_active_rules_end_to_end_futures_decision_gets_properly_sized_and_accepted():
    """Le test le plus direct : fait tourner TOUTE la chaîne
    `ACTIVE_RULES`, dans l'ordre réel, sur une décision futures neuve -
    `context.suggested_quantity` commence à None (jamais posé à la
    main), exactement comme une vraie décision arrivant au Risk Engine.
    Avant le correctif du 19/08/2026, ce test échouait avec
    FINAL_VERDICT refusé sur futures_notional_exposure_cap."""
    from risk_engine.main import ACTIVE_RULES

    context = _context(
        available_capital=Decimal("350"),
        current_price=Decimal("65000"),
        suggested_side=Side.SELL,
        risk_reward_ratio=2.0,
    )
    context.market_type = "futures_perpetual"
    context.open_position_quantity = Decimal("0")
    assert context.suggested_quantity is None  # jamais posé à la main - condition de départ réelle

    results = [rule.check(context) for rule in ACTIVE_RULES]

    failed = [r for r in results if not r.passed]
    assert (
        not failed
    ), f"Règle(s) refusée(s) de façon inattendue : {[(r.rule_name, r.reason) for r in failed]}"
    assert context.suggested_quantity is not None
    assert context.suggested_quantity > 0


# --- Seuils réglables par variable d'environnement (19/08/2026) ---


def test_max_consecutive_losses_threshold_is_configurable_via_env_var():
    """Vérifie que MAX_CONSECUTIVE_LOSSES et MAX_CONSECUTIVE_LOSS_PAUSE_HOURS
    lisent réellement leur variable d'environnement au chargement du
    module - pas juste une valeur par défaut inerte. Recharge le module
    avec une variable définie, plutôt que de supposer que le code source
    fait ce qu'il prétend faire."""
    import importlib
    import os

    import risk_engine.rules.max_consecutive_loss as module

    original_env = os.environ.get("MAX_CONSECUTIVE_LOSSES")
    original_hours_env = os.environ.get("MAX_CONSECUTIVE_LOSS_PAUSE_HOURS")
    try:
        os.environ["MAX_CONSECUTIVE_LOSSES"] = "8"
        os.environ["MAX_CONSECUTIVE_LOSS_PAUSE_HOURS"] = "3"
        importlib.reload(module)

        assert module.MAX_CONSECUTIVE_LOSSES == 8
        assert module.PAUSE_EXPIRY == timedelta(hours=3)

        # Avec le nouveau seuil réglé à 8, une série de 5 pertes ne doit
        # plus bloquer une nouvelle position - preuve que la valeur
        # rechargée est bien celle réellement utilisée par check(),
        # jamais seulement exposée en façade.
        context = _context(consecutive_losses=5)
        context.open_position_quantity = Decimal("0")
        result = module.MaxConsecutiveLossRule().check(context)
        assert result.passed is True
    finally:
        if original_env is None:
            os.environ.pop("MAX_CONSECUTIVE_LOSSES", None)
        else:
            os.environ["MAX_CONSECUTIVE_LOSSES"] = original_env
        if original_hours_env is None:
            os.environ.pop("MAX_CONSECUTIVE_LOSS_PAUSE_HOURS", None)
        else:
            os.environ["MAX_CONSECUTIVE_LOSS_PAUSE_HOURS"] = original_hours_env
        importlib.reload(module)  # restaure l'état par défaut pour les tests suivants
