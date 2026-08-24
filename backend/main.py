"""Point d'entrée unique du backend (Phase 18, §1).

Regroupe les boucles jusqu'ici lancées comme des scripts indépendants,
conformément au monolithe modulaire décidé en Phase 2 - un seul
processus, modules internes séparés, communication interne par Redis
Pub/Sub (déjà en place depuis la Phase 2/7).

C'est ce module qui tourne dans le conteneur "engine" (Phase 18, §1),
distinct du conteneur "api" (backend/api/main.py) qui reste réactif
indépendamment de la charge du moteur.
"""

import asyncio
import logging

import data_collector.main as data_collector_main
import data_normalizer.main as data_normalizer_main
import decision_engine.main as decision_engine_main
import execution_engine.main as execution_engine_main
import feature_engine.main as feature_engine_main

logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("Démarrage du moteur (5 boucles internes, Phase 18 §1)")

    await asyncio.gather(
        data_collector_main.main(),
        data_normalizer_main.main(),
        feature_engine_main.main(),
        decision_engine_main.main(),
        execution_engine_main.main(),  # inclut l'appel au risk_engine (Phase 13)
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
