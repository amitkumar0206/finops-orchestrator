# FinOps AI Cost Intelligence Platform

Enterprise-grade AWS cost intelligence platform powered by AI agents, featuring robust service name resolution, multi-turn conversations, and intelligent cost analysis.

## 🌟 Key Features

### Intelligence & Analysis
- 🎯 **Multi-Agent Orchestration**: LangGraph-powered supervisor pattern with specialized agents for cost analysis, optimization, and infrastructure insights
- 🧠 **Universal Parameter Schema (UPS)**: AI-driven intent + parameter extraction with LLM/heuristic hybrid, embedding validation, and JSON repair
- 💬 **Context-Aware Conversations**: Multi-turn dialogue with time range inheritance and conversation persistence
- 📊 **Intelligent Visualizations**: Intent-based chart recommendations with responsive layouts and AWS service label normalization
- 🔍 **Deep Cost Breakdowns**: Drill down from services → usage types → operations with automatic dimension inference

### Optimization Opportunities (NEW)
- 💰 **AWS Optimization Signals**: Integration with Cost Explorer, Trusted Advisor, and Compute Optimizer
- 📋 **Opportunities Dashboard**: Filterable, sortable table of optimization recommendations with status tracking
- 🔎 **Evidence Panel**: Deep-dive view with API trace, deep links, CUR validation SQL, and utilization metrics
- 🤖 **LLM-Powered Intent Detection**: Robust understanding of optimization queries with typo tolerance and semantic matching
- 📊 **Savings Analytics**: Track potential monthly/annual savings by category and service
- ✅ **Status Management**: Mark opportunities as open/accepted/dismissed with bulk actions and export

### Data & Integration
- 📈 **Complete CUR Access**: 15+ optimized Athena SQL templates with partition pruning and effective cost calculations
- ⚡ **Async Query Execution**: Non-blocking Athena queries with automatic result parsing and retry logic
- 🗄️ **PostgreSQL Conversation Store**: Full chat history persistence with agent execution tracking
- 📉 **Prometheus Metrics**: Service resolution counters, query performance, and system health monitoring

### User Experience
- 🎯 **Professional FinOps Responses**: Structured 6-section format (Summary/Scope/Results/Insights/Charts/Next Steps)
- 💡 **Smart Follow-up Suggestions**: Context-aware clickable suggestions after every response
- 🔄 **New Chat Reset**: Complete conversation context clearing for fresh sessions
- 📱 **Responsive UI**: Material-UI React frontend with real-time chart rendering and markdown support

## 🏗️ Architecture Overview

### Universal Parameter Schema (UPS) Pipeline

```
User Query: "Show EC2 cost by region for last month"
    ↓
UPS Extractor (ups_extractor.py):
  1. LLM extraction (Pydantic-validated JSON) → intent + entities + operations
  2. Heuristic fallback (regex + keyword scoring) if LLM fails
  3. JSON repair layer validates and auto-fixes malformed output
    ↓
Intent Classifier (intent_classifier.py):
  4. Map UPS output → legacy parameter format (compatibility)
  5. Follow-up time range inheritance (if context exists)
  6. Embedding intent router → semantic validation + confidence boost
  7. Clarification threshold check (intent_thresholds.json)
    ↓
SQL: WHERE line_item_product_code = 'AmazonEC2' AND ...
```

**Key Components**:
- **UPS Extractor**: Single extraction call produces intent + all parameters
- **Repair Layer**: Auto-fix malformed LLM JSON via re-prompting
- **Embedding Router**: SentenceTransformer similarity validates/overrides intent
- **Calibrated Thresholds**: Per-intent confidence minimums from evaluation runs
- **Evaluation Harness**: Confusion matrix, precision/recall, confidence stats
- **Drift Monitoring**: Track accuracy over time, detect degradation

**See [UPS Architecture](./docs/UPS_ARCHITECTURE.md) for full technical details.**

### Multi-Agent Workflow
```
User Query → Supervisor → Route Decision
                ↓
    ┌───────────┼───────────┐
    ↓           ↓           ↓
Cost       Optimization  Infrastructure
Analysis      Engine       Analyzer
    ↓           ↓           ↓
Response ← Formatter ← Chart Engine
```

## 🚀 Quick Start

### Prerequisites
- AWS Account with Cost and Usage Report (CUR) configured
- Docker installed locally
- AWS CLI configured with appropriate credentials
- Python 3.11+ (for local development)

### AWS Deployment

**Complete deployment guide:** [docs/AWS_DEPLOYMENT_GUIDE.md](./docs/AWS_DEPLOYMENT_GUIDE.md)

```bash
# Clone repository
git clone <repository-url>
cd finops-orchestrator

# Make deploy script executable
chmod +x deploy.sh

# Run automated deployment with pre-flight validation
./deploy.sh deploy

# The deployment script includes comprehensive pre-flight validation:
# [1/7] Validating required tools (AWS CLI, Docker, jq)
# [2/7] Validating AWS credentials and permissions
# [3/7] Validating AWS region configuration
# [4/7] Validating IAM permissions (CloudFormation, ECS, RDS, S3, etc.)
# [5/7] Validating Bedrock model access
# [6/7] Validating disk space for Docker builds
# [7/7] Validating deployment configuration

# After validation, the script will:
# ✓ Detect existing infrastructure (if any)
# ✓ Prompt for deployment mode (fresh install, update, or rebuild)
# ✓ Set up one-time components (S3, Glue, Athena)
# ✓ Deploy CloudFormation stack (10-15 min)
# ✓ Build and push Docker images to ECR (5-10 min)
# ✓ Deploy ECS services (5 min)
# ✓ Run database migrations with validation
# ✓ Validate deployment health
# ✓ Save configuration to deployment.env
# ✓ Provide application URL and next steps

# Total time: ~25-35 minutes (first-time installation)

# Note: Platform works immediately with Cost Explorer API (13 months).
# Data export setup is OPTIONAL and only needed for 13+ month history.
```

**Deployment Modes:**

- **Fresh Install**: Complete setup from scratch (all infrastructure including CUR)
- **Update Deployment**: Update existing infrastructure with new code/configuration
- **Partial Cleanup**: Destroy infrastructure but keep data exports and S3 buckets
- **Complete Cleanup**: Destroy EVERYTHING including all historical data (⚠️ DATA LOSS WARNING)

**For faster service-only updates:**

```bash
# Update only Docker images and ECS services (no infrastructure changes)
./deploy.sh update
```

**To remove infrastructure:**

```bash
# Partial removal (keeps CUR/Data Exports, S3 buckets, Glue, Athena)
./deploy.sh destroy

# Complete removal (deletes EVERYTHING including all data - requires typing "DELETE EVERYTHING")
./deploy.sh destroyAll
```

**📖 For detailed instructions, see [AWS Deployment Guide](./docs/AWS_DEPLOYMENT_GUIDE.md)**

### Prerequisites
- Python 3.11+
- Node.js 18+ (frontend only)
- Docker & Docker Compose
- AWS CLI configured with appropriate IAM permissions
- **AWS Athena and S3** with CUR data configured (optional - works with Cost Explorer API)
- AWS Bedrock access for LLM (Amazon Nova Pro recommended)

### Local Development Setup

```bash
# Clone repository
git clone <repository-url>
cd finops-orchestrator

# Backend setup
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configure environment (for local development only)
# Note: Production uses deployment.env created by deploy.sh
cp backend/.env.example backend/.env  # If example exists
# Edit backend/.env with local AWS credentials for testing

# Frontend setup  
cd ../frontend
npm install
npm run build  # Validates TypeScript + Vite production build

# Start development servers
docker-compose up -d  # Database and supporting services
cd backend && uvicorn main:app --reload  # Backend on :8000
cd frontend && npm start  # Frontend on :3000
```

### Testing the New Pipeline

```bash
# Test intent classification
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Show me EC2 costs by instance type for last month"}'

# Test follow-up context
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Now exclude t2.micro", "conversation_id": "your-conv-id"}'

# See QUICK_START.md for 15+ example queries
```

## Deployment

### Production Deployment to AWS

For complete AWS deployment instructions, see **[AWS Deployment Guide](./AWS_DEPLOYMENT_GUIDE.md)**

Quick deployment commands:

```bash
# Fresh installation or update existing deployment
./deploy.sh deploy

# Service-only update (faster)
./deploy.sh update

# Partial infrastructure removal (keeps CUR, S3, Glue, Athena)
./deploy.sh destroy

# Complete infrastructure removal (deletes EVERYTHING)
./deploy.sh destroyAll
```

The deployment script automatically:

- Detects existing infrastructure
- Sets up one-time components (CUR, Glue, Athena) for fresh installs
- Deploys/updates CloudFormation stacks
- Builds and pushes Docker images
- Deploys/updates ECS services
- Provides application URL

### Verify Deployment

```bash
# After deployment, verify CUR setup (optional - for 13+ months historical data)
./scripts/setup/verify-cur-setup.sh

# Set up CUR for extended historical data beyond 13 months (optional)
./scripts/setup/setup-cur.sh
```

**📖 Read More:**
- [AWS Deployment Guide](./docs/AWS_DEPLOYMENT_GUIDE.md) - Complete AWS setup instructions
- [Quick Start Guide](./docs/QUICK_START.md) - Developer guide with examples
- [UPS Architecture](./docs/UPS_ARCHITECTURE.md) - Universal Parameter Schema technical guide
- [Phase 2: Advanced Filters](./docs/PHASE_2_ADVANCED_FILTERS.md) - Charge types, tags, purchase options filtering
- [Backend Architecture](./docs/BACKEND_ARCHITECTURE.md) - System design and component documentation
- [Troubleshooting Guide](./docs/TROUBLESHOOTING.md) - Common issues and solutions
- [CUR Setup Guide](./docs/SETUP_CUR.md) - Configure AWS Cost and Usage Reports

## Architecture

### LangGraph Orchestration Pipeline

The platform uses a **LangGraph state machine** with **Pydantic structured outputs** for all LLM interactions:

1. **Query Analysis**: LLM classifies intent into structured `UserQueryAnalysis` with confidence scoring
2. **Semantic Routing**: Enum-based conditional routing (NO string matching) with confidence thresholds
3. **Query Rewriting**: Context-aware query enhancement for follow-up queries (resolves pronouns, expands relative time)
4. **Data Retrieval**: Structured `FinOpsQueryPlan` generation and execution via Athena
5. **Response Synthesis**: Structured `ConversationalResponse` with insights, recommendations, and chart specifications
6. **Message History**: PostgreSQL-backed conversation tracking with `RunnableWithMessageHistory`

**Key Principles:**
- ✅ All LLM outputs use `with_structured_output()` with Pydantic models
- ✅ Routing uses enum comparisons (`intent == "cost_analysis"`) NOT string matching
- ✅ Query rewriting resolves conversational context before data retrieval
- ✅ Agent working state separated from conversation messages
- ✅ Confidence thresholds trigger clarification flows

### Intent Types (10)

- **cost_analysis**: Service/account/region distribution analysis
- **anomaly_detection**: Spike detection and anomaly investigation
- **optimization**: Savings recommendations (RI, SP, rightsizing)
- **forecasting**: Cost projection and trend forecasting
- **budget_tracking**: Budget monitoring and variance analysis
- **resource_analysis**: Resource utilization and efficiency
- **trend_analysis**: Time series trends and patterns
- **comparative_analysis**: Period-over-period comparisons
- **drill_down**: Detailed breakdowns and drill-downs
- **general_inquiry**: Greetings, help, clarification-needed queries

### Backend Components

- **Universal Parameter Schema (UPS)** (`services/ups_extractor.py`, `agents/intent_classifier.py`):
  - LLM + heuristic hybrid extraction of intent + parameters
  - JSON repair layer with schema validation
  - Embedding-based intent validation (`services/embedding/embedding_intent_router.py`)
  - Calibrated clarification thresholds (`config/intent_thresholds.json`)
- **Evaluation & Monitoring** (`evaluation/`):
  - `ups_evaluator.py`: Confusion matrix, precision/recall, confidence stats
  - `calibrate_thresholds.py`: Generate per-intent confidence minimums
  - `drift_monitor.py`: Track accuracy over time, detect degradation
- **Pydantic Models** (`models/finops_schemas.py`): Structured schemas for all LLM interactions
  - `UserQueryAnalysis`: Intent classification output
  - `FinOpsQueryPlan`: Athena query specification
  - `ConversationalResponse`: Final structured response
- **LangGraph Nodes** (`nodes/`): Processing pipeline nodes
  - `analyzer.py`: Intent analysis with structured output
  - `query_rewriter.py`: Conversational query enhancement
  - `retriever.py`: Data retrieval with structured query plans
- **Orchestration** (`orchestrator/router.py`, `graph_workflow.py`):
  - Enum-based semantic routing (NO string matching)
  - LangGraph state machine with message history
- **State Management** (`state/agent_state.py`): Separated working state and conversation memory
- **Athena Templates** (`services/athena_cur_templates.py`): 15+ optimized SQL templates
- **Query Executor** (`services/athena_executor.py`): Async Athena client with result parsing
- **Response Formatter** (`services/response_formatter.py`): Structured FinOps templates
- **Chart Engine** (`services/chart_recommendation.py`): Cardinality-based visualization selection
- **LLM Service** (`services/llm_service.py`): AWS Bedrock integration for insights generation

### Frontend (React + TypeScript)
- Chat interface with markdown rendering and responsive two-column assistant responses when charts are returned
- Chart.js visualizations (column, line, stacked bar, clustered bar, pie) with styled axes, compact legends, and AWS service label abbreviations
- Export capabilities (PNG, PDF, CSV)
- Context-aware follow-up support

> **Tip:** Service label abbreviations (for example, `Amazon Elastic Compute Cloud` → `EC2`) are managed in `frontend/src/components/Chat/ChatInterface.tsx` via the `SERVICE_LABEL_MAP`. Update this map if you need to customize how AWS services are displayed in chart labels or legends.

### Data Layer
- **Primary Source**: AWS Athena querying CUR data in S3
- **Vector Store**: ChromaDB for semantic search (optional)
- **Metadata**: PostgreSQL for conversation history (planned)
- **Cache**: Valkey for query result caching (planned)

## API Documentation

Once running, visit:
- **Backend API**: http://localhost:8000/docs
- **Frontend UI**: http://localhost:3000

## Project Structure

```
finops-orchestrator/
├── backend/                       # FastAPI backend
│   ├── agents/                   # Multi-agent orchestration
│   │   ├── multi_agent_workflow.py       # LangGraph supervisor (entry point)
│   │   ├── intent_classifier.py         # UPS intent → legacy param mapping
│   │   ├── execute_query_v2.py          # Athena query execution agent
│   │   └── optimization_agent.py        # Cost-optimization recommendations
│   ├── api/                      # FastAPI route handlers
│   │   ├── chat.py                       # Main chat endpoint + SSE streaming
│   │   ├── health.py                     # Liveness / readiness / detailed checks
│   │   ├── analytics.py                  # Cost-Explorer analytics
│   │   ├── athena_queries.py             # Query generation, execution, export
│   │   ├── auth.py                       # Login, token, password management
│   │   ├── organizations.py              # Multi-tenant org management
│   │   ├── saved_views.py                # Saved account-scope views
│   │   ├── phase3_enterprise.py          # Scheduled reports, RBAC, dashboards
│   │   ├── opportunities.py              # Optimization opportunities
│   │   ├── scope.py                      # Account-scope switching
│   │   └── reports.py                    # Report endpoints
│   ├── middleware/               # Request-level middleware
│   │   ├── authentication.py            # JWT-only auth (no header fallback)
│   │   ├── account_scoping.py           # Multi-tenant context injection
│   │   ├── rate_limiting.py             # Sliding-window rate limits
│   │   └── security_headers.py          # CSP, HSTS, X-Frame-Options
│   ├── models/                   # Data models
│   │   ├── finops_schemas.py            # Pydantic schemas for LLM I/O
│   │   ├── database_models.py           # SQLAlchemy ORM models
│   │   ├── opportunities.py             # Optimization opportunity models
│   │   └── schemas.py                   # Request/response schemas
│   ├── services/                 # Core business logic (~40 modules)
│   │   ├── athena_cur_templates.py      # 15+ optimized SQL templates
│   │   ├── athena_executor.py           # Async Athena client
│   │   ├── athena_query_service.py      # Query generation + validation
│   │   ├── cache_service.py             # Valkey cache + fail-closed blacklist
│   │   ├── conversation_manager.py      # Postgres-backed chat history
│   │   ├── llm_service.py               # AWS Bedrock integration
│   │   ├── optimization_engine.py       # Savings-opportunity analysis
│   │   ├── rbac_service.py              # Role-based access control
│   │   ├── organization_service.py      # Multi-tenant org logic
│   │   ├── saved_views_service.py       # Account-scope view persistence
│   │   ├── request_context.py           # Per-request tenant context
│   │   ├── audit_log_service.py         # Compliance audit trail
│   │   └── ...                          # + 25 additional service modules
│   ├── config/                   # Configuration
│   │   └── settings.py                  # Pydantic env-based settings
│   ├── utils/                    # Shared utilities
│   │   ├── aws_session.py               # IAM-role session factory
│   │   ├── aws_constants.py             # AWS service/region constants
│   │   ├── sql_validation.py            # SQL injection prevention
│   │   ├── sql_constants.py             # Centralised SQL string literals
│   │   ├── errors.py                    # Centralised error codes + helpers
│   │   ├── pii_masking.py               # Email/PII masking
│   │   ├── auth.py                      # Auth helpers (password hashing, JWT)
│   │   ├── date_parser.py               # Date parsing utilities
│   │   └── logging.py                   # Structlog configuration
│   ├── evaluation/               # Model-evaluation harness
│   │   ├── ups_evaluator.py             # Confusion matrix, precision/recall
│   │   ├── calibrate_thresholds.py      # Per-intent confidence calibration
│   │   └── drift_monitor.py             # Accuracy drift detection
│   ├── scripts/                  # Database seed & migration scripts
│   │   ├── init_database.sh             # Orchestrator (seed + migrate)
│   │   └── seed_all_32_recommendations.sql  # Optimization-recommendation seed
│   ├── alembic/                  # Schema migrations (12 versions)
│   └── main.py                   # FastAPI application entry point
├── frontend/                     # React + TypeScript frontend
│   └── src/
│       ├── components/           # Chat, Opportunities, SavedViews, Scope
│       └── utils/                # Export helpers
├── infrastructure/               # AWS IaC
│   ├── cloudformation/          # CloudFormation templates (3)
│   ├── config/                  # Task definitions, bucket policies, dashboards
│   └── sql/                     # CUR table definitions
├── scripts/                     # Operational scripts
│   ├── deployment/              # Deployment helpers
│   ├── setup/                   # CUR setup & verification
│   └── utilities/               # Athena-results cleanup
├── tests/                       # Test suite (631 tests)
│   ├── unit/                    # Unit tests (organised by layer)
│   │   ├── api/                 #   API sanitisation & health tests
│   │   ├── config/              #   Settings-security tests
│   │   ├── finops/              #   Time-range logic tests
│   │   ├── middleware/          #   Auth, rate-limit, security-header tests
│   │   ├── opportunities/       #   Opportunities API & agent tests
│   │   ├── services/            #   Cache, DB-SSL, IAM-migration tests
│   │   └── utils/               #   Auth, AWS-session, SQL, PII, error tests
│   └── (integration & e2e)     # 20 cross-layer test files
├── docs/                        # Project documentation
├── pytest.ini                   # pytest + asyncio configuration
├── deploy.sh                    # Main deployment script
├── docker-compose.yml           # Local development environment
├── SECURITY_AUDIT_REPORT.md     # Security-audit findings & status
├── DEVELOPER_GUIDE.md           # Developer onboarding guide
└── README.md                    # This file
```

## Configuration

### Required Environment Variables

```bash
# AWS Configuration
AWS_REGION=us-east-1
# Note: AWS credentials are handled via IAM roles (recommended for production)
# or the default credential chain (environment vars, ~/.aws/credentials for local dev)

# AWS Bedrock (for LLM insights)
BEDROCK_MODEL_ID=us.amazon.nova-pro-v1:0
BEDROCK_REGION=us-east-1

# Athena Configuration (REQUIRED)
ATHENA_WORKGROUP=primary
ATHENA_OUTPUT_LOCATION=s3://finops-intelligence-platform-data-${AWS_ACCOUNT_ID}/athena-results/
ATHENA_DATABASE=cur_database              # Your CUR database name
ATHENA_TABLE=cur_table                    # Your CUR table name
ATHENA_CATALOG=AwsDataCatalog

# Optional: Database for conversation persistence
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/finops

# Optional: Vector store for semantic search
CHROMA_DB_PATH=./data/chroma

# Application
LOG_LEVEL=INFO
ENVIRONMENT=development

# LLM-based conversation understanding (enabled by default)
# Set to 'false' to use rule-based parameter extraction instead
# USE_LLM_CONVERSATION_UNDERSTANDING=false
```

### Athena Setup Requirements

Your CUR data must be configured in AWS:
1. Enable Cost and Usage Reports in AWS Billing Console
2. Configure report to deliver to S3 bucket (must be globally unique, e.g. finops-intelligence-platform-data-${AWS_ACCOUNT_ID})
3. Set up Athena database and table (see `scripts/setup/setup-cur.sh`)
4. Grant appropriate IAM permissions for Athena and S3 access

See [AWS Deployment Guide](./docs/AWS_DEPLOYMENT_GUIDE.md) for detailed setup.

## Security & Access Control

### Authentication & Authorization

**JWT-Based Authentication**
- Secure password hashing with PBKDF2-HMAC-SHA256 (600,000 iterations - OWASP 2023+ compliant)
- Automatic password hash migration from legacy (100k) to current (600k) iterations on login
- Constant-time comparison to prevent timing attacks
- Access and refresh tokens with configurable expiration
- Token blacklisting for secure logout

**Role-Based Access Control (RBAC)**
- Platform admin (`is_admin` flag) - Full system access
- Organization roles: `owner`, `admin`, `member` - Per-organization permissions
- Configuration-based permissions (no hardcoded role checks)
- Multi-tenant organization isolation

### Rate Limiting

**Multi-Layer Rate Limiting with Per-User Fairness**

Prevents resource hogging through 3-tier rate limiting system:

```
Layer 1: Per-User Limits (prevents single user from consuming all resources)
         ↓
Layer 2: Organization Limits (enforces subscription tier quotas)
         ↓
Request Allowed
```

**Priority Hierarchy:**
1. **User-specific override** (highest) - Custom limit for specific user
2. **Organization role override** - Custom limit for role within organization
3. **System tier default** - Default limit based on subscription tier
4. **Conservative fallback** (lowest) - 10 requests/hour if all else fails

**Default Limits by Tier:**
- **Enterprise** (200 req/hour org): owner/admin=100, member=50 per user
- **Standard** (50 req/hour org): owner/admin=30, member=15 per user
- **Free** (10 req/hour org): owner/admin=5, member=3 per user

**Configuration:**
```bash
# Organization limits (by subscription tier)
ATHENA_EXPORT_LIMIT_ENTERPRISE=200
ATHENA_EXPORT_LIMIT_STANDARD=50
ATHENA_EXPORT_LIMIT_FREE=10

# Per-user limits (Enterprise tier)
ATHENA_EXPORT_PER_USER_LIMIT_ENTERPRISE_OWNER=100
ATHENA_EXPORT_PER_USER_LIMIT_ENTERPRISE_ADMIN=100
ATHENA_EXPORT_PER_USER_LIMIT_ENTERPRISE_MEMBER=50

# Per-user limits (Standard tier)
ATHENA_EXPORT_PER_USER_LIMIT_STANDARD_OWNER=30
ATHENA_EXPORT_PER_USER_LIMIT_STANDARD_ADMIN=30
ATHENA_EXPORT_PER_USER_LIMIT_STANDARD_MEMBER=15

# Per-user limits (Free tier)
ATHENA_EXPORT_PER_USER_LIMIT_FREE_OWNER=5
ATHENA_EXPORT_PER_USER_LIMIT_FREE_ADMIN=5
ATHENA_EXPORT_PER_USER_LIMIT_FREE_MEMBER=3
```

### Admin API for Rate Limit Management

**Platform Admin Endpoints** (requires `is_admin=true`):
```http
# View organization's rate limits
GET /api/admin/rate-limits/organizations/{org_id}/{endpoint}

# Set role-based limits
PUT /api/admin/rate-limits/organizations/{org_id}/roles
Body: {
  "endpoint": "athena_export",
  "role_limits": [{"role": "member", "requests_per_hour": 75}]
}

# Set user-specific limit
PUT /api/admin/rate-limits/organizations/{org_id}/users/{user_id}
Body: {
  "endpoint": "athena_export",
  "user_id": "uuid",
  "requests_per_hour": 200,
  "notes": "Power user - data analyst"
}

# Reset role to system default
DELETE /api/admin/rate-limits/organizations/{org_id}/roles/{role}

# Reset user to role default
DELETE /api/admin/rate-limits/organizations/{org_id}/users/{user_id}
```

**Organization Admin Endpoints** (requires organization owner/admin role):
```http
# Same endpoints with different prefix
GET    /api/organizations/{org_id}/rate-limits/{endpoint}
PUT    /api/organizations/{org_id}/rate-limits/roles
PUT    /api/organizations/{org_id}/rate-limits/users/{user_id}
DELETE /api/organizations/{org_id}/rate-limits/roles/{role}
DELETE /api/organizations/{org_id}/rate-limits/users/{user_id}
```

**Use Cases:**
- **Set role overrides**: Increase member limit from 50/hour to 75/hour for entire organization
- **Give power user custom limit**: Data analyst needs 200/hour instead of default 50/hour
- **Restrict intern access**: Admin intern gets only 25/hour instead of default 100/hour

**Database Tables:**
- `organization_rate_limits` - Role-based overrides per organization
- `user_rate_limits` - User-specific overrides

**Access Control:**
- Platform admins can manage any organization's limits
- Organization admins can only manage their own organization
- Regular members cannot access rate limit management

### Security Features

**Password Security (HIGH-NEW-2 Fix)**
- PBKDF2-HMAC-SHA256 with 600,000 iterations (OWASP 2023+ compliant)
- Version tracking for password hashes (v1=100k legacy, v2=600k current)
- Automatic transparent migration on login (no password resets required)
- Constant-time comparison using `secrets.compare_digest()`

**PII Protection (HIGH-6 Fix)**
- Email masking in authentication logs (`u***@example.com`)
- No sensitive data in error messages or logs

**CSRF Protection**
- Secure cookie configuration with SameSite policies
- Token-based authentication (JWT in Authorization header)

**Security Headers**
- Content Security Policy (CSP) with strict directives
- HTTP Strict Transport Security (HSTS)
- X-Frame-Options: DENY (clickjacking protection)
- X-Content-Type-Options: nosniff

**SQL Injection Prevention**
- Parameterized queries throughout
- No string concatenation for SQL generation
- Centralized SQL constants

See [SECURITY_AUDIT_REPORT.md](./SECURITY_AUDIT_REPORT.md) for complete security audit findings and remediation status.

## Development

### Running Tests
```bash
# All backend tests (631 tests — run from project root)
pytest

# Unit tests only
pytest tests/unit/

# Specific layer
pytest tests/unit/api/          # API sanitisation & health
pytest tests/unit/middleware/   # Auth, rate-limiting, security headers
pytest tests/unit/services/     # Cache, DB-SSL, IAM migration

# Frontend tests
cd frontend && npm test
```

### Code Quality
```bash
# Backend formatting
cd backend && black . && isort .

# Frontend formatting
cd frontend && npm run lint:fix
```

## Deployment

### AWS Infrastructure Components
- **ECS Fargate**: Container orchestration
- **ALB**: Load balancing and SSL termination
- **RDS PostgreSQL**: Primary database
- **ElastiCache Valkey**: Caching layer
- **S3**: Static assets and CUR data storage
- **CloudWatch**: Monitoring and logging
- **Cognito**: Authentication and authorization

### CI/CD Pipeline
- GitHub Actions for automated testing and deployment
- Automated infrastructure provisioning
- Blue/green deployments for zero downtime

## Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## License

This project is proprietary to DAZN Group Limited. All rights reserved.

## Documentation

### Active Documentation
- **[AWS Deployment Guide](./docs/AWS_DEPLOYMENT_GUIDE.md)** - Complete AWS deployment instructions
- **[Quick Start Guide](./docs/QUICK_START.md)** - Developer onboarding with code examples
- **[UPS Architecture](./docs/UPS_ARCHITECTURE.md)** - Universal Parameter Schema technical documentation
- **[Phase 2: Advanced Filters](./docs/PHASE_2_ADVANCED_FILTERS.md)** - Filter implementation guide
- **[Backend Architecture](./docs/BACKEND_ARCHITECTURE.md)** - System design and components
- **[CUR Setup Guide](./docs/SETUP_CUR.md)** - AWS Cost and Usage Reports configuration
- **[Troubleshooting](./docs/TROUBLESHOOTING.md)** - Common issues and solutions

### Recently Removed (December 2025 Cleanup)
- ~~OPTIMIZATION_IMPLEMENTATION_PLAN.md~~ - Completed, archived
- ~~CONTEXT_AWARE_ROUTING.md~~ - Superseded by UPS Architecture
- ~~ADVANCED_MULTI_AGENT.md~~ - Superseded by Backend Architecture
- ~~LEGACY_CUR_MODE.md~~ - Obsolete CUR documentation
- ~~PHASE_1_IMPLEMENTATION.md~~ - Completed planning document
- ~~LLM_ARCHITECTURE_PROPOSAL.md~~ - Implemented in Phase 1

## Support

For technical support and questions:
- **Technical Lead**: FinOps Platform Team
- **Architecture Questions**: Cloud Architecture Team
- **Deployment Issues**: Performance Engineering Team

## Roadmap

### Phase 1: Foundation ✅ COMPLETED

**Core Intelligence & Query Processing**
- ✅ Universal Parameter Schema (UPS) with LLM + heuristic hybrid extraction
- ✅ JSON repair layer with schema validation
- ✅ Embedding-based intent validation and confidence boosting
- ✅ Calibrated clarification thresholds from evaluation runs
- ✅ Evaluation harness (confusion matrix, precision/recall, confidence stats)
- ✅ Drift monitoring for accuracy tracking over time
- ✅ Follow-up time range inheritance for multi-turn conversations

**LangGraph Orchestration**
- ✅ LangGraph state machine with structured outputs
- ✅ Pydantic models for all LLM interactions
- ✅ Conversational query rewriting with context resolution
- ✅ Enum-based semantic routing (no string matching)
- ✅ Separated agent state from conversation memory
- ✅ PostgreSQL-backed message history with RunnableWithMessageHistory

**Data Layer & Visualization**
- ✅ 15+ Athena SQL templates with partition optimization
- ✅ Async query execution with result parsing
- ✅ Structured FinOps response formatting
- ✅ Intent-based chart recommendations

### Phase 2: Advanced Filter Support ✅ COMPLETED

**Query Filtering Capabilities**
- ✅ Charge type filtering (exclude taxes, credits, fees, support charges)
- ✅ Purchase option filtering (On-Demand, Reserved, Spot, Savings Plans)
- ✅ Tag-based filtering (Environment, CostCenter, custom tags)
- ✅ Platform filtering (Linux, Windows, RHEL, SUSE, Ubuntu)
- ✅ Database engine filtering (MySQL, PostgreSQL, Aurora, etc.)
- ✅ Multi-filter combinations with proper SQL AND/OR logic
- ✅ Centralized synonym mappings (200+ entries, zero hardcoding)
- ✅ AWS Cost Explorer API filter integration
- ✅ 56 test cases (25 unit + 31 E2E tests)

**See:** [Phase 2 Documentation](./docs/PHASE_2_ADVANCED_FILTERS.md) for complete technical details.

### Phase 3: Enterprise Features 🔄 IN PROGRESS

**Completed**
- ✅ Multi-account cost management (consolidated billing, linked accounts)
- ✅ Advanced RBAC (role-based access control, permission management)
- ✅ Audit logging (comprehensive activity tracking for compliance)

**In Development**
- 🔄 Custom dashboard builder (drag-and-drop widgets, personalized views)
- 🔄 Scheduled report generation (CRON, PDF/CSV/Excel, email/S3 delivery)
- 🔄 Integration with ticketing systems (Jira, ServiceNow, GitHub, Linear)
- 🔄 Cost allocation and chargeback (department/team attribution)

### Phase 4: Advanced Analytics ⏳ PLANNED

**Cost Intelligence**
- ⏳ ML-based cost forecasting with trend prediction
- ⏳ Automated anomaly detection with root cause analysis
- ⏳ Advanced optimization recommendations (RI/SP analysis, rightsizing)
- ⏳ Budget management and alerting (threshold-based notifications)

**Platform Expansion**
- ⏳ Real-time streaming responses (WebSocket-based progressive results)
- ⏳ Query result caching with Valkey (sub-second repeat query performance)
- ⏳ Multi-cloud support (Azure Cost Management, GCP Billing)
- ⏳ Reserved Instance and Savings Plan portfolio optimization
