# Vera — magicpin AI Challenge Submission

A deterministic, stateful FastAPI implementation of the Vera merchant
WhatsApp assistant endpoint contract.

The system composes concise, context-aware merchant interactions using
category, merchant, trigger, and optional customer context while maintaining
state across proactive conversations and replies.

## Implemented API

The application exposes the required Vera bot endpoints:

- `GET /v1/healthz`
- `GET /v1/metadata`
- `POST /v1/context`
- `POST /v1/tick`
- `POST /v1/reply`

An additional development endpoint is also available:

- `POST /v1/teardown`

## Design

The bot maintains the four context layers in memory and composes messages
from the context received at runtime:

```text
CategoryContext
      +
MerchantContext
      +
TriggerContext
      +
Optional CustomerContext
      ↓
Deterministic Message Composition
      ↓
Action

The router is deterministic and prioritizes:

Trigger relevance
Category-specific vocabulary and signals
Merchant-specific facts and performance
Active merchant offers
Customer consent and preferences when applicable
A single practical next step

The implementation does not depend on external APIs for message composition
and does not transmit merchant or customer context outside the application.

Context Management

The /v1/context endpoint supports incremental delivery of:

Category context
Merchant context
Customer context
Trigger context

Context versions are handled using the supplied context identifier and
version number.

The implementation supports:

Idempotent re-delivery of the same context version
Rejection of stale lower versions
Replacement by higher versions
Atomic context replacement under a lock
Runtime context injection without requiring a restart
Conversation Flow

Proactive interactions are initiated through /v1/tick.

For an eligible trigger, the system:

Identifies the relevant merchant and category context.
Evaluates the trigger.
Composes a deterministic merchant-facing message.
Applies suppression rules.
Creates a unique conversation ID.
Returns the resulting action.

Subsequent merchant messages are handled through /v1/reply.

The reply handler maintains conversation state and returns one of:

send
wait
end

This allows a proactive message to continue as a stateful conversation rather
than being treated as an isolated request.

Operational Guarantees

The implementation provides the following runtime guarantees:

The same (scope, context_id, version) is treated as a no-op.
Lower context versions return HTTP 409 with stale_version information.
Higher context versions replace the stored context atomically.
/v1/tick limits the number of returned actions to 20.
Suppression keys prevent duplicate proactive sends.
New tick actions receive unique conversation IDs.
/v1/reply maintains conversation state.
/v1/reply returns only send, wait, or end actions.
/v1/teardown clears runtime state.
Merchant and customer context is not persisted to an external database.
Deterministic Composition

Message generation is based on received context rather than fixed responses
to only the canonical challenge examples.

The composition layer uses available:

Merchant identity
Merchant performance
Category information
Peer statistics
Offers
Trigger payloads
Customer preferences and consent where applicable
Conversation state

This allows the same endpoint contract to process newly injected contexts
during evaluation.

Local Development

Create and activate a virtual environment:

python -m venv .venv
.\.venv\Scripts\Activate.ps1

Install dependencies:

pip install -r requirements.txt

Start the application:

uvicorn app.main:app --host 0.0.0.0 --port 8080

The local service is then available at:

http://localhost:8080
Health Check
Invoke-RestMethod http://localhost:8080/v1/healthz
Metadata
Invoke-RestMethod http://localhost:8080/v1/metadata
Docker

The application is containerized using Python 3.10 and can be built with:

docker build -t vera-bot .

Run the container locally:

docker run --rm -p 8080:8080 vera-bot

The container runs the FastAPI application using Uvicorn and supports the
platform-provided PORT environment variable for cloud deployment.

Deployment

The application is designed for deployment on a cloud platform that supports
Docker and provides a public HTTPS endpoint.

The Docker image exposes the FastAPI service on port 8080, while the
application also supports the platform-provided PORT environment variable.

The deployed service exposes:

GET  /v1/healthz
GET  /v1/metadata
POST /v1/context
POST /v1/tick
POST /v1/reply

The service metadata can be configured through environment variables such as:

TEAM_NAME
TEAM_MEMBERS
CONTACT_EMAIL
SUBMITTED_AT
Evaluation

The repository includes the provided challenge dataset, example payloads,
and judge_simulator.py for development and evaluation.

The implementation is designed to work with dynamically injected category,
merchant, customer, and trigger contexts rather than relying exclusively on
the bundled canonical examples.

The runtime API contract supports incremental context delivery and
stateful interactions throughout the evaluation flow.

Repository Structure
magicpin-vera-bot/
│
├── app/
│   └── main.py
│
├── dataset/
│   ├── categories/
│   ├── merchants_seed.json
│   ├── customers_seed.json
│   ├── triggers_seed.json
│   └── generate_dataset.py
│
├── examples/
│
├── tests/
│   └── test_api.py
│
├── scripts/
│   ├── check.sh
│   ├── run_simulator.ps1
│   └── smoke_test.py
│
├── challenge-brief.md
├── challenge-testing-brief.md
├── judge_simulator.py
├── requirements.txt
├── Dockerfile
├── render.yaml
├── .env.example
└── README.md
Key Characteristics
Stateful

Conversation state is maintained across /v1/tick and /v1/reply
interactions.

Deterministic

Given the same stored contexts, trigger, and conversation state, the
composition logic produces deterministic behavior.

Context-Aware

Messages are composed from merchant, category, trigger, and optional
customer information received through the API.

Suppression-Aware

Suppression keys prevent repeated proactive messages for the same trigger
condition.

Version-Aware

Context updates are processed according to their version, preventing stale
context from overwriting newer information.

Containerized

The complete application can be packaged and deployed as a Docker
container.

Privacy and Data Handling

The application keeps merchant, customer, category, and trigger contexts in
runtime memory.

No external database or third-party API is required for the core message
composition flow, and merchant/customer context is not transmitted outside
the application.

Project Status

The implementation provides the required Vera API contract together with
stateful context handling, deterministic message composition, trigger
suppression, version-aware updates, and Docker-based deployment support.