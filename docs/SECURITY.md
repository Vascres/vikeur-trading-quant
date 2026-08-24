# Security

## Secrets

No production API keys, exchange secrets, Telegram bot tokens, database passwords or session secrets should be committed to the repository.

Use a local environment file derived from `infra/.env.example` and keep it outside Git.

The public snapshot intentionally contains only placeholders.

## Exchange credentials

Exchange API credentials should use the minimum required permissions. Withdrawal permissions must remain disabled unless there is a separate, explicit security review that requires them.

## Network isolation

The Docker Compose configuration places PostgreSQL and Redis on an internal network. They are not directly published through host ports.

## Authentication and sensitive operations

Sensitive API operations are protected server-side. The frontend is not considered a trusted security boundary.

## Live execution

Live execution is deliberately governed by backend checks and is separate from paper capital. The project includes a kill switch and risk controls.

## Public repository checklist

Before publishing a repository publicly:

- scan the complete Git history for secrets;
- remove any real credentials from history, not only from the current working tree;
- verify GitHub Actions secrets and permissions;
- verify deployment configuration contains no private identifiers that should remain confidential;
- verify logs and sample data contain no personal or financial information;
- rotate any credential that may ever have been committed.

## Important repository-history note

The original private repository history contains an old `infra/.env` path. The current source uses `infra/.env.example`, but a public release should not reuse the old Git history unchanged. Use a history-cleaned repository or keep the original repository private and grant controlled access to reviewers.
