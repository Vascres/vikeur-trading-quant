# Technical Decisions

## Modular monolith for the core engine

The core processing stages are strongly related and latency-sensitive. Keeping them inside one modular process reduces operational complexity and unnecessary network boundaries while import-linter contracts preserve architectural separation at the code level.

## FastAPI for the backend API

FastAPI provides a typed Python API layer suitable for asynchronous integrations and a clean separation between the dashboard and backend services.

## PostgreSQL / TimescaleDB

PostgreSQL provides durable relational storage. TimescaleDB is used where time-series characteristics make it useful for market and historical event data.

## Redis for transient coordination

Redis is used for fast event distribution and coordination between services. Persistent business state remains in PostgreSQL.

## Docker Compose

Compose provides reproducible service configuration on a VPS without introducing orchestration complexity that would be disproportionate to the current project scale.

## Backend-side governance

Sensitive actions, especially execution-mode changes and risk controls, are validated on the backend. The frontend is not trusted to enforce business-critical security rules.

## Controlled deployment

Container images are built and published through CI, while the VPS deployment remains an explicit operational action. This reduces the risk of an unintended production deployment from a normal source-control push.

## Explicit limitations

Experimental components and unfinished capabilities are documented rather than presented as production-ready. This is intentional: technical debt and known limitations should be visible to anyone evaluating the project.
