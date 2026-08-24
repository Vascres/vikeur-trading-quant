"""Mapping de symboles - un point unique de vérité par exchange (Phase 8, §3.1).

Volontairement explicite (pas de déduction automatique par regex) : un
symbole non prévu doit échouer bruyamment, jamais être deviné silencieusement.
"""

# HTX (Phase 7) : format natif "btcusdt" (minuscule, concaténé, sans séparateur)
HTX_NATIVE_TO_CANONICAL: dict[str, str] = {
    "btcusdt": "BTC/USDT",
    "ethusdt": "ETH/USDT",
    "solusdt": "SOL/USDT",
}

# Binance (ADR-0012) : même format natif que HTX (minuscule, concaténé) -
# une coïncidence entre ces deux exchanges précis, pas une règle générale
# à supposer pour un futur troisième exchange (Kraken, par exemple,
# utilise un format différent - à vérifier explicitement à l'ajout).
BINANCE_NATIVE_TO_CANONICAL: dict[str, str] = {
    "btcusdt": "BTC/USDT",
    "ethusdt": "ETH/USDT",
    "solusdt": "SOL/USDT",
}

_EXCHANGE_MAPPINGS: dict[str, dict[str, str]] = {
    "htx": HTX_NATIVE_TO_CANONICAL,
    "binance": BINANCE_NATIVE_TO_CANONICAL,
}


class UnknownSymbolError(ValueError):
    """Levée quand un symbole natif ne figure pas dans le mapping explicite."""


def to_canonical(exchange: str, native_symbol: str) -> str:
    try:
        mapping = _EXCHANGE_MAPPINGS[exchange]
    except KeyError as exc:
        raise UnknownSymbolError(f"Exchange inconnu du mapping : {exchange}") from exc

    try:
        return mapping[native_symbol.lower()]
    except KeyError as exc:
        raise UnknownSymbolError(
            f"Symbole natif '{native_symbol}' non prévu dans le mapping de {exchange}. "
            "Ajouter explicitement l'entrée avant de suivre cette paire."
        ) from exc


def canonical_to_native(exchange: str, canonical_symbol: str) -> str:
    mapping = _EXCHANGE_MAPPINGS[exchange]
    reverse = {v: k for k, v in mapping.items()}
    try:
        return reverse[canonical_symbol]
    except KeyError as exc:
        raise UnknownSymbolError(
            f"Symbole canonique '{canonical_symbol}' non prévu pour {exchange}."
        ) from exc
