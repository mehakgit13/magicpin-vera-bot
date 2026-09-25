# Vera — magicpin AI Challenge Submission

A deterministic, stateful FastAPI implementation of the required Vera bot endpoint contract.

## Implemented

- `GET /v1/healthz`
- `GET /v1/metadata`
- `POST /v1/context`
- `POST /v1/tick`
- `POST /v1/reply`
- Optional `POST /v1/teardown`

## Design

The bot keeps the four pushed context layers in memory and composes messages only from received data:

`CategoryContext + MerchantContext + TriggerContext + optional CustomerContext -> action`

The router is deterministic. It prioritizes trigger relevance, category vocabulary, merchant facts, active offers, customer consent/preferences, and a single low-friction next step. It does not call external APIs and does not transmit merchant/customer context outside the bot.

### Operational guarantees

- Same `(scope, context_id, version)` is a no-op.
- Lower versions return HTTP 409 with `stale_version`.
- Higher versions replace the stored context atomically under a lock.
- `/v1/tick` caps output at 20 actions.
- Suppression keys prevent duplicate proactive sends.
- New tick actions always receive unique conversation IDs.
- `/v1/reply` is stateful and returns only `send`, `wait`, or `end`.
- `/v1/teardown` clears runtime state.
- No persistent merchant/customer storage is used.

## Local run

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Then:

```powershell
Invoke-RestMethod http://localhost:8080/v1/healthz
Invoke-RestMethod http://localhost:8080/v1/metadata
```

## Docker

```bash
docker build -t vera-bot .
docker run --rm -p 8080:8080 vera-bot
```

## Public deployment

Deploy the Docker image to a cloud service that supplies a public HTTPS URL and routes the service port to `8080`. Set the environment variables in `.env.example`. Submit only the base URL, for example:

`https://YOUR-SERVICE-DOMAIN`

The challenge judge will call the five `/v1/...` endpoints from that base URL.

## Important submission checks

Before submitting, verify all five endpoints from the public internet and run the supplied magicpin `judge_simulator.py` against the public/local URL. The real judge injects fresh contexts and triggers, so this bot intentionally does not pattern-match only the canonical examples.

## Local judge simulator

The starter package's `judge_simulator.py`, `dataset/`, and `examples/` are included in this submission bundle for convenience.

Start the bot first, then configure the simulator's `BOT_URL` and LLM provider/API key as documented in `judge_simulator.py` and run:

```bash
python judge_simulator.py
```

The simulator is the development gate; the real judge injects fresh scenarios.
