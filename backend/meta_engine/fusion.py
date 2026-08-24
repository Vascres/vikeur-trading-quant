"""Fusion de plusieurs EngineOpinion (ADR-0010).

Fonction pure : aucun accès DB/réseau/horloge - même exigence que
Feature/DecisionEngine. Méthode retenue : moyenne pondérée par la
confiance déclarée de chaque moteur, avec arbitrage de camp par le
score pondéré le plus élevé (cf. ADR-0010 pour les alternatives
envisagées et pourquoi elles n'ont pas été retenues à ce stade).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shared.decision_engine import EngineOpinion, Side


@dataclass(frozen=True)
class FusionResult:
    suggested_side: Side | None  # None si aucun camp ne l'emporte clairement
    fused_score: float | None  # None si suggested_side est None
    weights_applied: dict[str, float] = field(default_factory=dict)  # nom du moteur -> confiance utilisée
    contributing_engine_names: list[str] = field(default_factory=list)


def fuse_opinions(opinions: list[EngineOpinion], engine_names: list[str]) -> FusionResult:
    """`opinions` et `engine_names` doivent être alignés (même index =
    même moteur) - l'appelant (decision_engine, backtesting) est
    responsable de cet appariement, cette fonction reste pure et ne
    connaît aucun identifiant de moteur au-delà du nom fourni."""
    if not opinions:
        return FusionResult(suggested_side=None, fused_score=None)

    by_side: dict[Side, list[tuple[EngineOpinion, str]]] = {Side.BUY: [], Side.SELL: []}
    for opinion, name in zip(opinions, engine_names, strict=True):
        by_side[opinion.suggested_side].append((opinion, name))

    weighted_scores: dict[Side, float] = {}
    weights_by_side: dict[Side, dict[str, float]] = {}

    for side, entries in by_side.items():
        if not entries:
            continue
        total_confidence = sum(opinion.confidence for opinion, _ in entries)
        if total_confidence <= 0:
            continue  # aucune confiance exploitable de ce côté
        weighted_scores[side] = (
            sum(opinion.confidence * opinion.score for opinion, _ in entries) / total_confidence
        )
        weights_by_side[side] = {name: opinion.confidence for opinion, name in entries}

    if not weighted_scores:
        return FusionResult(suggested_side=None, fused_score=None)

    if len(weighted_scores) == 2 and weighted_scores[Side.BUY] == weighted_scores[Side.SELL]:
        # Désaccord exact entre les deux camps - jamais un choix arbitraire
        # entre deux camps à égalité (ADR-0010).
        return FusionResult(suggested_side=None, fused_score=None)

    winning_side = max(weighted_scores, key=lambda side: weighted_scores[side])
    contributing_names = [name for _, name in by_side[winning_side]]

    return FusionResult(
        suggested_side=winning_side,
        fused_score=weighted_scores[winning_side],
        weights_applied=weights_by_side[winning_side],
        contributing_engine_names=contributing_names,
    )
