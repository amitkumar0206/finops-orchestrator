# aasmaa AI Cost Intelligence Platform

AI-assisted FinOps platform for AWS-first cost analysis, multi-cloud cost ingestion, optimization discovery, governed multi-tenant access, and infrastructure design workflows.

## Current Status

- As of 8 April 2026, the core product is implemented and actively maintained.
- The application can run locally and can also be deployed as an AWS-hosted stack for organization use.
- End-to-end shipped areas include AI cost analysis chat, optimization opportunities, CUR deep analysis, multi-tenant scoping, authentication, demo admin controls, IaC analysis, IaC blueprint generation, and F-001 multi-cloud ingestion with FOCUS-style normalization.
- Recent security fixes are documented and verified in the security docs and test suite.
- Some enterprise surfaces are still partial or scaffolded: report generation endpoints are currently mock-only, and the custom dashboard builder is not yet implemented. Treat those areas as work in progress unless you validate them directly in code.
- The shipped F-001 scope is the data-source registry, advisory upload ingestion, source run history, idempotent file tracking, and unified normalized spend preview. Connected-mode provider pulls remain a follow-up and currently return a clear not-enabled response.

## Key Features

### AI FinOps Chat
- **Multi-agent orchestration**: Supervisor routes queries to a cost-analysis agent, an optimization agent, or a comparison flow based on intent signals and embedded query classification.
- **LLM text-to-SQL**: The LLM (AWS Bedrock) generates Athena SQL directly from natural language — no rigid parameter schema. A library of 15+ optimized CUR SQL templates backs the execution.
- **Embedding-based intent router**: A SentenceTransformer model validates and adjusts intent classification using semantic similarity against canonical exemplars per intent category.
- **Context-aware multi-turn chat**: Time-range inheritance from prior turns, follow-up shorthand (`"break down by region"` inherits the prior query's intent and time window), and conversation persistence backed by PostgreSQL.
- **Streaming responses**: Server-Sent Events (SSE) for progressive response delivery.
- **Visual responses**: Chart.js visualizations (bar, stacked bar, line, pie) rendered inline with the assistant response. Charts export as PNG, PDF, or CSV. AWS service labels are abbreviated automatically.
- **Follow-up suggestions**: The assistant returns suggested next queries after each response.
- **Token quota enforcement** (demo mode): Per-user and per-department monthly token budgets, with usage tracking.

### Optimization Opportunities
- **AWS signal ingestion**: Cost Explorer (rightsizing, RI/SP purchase recommendations, anomalies), Trusted Advisor checks, and Compute Optimizer recommendations for EC2 and Lambda.
- **CloudWatch-based waste detection**: Idle EC2 instances (CPU P95 < 5%), idle RDS instances (zero connections), idle load balancers (zero requests), idle Lambda functions (zero invocations), and underutilized EC2 candidates — works at all AWS Support tiers.
- **RI/SP coverage analysis**: Cost Explorer coverage, utilization, expiry (< 90 days), and purchase recommendations for both Reserved Instances and Savings Plans.
- **Storage lifecycle signals**: Unattached EBS volumes, orphaned snapshots, deregistered AMIs with retained snapshots, S3 buckets missing lifecycle policies, and gp2→gp3 migration candidates.
- **CUR pattern mining, connected mode**: Athena + Cost Explorer detectors for unused RI/SP coverage, idle and scheduling candidates, cross-region data transfer, steady-state spend, month-over-month cost spikes, and CE anomalies.
- **CUR pattern mining, advisory mode**: Upload a CUR CSV or CSV.GZ export and run the same detector family with pandas — no live AWS credentials required.
- **Opportunities workspace**: Filterable and paginated recommendations list with savings estimates, evidence detail, status updates (open / in progress / resolved / dismissed), bulk status actions, and CSV export.
- **Configurable thresholds**: All detection thresholds are tunable through `CUR_MINING_*` and `CUR_UPLOAD_*` environment variables.

### Multi-Cloud Data Sources
- **Data source registry**: Organization-scoped registry for AWS CUR, Azure Cost Management exports, GCP billing exports, and generic cost CSV feeds.
- **FOCUS-style normalization**: Uploaded billing files are normalized into a unified provider/service/month dataset that can be queried consistently across clouds.
- **Advisory upload workflow**: FinOps teams can ingest billing exports without live cloud credentials and immediately inspect normalized run status, validation feedback, and freshness.
- **Idempotent ingestion tracking**: Source file checksum registry prevents duplicate uploads from being processed twice.
- **Run history and freshness**: Each source records validation status, rows read, rows normalized, and the latest freshness timestamp exposed in the UI.
- **Scoped API surface**: `/api/v1/data-sources` endpoints preserve organization scoping and reuse existing auth and feature-access controls.
- **Deployment note**: Connected-mode ingestion is intentionally not enabled yet in this deployment; advisory upload is the supported production path.

### Multi-Tenant Access & Governance
- **Organization-scoped access**: Every request carries an organization context (org ID + allowed AWS account IDs). All Athena queries, Cost Explorer calls, and opportunity lookups are filtered to the caller's tenant scope.
- **Organization management**: Create organizations, switch between them, invite and remove members, and update member roles (owner / admin / member).
- **Saved views**: Name and save a scoped set of AWS account IDs with optional time range and filter defaults. Set a view as the active scope for all subsequent requests.
- **Effective scope API**: A `/scope/current` endpoint returns the caller's resolved organization, allowed accounts, active view, and effective time range and filters.
- **Platform admin**: Users with `is_admin=true` can manage rate limits across any organization.

### Demo Admin Console
- **Organization token budget**: Set and track a monthly token budget at the organization level.
- **Department CRUD**: Create, update, and delete departments. Each department has its own monthly token limit. Deletion is blocked if users are still assigned.
- **User management**: Create and update users with per-user token overrides, department assignment, feature access flags, org role, and one-time token top-ups.
- **Feature access gates**: Per-user flags for chat, analyze (IaC + opportunities), generate (blueprints), cur_analysis, and admin_console. Enforced at the middleware layer.
- **Token quota summary**: Full hierarchy view — organization total → departments → users — with live usage statistics.

### Infrastructure Design Workflows
- **IaC workbench**: Upload one or more Terraform (`.tf`, `.hcl`, `.tfvars`) or CloudFormation (`.yaml`, `.yml`, `.json`) files. The LLM returns: summary, explanation, pros and cons, estimated cost impacts, improvement suggestions, and an improved template.
- **Multi-file cross-file analysis**: When multiple files are uploaded together, the analysis covers cross-file dependencies and interactions.
- **IaC follow-up chat**: Continue a conversation against a previously analyzed template session.
- **Optimized template generation**: Produce a revised version of an analyzed template incorporating user-supplied goals.
- **Blueprint generation**: Generate a Terraform or CloudFormation starter template (plus an alternate format) from text requirements, a selected list of AWS services, or an uploaded architecture diagram description.

### Security & Operations
- **JWT authentication**: Access and refresh tokens; token blacklisting via Valkey; constant-time comparison; PBKDF2-HMAC-SHA256 (600,000 iterations, OWASP 2023 compliant); automatic transparent migration from legacy 100k-iteration hashes on login.
- **Login brute-force protection**: Valkey-backed per-IP and per-email throttle with progressive lockout (15 min → 30 min → 1 hr → ... → 24 hr cap), trusted-proxy XFF parsing.
- **Rate limiting**: Sliding-window rate limiter scoped per user and per organization. Configurable defaults per subscription tier (Enterprise / Standard / Free) with admin-managed overrides.
- **Security headers**: Content Security Policy, HSTS, X-Frame-Options (DENY), X-Content-Type-Options (nosniff).
- **SQL injection prevention**: Parameterized queries throughout; a centralized validation layer for date, account ID, service code, instance type, tag key/value, and resource ID inputs.
- **SSRF protection**: Webhook URLs in scheduled reports are validated against blocked private CIDR ranges (RFC 1918, loopback, link-local) and enforced HTTPS-only.
- **SSTI prevention**: Report template content is validated against a blocked-pattern list before storage.
- **PII masking**: Email addresses are masked in all authentication and audit logs; identifiers are hashed for correlation.
- **Audit logging**: User actions written to a PostgreSQL `audit_logs` table (requires database mode).
- **Health endpoints**: `/health` (public), `/health/liveness`, `/health/readiness`, and `/health/detailed` (authenticated, returns full service status).
- **Prometheus metrics**: Request count and duration exported at `/metrics`.

## 🏗️ Architecture Overview

### Chat Query Pipeline

```
User Message
    ↓
Multi-Agent Workflow (multi_agent_workflow.py)
    ↓
Intent Routing:
  - Embedding intent router (SentenceTransformer) classifies the query
  - Signals compared: optimization markers, comparison markers, cost/drill-down terms
  - Follow-up context from prior turn is merged (time range, intent inheritance)
    ↓
    ┌──────────────────────┬──────────────────────┐
    ↓                      ↓                      ↓
Cost Analysis          Optimization            Comparison
  (Athena SQL)           Agent               (Athena SQL,
                                            two periods)
    ↓                      ↓                      ↓
Athena Executor    Opportunity signals       Athena Executor
    ↓                      ↓                      ↓
Response Formatter ← Chart Data Builder ← LLM Insight Generation
    ↓
JSON response: markdown summary + chart specs + follow-up suggestions
```

**Key components:**
- **Multi-agent workflow** (`agents/multi_agent_workflow.py`): Entry point; routing logic using keyword signals and the embedding router.
- **Embedding intent router** (`services/embedding/embedding_intent_router.py`): SentenceTransformer semantic similarity against per-intent canonical examples. Adjusts confidence or overrides classification.
- **Athena CUR templates** (`services/athena_cur_templates.py`): 15+ optimized SQL templates for cost breakdown, top-N, trend, comparison, drill-down, and CUR pattern mining.
- **Athena executor** (`services/athena_executor.py`): Async Athena client with polling, result parsing, and partition-pruned query execution.
- **LLM service** (`services/llm_service.py`): AWS Bedrock integration (Amazon Nova Pro by default) for insight generation and IaC analysis.
- **Response formatter** (`services/response_formatter.py`): Structured aasmaa response template: summary → scope → results → insights → charts → next steps.
- **Chart data builder** (`services/chart_data_builder.py`): Converts query results + chart specifications into Chart.js-ready data structures.
- **Time range module** (`aasmaa/time_range.py`): Parses natural language time expressions and merges with conversation context. Supports rolling periods, calendar periods, comparisons, and explicit date ranges.
- **Optimization agent** (`agents/optimization_agent.py`): Handles optimization-intent queries by aggregating signals from Cost Explorer, CloudWatch, RI/SP analysis, storage, and CUR mining services.

### Optimization Signal Sources

| Service | Signals |
|---------|---------|
| `aws_optimization_signals.py` | CE rightsizing, RI/SP purchase recommendations, Trusted Advisor checks, Compute Optimizer |
| `cloudwatch_optimization_signals.py` | Idle EC2/RDS/ELB/Lambda by CloudWatch metrics |
| `ri_savings_plans_signals.py` | RI/SP coverage, utilization, expiry, purchase recommendations |
| `storage_optimization_signals.py` | Unattached EBS, old snapshots, S3 lifecycle gaps, gp2→gp3 |
| `cur_pattern_mining_signals.py` | Connected-mode Athena + CE anomaly/trend detectors |
| `cur_csv_analyzer.py` | Advisory-mode pandas detectors on uploaded CUR CSV/GZ |

### Deployment Modes

| Mode | When to use |
|------|-------------|
| **Local (Docker Compose)** | Development; Postgres + Valkey run in containers, backend and frontend on host |
| **AWS demo stack** | Low-cost demo; single ECS task, no RDS, no Valkey, no NAT Gateway |
| **AWS production stack** | Full ECS Fargate, ALB, RDS PostgreSQL, ElastiCache Valkey, S3, CloudWatch |


## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+ (frontend only)
- Docker & Docker Compose
- AWS CLI configured with appropriate IAM permissions
- AWS Athena and S3 with CUR data configured (optional — works with Cost Explorer API without Athena)
- AWS Bedrock access for LLM (Amazon Nova Pro recommended)

### Local Development Setup

```bash
# Clone repository
git clone <repository-url>
cd aasmaa

# Use the local-run script to start everything (postgres + valkey via Docker, backend + frontend on host)
./local-run.sh start

# Or manually:
# Start postgres + valkey
docker-compose up -d postgres valkey

# Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload  # runs on :8000

# Frontend
cd ../frontend
npm install
npm run dev  # runs on :3000
```

`local-run.sh` supports `start`, `stop`, `restart`, `status`, and `logs`. It auto-loads `deployment.env` and `backend/.env` if they exist, and installs dependencies on first run by default.

If you are using the new Data Sources capability with database-backed mode, run the latest Alembic migration before testing the feature:

```bash
cd backend
alembic upgrade head
```

### Testing

```bash
# All backend tests (run from project root)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest

# Unit tests only
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/unit/

# Specific area
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/unit/api/          # API routers incl. data-sources
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/unit/middleware/   # Auth, rate-limiting, security headers
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/unit/services/     # Service-layer logic incl. FOCUS normalization
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/test_token_quota_and_departments.py -v

# Frontend type-check and lint
cd frontend && npm run type-check && npm run lint
```

Targeted F-001 validation:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/unit/services/test_focus_normalizer.py tests/unit/api/test_data_sources_api.py
cd frontend && npm run type-check
```

### API Explorer

Once running:
- **Backend Swagger UI**: http://localhost:8000/docs
- **Frontend UI**: http://localhost:3000

## Deployment

### AWS Deployment

Two CloudFormation pathways are provided under `infrastructure/cloudformation/`:

| Template | Purpose |
|----------|---------|
| `main-stack.yaml` | Full production stack: ECS Fargate, ALB, RDS PostgreSQL, ElastiCache Valkey, S3, CloudWatch |
| `main-stack-demo.yaml` | Low-cost demo: ECS, ALB, S3 — no RDS, no Valkey, no NAT Gateway |
| `main-stack-demo-ec2.yaml` | EC2-based demo variant |
| `ecs-services.yaml` | ECS task and service definitions (imported by main stacks) |
| `glue-crawler.yaml` | Glue crawler for CUR table setup |

Deploy scripts are in `scripts/deployment/`:
- `deploy-demo-barebones.sh` — Deploy the low-cost demo stack
- `deploy-demo-only.sh` — Alternative demo deployment
- `redeploy-backend.sh` — Rebuild and push backend image only
- `update-prod-full.sh` — Update the full production stack

```bash
# Example: deploy the demo stack
cd scripts/deployment
./deploy-demo-barebones.sh

# Example: redeploy only the backend service (faster; no infra changes)
./redeploy-backend.sh
```

```bash
# After deployment, verify CUR setup (needed for 13+ months of history)
./scripts/setup/verify-cur-setup.sh

# Set up the Athena CUR view
./scripts/setup/setup-cur.sh
```

**📖 See [docs/AWS_DEPLOYMENT_GUIDE.md](./docs/AWS_DEPLOYMENT_GUIDE.md) for complete setup instructions.**

### AWS Infrastructure Components (Production Stack)
- **ECS Fargate**: Container orchestration for backend services
- **ALB**: Load balancing and HTTPS termination
- **RDS PostgreSQL**: Primary database (conversation history, orgs, opportunities, audit logs)
- **ElastiCache Valkey**: Cache for login throttle, token blacklisting, and rate-limit storage
- **S3**: CUR data storage and Athena query results
- **CloudWatch**: Logs and metrics
- **AWS Athena + Glue**: CUR query execution

## Configuration

### Key Environment Variables

```bash
# AWS
AWS_REGION=us-east-1
# Credentials come from the IAM role chain (recommended) or ~/.aws/credentials for local dev

# AWS Bedrock (LLM)
BEDROCK_MODEL_ID=us.amazon.nova-pro-v1:0
BEDROCK_REGION=us-east-1

# Athena / CUR
ATHENA_WORKGROUP=primary
ATHENA_OUTPUT_LOCATION=s3://your-bucket/athena-results/
ATHENA_DATABASE=cur_database
ATHENA_TABLE=cur_table
ATHENA_CATALOG=AwsDataCatalog

# Database (optional — enables conversation history, orgs, opportunities, audit logs)
DATABASE_ENABLED=true
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=aasmaa
POSTGRES_USER=aasmaa
POSTGRES_PASSWORD=...

# Valkey / Redis (optional — enables login throttle, token blacklist, distributed rate limiting)
VALKEY_HOST=localhost
VALKEY_PORT=6379
VALKEY_PASSWORD=...

# Auth
SECRET_KEY=<long-random-string>   # required; no default
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# Demo mode (single-tenant, no DB or Valkey required)
DEMO_MODE=false
CONFIG_DEMO_AUTH_ENABLED=false
DEMO_IDENTITY_STORE_PATH=backend/data/demo_identity_store.json

# CUR pattern mining (all optional — shown with defaults)
CUR_PATTERN_MINING_ENABLED=true
CUR_UPLOAD_MAX_SIZE_MB=200
CUR_UPLOAD_MAX_ROWS=2000000
CUR_MINING_LOOKBACK_DAYS=30
CUR_MINING_MIN_IDLE_COST_USD=5.0
CUR_MINING_MIN_DATA_TRANSFER_USD=10.0
CUR_MINING_MIN_RI_UNUSED_USD=1.0
CUR_MINING_MIN_SP_UNUSED_USD=1.0
CUR_MINING_MIN_STEADY_STATE_COST_USD=50.0
CUR_MINING_MOM_INCREASE_THRESHOLD_PCT=40.0
CUR_MINING_MAX_FINDINGS_PER_DETECTOR=25

# F-001 multi-cloud data sources
F001_DATA_SOURCES_ENABLED=true
F001_UPLOAD_MAX_SIZE_MB=250
F001_UPLOAD_MAX_ROWS=2000000

# Logging & observability
LOG_LEVEL=INFO
ENVIRONMENT=development
```

### Athena / CUR Setup

1. Enable Cost and Usage Reports in the AWS Billing Console.
2. Configure delivery to an S3 bucket (e.g. `your-account-cur-data`).
3. Run the Glue crawler or use `scripts/setup/setup-cur.sh` to create the Athena database and table.
4. Grant the ECS task role (or local IAM user) read access to Athena, S3, and Glue.

See [docs/SETUP_CUR.md](./docs/SETUP_CUR.md) for step-by-step instructions.

## Project Structure

```
finops-orchestrator/
├── backend/                          # FastAPI backend
│   ├── agents/                       # Multi-agent orchestration
│   │   ├── multi_agent_workflow.py   # Entry point: intent routing + query execution
│   │   ├── execute_query_v2.py       # Athena query execution and routing helpers
│   │   ├── intent_classifier.py      # Intent type definitions + embedding router wrapper
│   │   └── optimization_agent.py     # Aggregates optimization signals
│   ├── api/                          # FastAPI routers
│   │   ├── chat.py                   # Chat endpoint + SSE streaming
│   │   ├── health.py                 # /health, /health/liveness, /health/readiness, /health/detailed
│   │   ├── analytics.py              # Cost Explorer analytics (tenant-scoped)
│   │   ├── athena_queries.py         # Athena SQL generation, execution, and export
│   │   ├── auth.py                   # Login, token refresh, logout, current-user
│   │   ├── organizations.py          # Org creation, switching, member management
│   │   ├── saved_views.py            # Saved account-scope views
│   │   ├── scope.py                  # Effective scope for current user
│   │   ├── opportunities.py          # Optimization opportunities CRUD, bulk actions, export
│   │   ├── cur_analysis.py           # CUR deep analysis (upload / mine / capabilities)
│   │   ├── data_sources.py           # Multi-cloud data source registry and upload ingestion
│   │   ├── iac_workbench.py          # IaC upload, analysis, chat, and template generation
│   │   ├── iac_generate_workflow.py  # Greenfield blueprint generation
│   │   ├── demo_admin.py             # Demo admin console (users, departments, token quotas)
│   │   ├── phase3_enterprise.py      # Scheduled reports, multi-account, RBAC (partial)
│   │   ├── reports.py                # Report endpoints (currently mock-only)
│   │   └── admin/rate_limits.py      # Platform admin rate-limit management
│   ├── middleware/                   # Request-level middleware
│   │   ├── authentication.py         # JWT verification; attaches AuthenticatedUser to request
│   │   ├── account_scoping.py        # Resolves org + allowed accounts into RequestContext
│   │   ├── feature_access.py         # Per-feature gates and token quota enforcement (demo mode)
│   │   ├── login_throttle.py         # Per-IP + per-email progressive login rate limiting
│   │   ├── rate_limiting.py          # Sliding-window endpoint rate limits
│   │   └── security_headers.py       # CSP, HSTS, X-Frame-Options, X-Content-Type-Options
│   ├── models/                       # Data models
│   │   ├── database_models.py        # SQLAlchemy ORM models
│   │   ├── opportunities.py          # Opportunity Pydantic models
│   │   ├── data_sources.py           # Data source, run, and normalized-cost schemas
│   │   └── schemas.py                # Request/response schemas
│   ├── services/                     # Core business logic (50+ modules)
│   │   ├── athena_cur_templates.py   # 15+ optimized SQL templates + CURPatternMiningTemplates
│   │   ├── athena_executor.py        # Async Athena client
│   │   ├── athena_query_service.py   # Query generation + validation
│   │   ├── aws_optimization_signals.py # CE, Trusted Advisor, Compute Optimizer signals
│   │   ├── cloudwatch_optimization_signals.py # Idle resource detection via CloudWatch
│   │   ├── ri_savings_plans_signals.py  # RI/SP coverage, utilization, expiry
│   │   ├── storage_optimization_signals.py  # EBS, snapshot, S3 lifecycle signals
│   │   ├── cur_pattern_mining_signals.py # Connected-mode Athena + CE detectors
│   │   ├── cur_csv_analyzer.py       # Advisory-mode pandas CUR CSV detectors
│   │   ├── data_source_registry.py   # Data source orchestration, run tracking, unified spend
│   │   ├── focus_normalizer.py       # FOCUS-style normalization for AWS/Azure/GCP/generic feeds
│   │   ├── opportunities_service.py  # Opportunity CRUD and tenant scoping
│   │   ├── optimization_engine.py    # DB-backed recommendation templates
│   │   ├── iac_analysis_service.py   # IaC file analysis sessions
│   │   ├── iac_blueprint_generator.py # Greenfield template generation
│   │   ├── conversation_manager.py   # PostgreSQL-backed conversation threads
│   │   ├── llm_service.py            # AWS Bedrock integration (Nova Pro default)
│   │   ├── response_formatter.py     # Structured response template
│   │   ├── chart_data_builder.py     # Chart.js-compatible chart data builder
│   │   ├── chart_recommendation.py   # Chart type selection
│   │   ├── cache_service.py          # Valkey cache + fail-closed token blacklist
│   │   ├── organization_service.py   # Org CRUD and member management
│   │   ├── saved_views_service.py    # Saved view persistence
│   │   ├── request_context.py        # Per-request tenant context dataclass
│   │   ├── rbac_service.py           # Role-based access control
│   │   ├── audit_log_service.py      # Audit log writes
│   │   ├── demo_identity_store.py    # File-backed identity store (users, depts, quotas)
│   │   ├── scheduled_report_service.py # Report scheduling service (scaffolded)
│   │   ├── multi_account_service.py  # Cross-account registration and aggregation
│   │   ├── email_service.py          # Email delivery
│   │   ├── s3_service.py             # S3 operations
│   │   ├── vector_store.py           # ChromaDB vector store (optional)
│   │   ├── provider_connectors/      # AWS/Azure/GCP/generic billing file adapters
│   │   ├── embedding/
│   │   │   └── embedding_intent_router.py  # SentenceTransformer intent classifier
│   │   └── ...                       # Additional utility services
│   ├── aasmaa/
│   │   └── time_range.py             # Time range parsing and merge (natural language → dates)
│   ├── config/
│   │   └── settings.py               # Pydantic settings (all env vars)
│   ├── utils/                        # Shared utilities
│   │   ├── aws_session.py            # IAM role-based session factory
│   │   ├── aws_constants.py          # AWS service/region constants
│   │   ├── sql_validation.py         # SQL injection prevention
│   │   ├── sql_constants.py          # Centralized SQL string literals
│   │   ├── pii_masking.py            # Email and identifier masking for logs
│   │   ├── auth.py                   # JWT + password hashing helpers
│   │   ├── encryption.py             # Field-level encryption for sensitive DB columns
│   │   ├── client_ip.py              # Trusted-proxy XFF parsing
│   │   ├── errors.py                 # Error codes and helpers
│   │   └── logging.py                # Structlog configuration
│   ├── evaluation/                   # Intent classification evaluation harness
│   │   ├── ups_evaluator.py          # Confusion matrix, precision/recall
│   │   ├── calibrate_thresholds.py   # Per-intent confidence calibration
│   │   └── drift_monitor.py          # Accuracy drift detection
│   ├── alembic/                      # Database schema migrations (18 versions)
│   ├── scripts/                      # DB seed scripts
│   │   └── seed_all_32_recommendations.sql
│   └── main.py                       # FastAPI app entry point with lifespan, middleware, routers
├── frontend/                         # React 18 + TypeScript + Vite frontend
│   └── src/
│       ├── App.tsx                   # App shell, routing, sidebar nav (Material UI)
│       ├── components/
│       │   ├── Chat/                 # Chat interface + markdown renderer
│       │   ├── DataSources/          # Data source wizard, freshness, run history
│       │   ├── Opportunities/        # Opportunities workspace
│       │   ├── SavedViews/           # Saved view management
│       │   └── Scope/                # Active scope indicator
│       ├── pages/
│       │   ├── IacWorkbenchPage.tsx  # IaC upload and analysis
│       │   ├── CurAnalysisPage.tsx   # CUR deep analysis (upload + mine)
│       │   ├── DataSourcesPage.tsx   # Multi-cloud ingestion and source management
│       │   ├── GenerateBlueprintPage.tsx # IaC blueprint generation
│       │   ├── AdminConsolePage.tsx  # Demo admin console
│       │   ├── LoginPage.tsx
│       │   ├── ProfilePage.tsx
│       │   └── SettingsPage.tsx
│       ├── context/AuthContext.tsx   # Auth state + feature access checks
│       └── lib/api.ts                # Axios-based API client
├── infrastructure/                   # AWS IaC
│   ├── cloudformation/               # CloudFormation templates (5)
│   ├── config/                       # ECS task definitions, bucket policies
│   └── sql/                          # CUR table DDL
├── scripts/                          # Operational scripts
│   ├── deployment/                   # AWS deployment and update scripts
│   ├── setup/                        # CUR and Athena setup and verification
│   └── utilities/                    # Athena result cleanup utilities
├── tests/                            # Test suite (86 test files)
│   ├── unit/                         # Unit tests organized by layer
│   │   ├── api/
│   │   ├── config/
│   │   ├── aasmaa/
│   │   ├── middleware/
│   │   ├── opportunities/
│   │   ├── services/
│   │   └── utils/
│   └── (integration and e2e test files)
├── docs/                             # Project documentation
├── local-run.sh                      # Convenience script: start/stop/status local dev env
├── docker-compose.yml                # PostgreSQL (with pgvector) + Valkey for local dev
├── pytest.ini                        # pytest configuration
├── SECURITY_AUDIT_REPORT.md          # Security audit findings and remediation status
├── DEVELOPER_GUIDE.md                # Developer onboarding guide
└── README.md                         # This file
```

## Security & Access Control

### Authentication
- JWT access and refresh tokens; configurable expiration
- PBKDF2-HMAC-SHA256, 600,000 iterations (OWASP 2023+ compliant)
- Automatic transparent hash migration from legacy 100k iterations on login
- Constant-time password comparison via `secrets.compare_digest()`
- Token blacklisting (Valkey-backed; fail-closed — a cache outage keeps revoked tokens revoked)
- Login brute-force protection: per-IP (20 attempts / 15 min) + per-email (5 attempts / 15 min) with progressive lockout; trusted-proxy XFF parsing

### Authorization
- Organization roles: `owner`, `admin`, `member`; platform admin flag (`is_admin`)
- Per-request tenant context injected by `AccountScopingMiddleware` — all data access is scoped to the caller's `organization_id` and `allowed_account_ids`
- Feature access flags in demo mode enforced at middleware layer before any handler runs

### Rate Limiting

Sliding-window rate limiter with user → organization priority hierarchy:

| Priority | Source |
|---------|--------|
| 1 (highest) | User-specific override |
| 2 | Organization role override |
| 3 | Subscription tier default |
| 4 (lowest) | Conservative fallback (10 req/hr) |

Default tier limits (Athena export):

| Tier | Org limit | owner/admin | member |
|------|-----------|-------------|--------|
| Enterprise | 200 req/hr | 100 | 50 |
| Standard | 50 req/hr | 30 | 15 |
| Free | 10 req/hr | 5 | 3 |

Platform admins can manage rate-limit overrides via `/api/admin/rate-limits/organizations/...`; organization admins can manage their own org via `/api/organizations/{org_id}/rate-limits/...`.

### Demo Admin Console API

Available when `CONFIG_DEMO_AUTH_ENABLED=true`. Requires `is_admin=true`.

```http
# Organization token budget
GET  /api/demo/admin/org-settings
PATCH /api/demo/admin/org-settings    { "monthly_token_budget": 3000000 }

# Token quota summary
GET  /api/demo/admin/token-summary

# Department CRUD
GET    /api/demo/admin/departments
POST   /api/demo/admin/departments    { "name": "Engineering", "monthly_token_limit": 500000 }
PATCH  /api/demo/admin/departments/{dept_id}
DELETE /api/demo/admin/departments/{dept_id}

# User management
GET    /api/demo/admin/summary
POST   /api/demo/admin/users
PATCH  /api/demo/admin/users/{user_id}
```

See [SECURITY_AUDIT_REPORT.md](./SECURITY_AUDIT_REPORT.md) for complete audit findings and remediation status.

## Documentation

- **[AWS Deployment Guide](./docs/AWS_DEPLOYMENT_GUIDE.md)** — Complete AWS deployment instructions
- **[Demo Deployment Guide](./docs/DEMO_DEPLOYMENT.md)** — Low-cost demo stack setup
- **[Quick Start Guide](./docs/QUICK_START.md)** — Developer onboarding with example queries
- **[CUR Setup Guide](./docs/SETUP_CUR.md)** — Configure AWS Cost and Usage Reports
- **[Multi-Tenant Implementation](./docs/MULTI_TENANT_IMPLEMENTATION.md)** — Org and scope design
- **[RBAC System](./docs/RBAC_SYSTEM.md)** — Role and permission design
- **[Troubleshooting](./docs/TROUBLESHOOTING.md)** — Common issues and solutions

## Contributing

Forks and contributions are welcome for noncommercial use. To contribute:

1. Fork the repository.
2. Make and test your changes.
3. Open a pull request for review, with a clear description of the change.

Please keep attribution to the original project intact in any fork or derivative work — see [License](#license) below.

## License

See [LICENSE](./LICENSE).

This codebase is licensed for noncommercial use: you may fork, modify, and
redistribute it (including as training data for AI/LLM models) as long as
you give credit to the original project. Building or offering a commercial
product or service based on this codebase is not permitted without a
separate commercial license from the copyright owner.
