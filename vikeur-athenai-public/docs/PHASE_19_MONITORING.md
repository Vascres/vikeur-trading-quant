# Phase 19 — Monitoring et observabilité
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 19 en cours de validation.**
**Prérequis : Phases 1 à 18 validées.**

---

## 1. Besoin métier de cette phase

Le dashboard (Phase 18) affiche l'état du système **passivement** — il faut le regarder. Cette phase ajoute une surveillance **active** : détecter une anomalie (perte de données, disque plein, reconnexions excessives) et **alerter sans attendre qu'un humain ouvre le dashboard**, condition posée depuis la Phase 1 (« le système doit détecter et signaler ses propres pannes »).

## 2. Problème technique

Comment surveiller un système sur un VPS unique sans ajouter une pile d'observabilité lourde (Prometheus/Grafana : 2 conteneurs, configuration non triviale) qui contredirait la contrainte d'infra minimale de la Phase 3 ?

---

## 3. Options envisagées

| Option | Avantages | Limites | Retenue ? |
|---|---|---|---|
| Prometheus + Grafana | Standard de l'industrie, tableaux de bord riches | 2 conteneurs supplémentaires, configuration (exporters, scraping) non négligeable pour un opérateur seul, sur-dimensionné pour surveiller 5 boucles et une poignée de métriques | ❌ Rejetée en V1 (réévaluable si le système grossit, Phase 20) |
| **Service de surveillance maison, léger, basé sur `events_journal` déjà existant** | Aucune nouvelle brique d'infrastructure, réutilise le Journal (Phase 4 §5.5) déjà alimenté par tous les modules, coût de calcul négligeable | Moins de visualisation qu'un vrai tableau de bord de métriques (compensé par le dashboard, Phase 18) | **✅ Retenue** |

**Décision retenue** : un service `monitoring` léger qui interroge `events_journal` et l'état du système (disque, connexions), et alerte via un bot Telegram (gratuit, API simple, pas de serveur SMTP à gérer) — cohérent avec la philosophie d'infra minimale de la Phase 3.

---

## 4. Vérifications mises en place

| Vérification | Seuil (valeur de départ) | Alerte si |
|---|---|---|
| Fraîcheur des événements par module | Collecteur : 5 min ; Features/Décision : 3 min ; Risque/Exécution : 2 min | Aucun événement du module dans la fenêtre |
| Espace disque | 85% d'utilisation | Dépassement |
| Taux de reconnexion du collecteur | > 5 reconnexions / 15 min | Dépassement (cohérent avec le risque identifié en Phase 7, §8) |
| Kill switch actif | — | Notification informative (pas une anomalie, mais un état à ne pas ignorer) |

**Anti-spam** : chaque type d'alerte a un cooldown (30 minutes, stocké dans Redis) — une panne persistante alerte une fois, pas toutes les 15 secondes.

---

## 5. Fichiers produits dans cette phase

- `backend/monitoring/health_checks.py` — fonctions de vérification (pures autant que possible).
- `backend/monitoring/alerting.py` — envoi d'alertes Telegram.
- `backend/monitoring/main.py` — boucle de surveillance.
- `infra/docker-compose.yml` **(mis à jour)** — service `monitoring`.
- `infra/.env.example` **(mis à jour)** — `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- `backend/tests/test_monitoring.py`.

---

## 6. Auto-évaluation

**Faiblesses identifiées :**
- Les seuils (§4) sont des valeurs de départ, à ajuster une fois le système en fonctionnement réel.
- Un bot Telegram suppose que vous configuriez un bot et un chat — étape manuelle simple, documentée dans `.env.example`, mais non automatisée (volontairement : la configuration d'un canal d'alerte reste un geste humain, comme la création des clés API en Phase 7).

**Cohérence avec les phases précédentes :** ✅ réutilise `events_journal` (Phase 4) sans nouvelle infrastructure ; cohérent avec la philosophie d'infra minimale (Phase 3).

---

## 7. Prochaine étape

Phase 20 — Déploiement, sécurité, audit et mise en production : durcissement final avant toute mise en production réelle.
