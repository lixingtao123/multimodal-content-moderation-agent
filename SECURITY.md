# Security

## Credentials

Never commit API keys, database credentials, access tokens, or private test
content. Copy the provided environment template and keep real values only in
an ignored `.env` file:

```bash
cp src/backend/.env.example src/backend/.env
```

Before committing, check that `.env`, runtime databases, logs, uploaded files,
model weights, and evaluation outputs are not staged.

## Responsible use

This repository is an educational content-moderation prototype. Its decisions
should not be treated as legal, compliance, or safety guarantees. Production
deployments should retain human review for ambiguous or high-impact cases,
monitor model drift, and protect uploaded content according to applicable data
protection requirements.
