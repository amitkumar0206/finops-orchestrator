# FinOps AI Cost Intelligence Platform

Enterprise-grade AWS cost intelligence platform powered by AI agents, featuring robust service name resolution, multi-turn conversations, and intelligent cost analysis.

## 🌟 Key Features

### Intelligence & Analysis
- 🎯 **Multi-Agent Orchestration**: LangGraph-powered supervisor pattern with specialized agents for cost analysis, optimization, and infrastructure insights
- 🧠 **Universal Parameter Schema (UPS)**: AI-driven intent + parameter extraction with LLM/heuristic hybrid, embedding validation, and JSON repair
- 💬 **Context-Aware Conversations**: Multi-turn dialogue with time range inheritance and conversation persistence
- 📊 **Intelligent Visualizations**: Intent-based chart recommendations with responsive layouts and AWS service label normalization
- 🔍 **Deep Cost Breakdowns**: Drill down from services → usage types → operations with automatic dimension inference

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
│   │   ├── multi_agent_workflow.py       # LangGraph-based multi-agent system (default)
│   │   ├── enhanced_orchestrator.py      # DEPRECATED: Legacy orchestrator
│   │   ├── cost_data_processor.py        # Cost data processing
│   │   ├── external_intelligence.py      # External data sources
│   │   ├── recommendation_engine.py      # Cost optimization recommendations
│   │   └── report_generator.py           # Report generation
│   ├── nodes/                    # LangGraph processing nodes (NEW)
│   │   ├── analyzer.py                   # Intent analysis with structured output
│   │   ├── query_rewriter.py             # Conversational query enhancement
│   │   └── retriever.py                  # Data retrieval with structured plans
│   ├── orchestrator/             # Orchestration layer (NEW)
│   │   └── router.py                     # Enum-based semantic routing
│   ├── state/                    # State management (NEW)
│   │   └── agent_state.py                # Agent state definition
│   ├── models/                   # Data models
│   │   ├── finops_schemas.py             # Pydantic schemas for LLM I/O (NEW)
│   │   ├── database_models.py            # Database models
│   │   └── schemas.py                    # Pydantic schemas
│   ├── services/                 # Core services
│   │   ├── athena_cur_templates.py       # SQL template library
│   │   ├── athena_executor.py            # Async Athena client
│   │   ├── athena_query_service.py       # Athena query service
│   │   ├── response_formatter.py         # FinOps formatting
│   │   ├── chart_recommendation.py       # Visualization engine
│   │   ├── chart_data_builder.py         # Chart data builder
│   │   ├── conversation_manager.py       # Postgres-backed conversation + context
│   │   ├── conversation_context.py       # In-memory context manager
│   │   ├── llm_service.py                # Bedrock integration
│   │   ├── llm_query_refiner.py          # LLM query refinement
│   │   ├── database.py                   # Database service
│   │   └── vector_store.py               # Vector store service
│   ├── api/                      # FastAPI endpoints
│   │   ├── chat.py                       # Main chat endpoint
│   │   ├── health.py                     # Health checks
│   │   ├── analytics.py                  # Analytics endpoints
│   │   ├── athena_queries.py             # Athena query endpoints
│   │   └── reports.py                    # Report endpoints
│   ├── config/                   # Configuration
│   │   └── settings.py                   # Environment settings
│   ├── utils/                    # Utility functions
│   │   ├── date_parser.py                # Date parsing utilities
│   │   └── logging.py                    # Logging configuration
│   ├── graph_workflow.py         # LangGraph workflow definition (NEW)
│   └── main.py                   # FastAPI application
├── frontend/                     # React frontend
│   └── src/
│       └── components/
│           └── Chat/
│               └── ChatInterface.tsx     # Main UI
├── infrastructure/               # AWS infrastructure as code
│   ├── cloudformation/          # CloudFormation templates
│   ├── config/                  # Infrastructure configs
│   └── sql/                     # Database schemas
├── scripts/                     # Operational scripts
│   ├── deployment/              # Deployment scripts
│   ├── setup/                   # Setup and verification scripts
│   │   ├── setup-cur.sh
│   │   ├── verify-cur-setup.sh
│   │   └── verify-deployment-env.sh
│   └── utilities/               # Utility scripts
│       └── convert_csv_to_parquet.py
├── tests/                       # Test suite
├── docs/                        # Documentation
│   ├── AWS_DEPLOYMENT_GUIDE.md
│   ├── DEPLOYMENT_CHECKLIST.md
│   ├── DEPLOYMENT_STRATEGY.md
│   ├── DATA_ARCHITECTURE.md
│   ├── TROUBLESHOOTING.md
│   └── QUICK_START.md
├── deploy.sh                    # Main deployment script
├── docker-compose.yml           # Local development environment
└── PROJECT_STRUCTURE.md         # This file
```

## Configuration

### Required Environment Variables

```bash
# AWS Configuration
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key        # Or use IAM role
AWS_SECRET_ACCESS_KEY=your_secret_key    # Or use IAM role

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

## Development

### Running Tests
```bash
# Backend tests
cd backend && pytest

# Frontend tests  
cd frontend && npm test

# Integration tests
docker-compose -f docker-compose.test.yml up --abort-on-container-exit
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
- **Technical Lead**: [Amit Kumar] <amit.kumar2@dazn.com>
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
