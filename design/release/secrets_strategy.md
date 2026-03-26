# Secrets Strategy

## Mandatory rules

- Never commit real secrets to git.
- Use managed secret stores for all production credentials.
- Rotate secrets on schedule and immediately after suspected exposure.

## Secret sources

- GitHub Actions Secrets for CI/CD runtime secrets.
- Cloud secret manager (AWS Secrets Manager / GCP Secret Manager / Azure Key Vault) for app runtime.

## Required secret keys

- `JWT_SECRET_KEY`
- `LLM_API_KEY`
- `POSTGRES_PASSWORD`
- `POSTGRES_USER`

## Rotation policy

- JWT secret: every 90 days.
- DB credentials: every 90 days.
- LLM API key: every 60 days.

## Access policy

- Production secrets readable only by deployment role and runtime service account.
- No developer local machines should store production keys.
