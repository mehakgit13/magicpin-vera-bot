Vera — magicpin AI Challenge Submission

A deterministic, stateful FastAPI implementation of the Vera merchant WhatsApp assistant endpoint contract.

Implemented API

The application exposes the required Vera bot endpoints:

Method	Endpoint	Purpose
GET	/v1/healthz	Service health and runtime status
GET	/v1/metadata	Submission and team metadata
POST	/v1/context	Store or update runtime context
POST	/v1/tick	Process triggers and generate actions
POST	/v1/reply	Continue an existing conversation
Design

The bot maintains four context layers in memory:

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
Router Priorities

The router is deterministic and prioritizes:

Trigger relevance
Category-specific vocabulary and signals
Merchant-specific facts and performance
Active merchant offers
Customer consent and preferences
A single practical next step

The implementation does not depend on external APIs for message composition.

Context Management

The /v1/context endpoint supports incremental delivery of:

Category context
Merchant context
Customer context
Trigger context
Version Handling

The implementation supports:

✅ Idempotent re-delivery of the same context version
✅ Rejection of stale lower versions
✅ Replacement by higher versions
✅ Atomic context replacement
✅ Runtime context injection without restart
Conversation Flow

Proactive interactions are initiated through:

POST /v1/tick

For an eligible trigger, the system:

Identifies the relevant merchant and category.
Evaluates the trigger.
Composes a merchant-facing message.
Applies suppression rules.
Creates a unique conversation ID.
Returns the resulting action.

Subsequent merchant messages are handled through:

POST /v1/reply

The reply handler returns one of:

send
wait
end

This makes the interaction stateful rather than isolated.

Operational Guarantees
Capability	Implementation
Context versioning	✅
Idempotent updates	✅
Stale-version protection	✅
Atomic updates	✅
Trigger suppression	✅
Unique conversation IDs	✅
Stateful replies	✅
Deterministic composition	✅
Runtime context injection	✅
Docker support	✅
Deterministic Composition

Message generation uses the context received at runtime rather than relying only on fixed canonical examples.

The composition layer can use:

Merchant identity
Merchant performance
Category information
Peer statistics
Offers
Trigger payloads
Customer preferences
Customer consent
Conversation state

This allows the same endpoint contract to process newly injected contexts during evaluation.

Local Development
1. Create virtual environment
python -m venv .venv
2. Activate environment
.\.venv\Scripts\Activate.ps1
3. Install dependencies
pip install -r requirements.txt
4. Start server
uvicorn app.main:app --host 0.0.0.0 --port 8080

The service will be available at:

http://localhost:8080
Health Check
Invoke-RestMethod http://localhost:8080/v1/healthz
Metadata
Invoke-RestMethod http://localhost:8080/v1/metadata
Docker

The application is containerized using Python 3.10.

Build
docker build -t vera-bot .
Run
docker run --rm -p 8080:8080 vera-bot

The container supports the platform-provided PORT environment variable for cloud deployment.

Deployment

The application is designed for deployment on a cloud platform that provides a public HTTPS endpoint.

The deployed service exposes:

GET  /v1/healthz
GET  /v1/metadata
POST /v1/context
POST /v1/tick
POST /v1/reply
Environment Variables
TEAM_NAME
TEAM_MEMBERS
CONTACT_EMAIL
SUBMITTED_AT
Evaluation

The repository includes:

Challenge dataset
Example payloads
judge_simulator.py
API tests
Docker configuration

The implementation supports dynamically injected:

CategoryContext
MerchantContext
CustomerContext
TriggerContext

rather than relying exclusively on bundled examples.

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
🔄 Stateful

Conversation state is maintained across /v1/tick and /v1/reply.

🎯 Deterministic

The same stored contexts, trigger, and conversation state produce deterministic behavior.

🧠 Context-Aware

Messages use merchant, category, trigger, and optional customer information.

🛡️ Suppression-Aware

Suppression keys prevent duplicate proactive messages.

🔢 Version-Aware

Newer context versions replace older versions while stale updates are rejected.

🐳 Containerized

The complete application can be packaged and deployed as a Docker container.

Privacy and Data Handling

The application keeps merchant, customer, category, and trigger contexts in runtime memory.

No external database or third-party API is required for the core message composition flow.

Merchant and customer context is not transmitted outside the application.

Project Status

The implementation provides the required Vera API contract together with:

Stateful context handling
Deterministic message composition
Trigger suppression
Version-aware context updates
Stateful conversation replies
Docker-based deployment support
Health and metadata endpoints

Ready for public deployment and challenge evaluation.