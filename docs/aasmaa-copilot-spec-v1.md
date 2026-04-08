
# Aasmaa Copilot Implementation Specification v1
_Last updated: 2026-04-08_

## 1. Purpose of this file

This specification is designed to be read directly by GitHub Copilot (agent mode) and used as the implementation contract for Aasmaa’s next product phase.

Recommended usage pattern:

- `Read docs/aasmaa-copilot-spec-v1.md and implement feature F-001 end-to-end.`
- `Read docs/aasmaa-copilot-spec-v1.md and implement only the backend for feature F-006.`
- `Read docs/aasmaa-copilot-spec-v1.md and implement tests for feature F-004.`
- `Read docs/aasmaa-copilot-spec-v1.md and create the UI wireframe-aligned frontend for feature F-003.`

This document assumes the current Aasmaa codebase already contains:
- AWS-focused FinOps chat over CUR/Athena with multi-agent routing
- optimization opportunities and CUR mining
- multi-tenant scope enforcement
- demo admin and token controls
- IaC analysis and blueprint generation
- deployment scripts for local, demo AWS, and production AWS
- partial report scaffolding and no real dashboard builder yet

## 2. Product thesis

Aasmaa should not try to win by being “another cloud cost dashboard.”

Aasmaa should win by becoming the **AI-native FinOps operating system** for CFOs, FinOps teams, and platform engineering teams.

### Aasmaa must beat AWS native and Amazon Q on these axes

1. **Cross-cloud and cross-vendor normalization**
2. **Business mapping and 100% allocation**
3. **Closed-loop remediation and realized savings**
4. **Executive reporting and board-ready narratives**
5. **Engineering workflow integration**
6. **Governance and policy automation**
7. **AI cost visibility across internal and external model spend**

### What Aasmaa already has that is strategically valuable

- CUR-first AI analysis with text-to-SQL over Athena
- advisory-mode billing file upload without needing live AWS access
- strong multi-tenant scoping model
- optimization signal aggregation from multiple AWS-native sources
- FinOps-to-engineering bridge through IaC analysis and blueprint generation

These are meaningful differentiators and must be preserved.

## 3. Product goals

### Primary goals
- Reduce customer cloud run-rate with measurable realized savings
- Increase forecast accuracy and budget predictability
- Drive accountability through allocation, ownership, and workflow
- Make Aasmaa the system of record for executive cloud-finance reporting
- Shorten time from issue detection to issue remediation

### Secondary goals
- Expand from AWS-first to multi-cloud
- Support engineering-native workflows via IaC, pull requests, policies, and APIs
- Support AI/LLM cost management as an emerging spend category

### Non-goals for this phase
- Becoming a general observability platform
- Replacing customer ERP/GL systems
- Full procurement or vendor-management system in phase one
- Auto-remediation of production resources without explicit guardrails and approval controls

## 4. Global implementation principles

These rules apply to every feature.

### 4.1 Security and tenancy
- Every new API and query path must preserve organization scoping and allowed-account enforcement.
- All user actions affecting reporting, policies, allocations, budgets, anomalies, or remediation must be audit logged.
- Any outbound webhook or integration endpoint must preserve SSRF protections and allowlist validation.
- No feature should bypass existing JWT, RBAC, rate limiting, or feature access gates.

### 4.2 UX principles
- CFO views must be calm, narrative, and outcome-oriented.
- FinOps operator views must be filterable, evidence-rich, and workflow-oriented.
- Engineering views must be action-oriented, technically specific, and linked to remediation.
- Every high-severity issue should be actionable in 2 clicks or fewer.
- Every major page must show freshness, scope, and confidence.

### 4.3 Architecture principles
- Extend the current FastAPI + React + Postgres + Athena + S3 + Valkey approach where possible.
- Reuse existing chart, response formatting, conversation, and scoping infrastructure.
- Prefer strongly typed APIs, versioned resources, and immutable snapshots for finance-facing outputs.
- Favor explainable models over black-box models for forecasting, allocation, and anomaly detection.

### 4.4 Delivery principles
- All features must ship behind feature flags.
- Every feature must support partial rollout by org, role, or environment.
- Every feature must include migration notes, tests, metrics, and acceptance criteria.

## 5. Repo assumptions and coding touchpoints

Based on the current codebase, new features should generally plug into these areas:

### Existing backend areas to extend
- `backend/api/`
- `backend/services/`
- `backend/models/`
- `backend/middleware/`
- `backend/alembic/`
- `backend/utils/`

### Existing frontend areas to extend
- `frontend/src/pages/`
- `frontend/src/components/`
- `frontend/src/lib/api.ts`
- `frontend/src/context/AuthContext.tsx`

### Existing operational paths to extend
- `scripts/deployment/`
- `scripts/setup/`
- `infrastructure/cloudformation/`
- `docs/`

## 6. Feature tracker template

Use this table in the repo and update it in every feature PR.

| ID | Feature | Priority | Status | KPI | Target Release | Owner | Dependencies | Notes |
|---|---|---:|---|---|---|---|---|---|
| F-001 | Multi-cloud ingestion and FOCUS normalization | P0 | Implemented (MVP) | % spend ingested | Phase 1 | TBD | none | Advisory upload, normalization, run history, and unified spend preview are shipped; connected-mode pulls remain follow-up work |
| F-002 | Allocation engine and virtual tagging | P0 | Planned | % spend allocated | Phase 1 | TBD | F-001 | Must support shared costs |
| F-003 | Executive dashboards and builder | P0 | Planned | weekly executive usage | Phase 1 | TBD | F-001, F-002 | Replaces current gap |
| F-004 | Scheduled reports and board packs | P0 | Planned | report automation adoption | Phase 1 | TBD | F-003 | Current reports are mock-only |
| F-005 | Budgets, forecasting, explainability | P0 | Planned | forecast accuracy | Phase 1 | TBD | F-001, F-002 | Must support multi-cloud |
| F-006 | Anomaly detection and investigation | P0 | Planned | TTD, TTTR | Phase 1 | TBD | F-001 | Must tie to budget risk |
| F-007 | Ownership workflows and savings pipeline | P0 | Planned | % findings actioned | Phase 1 | TBD | F-002, F-006 | Must show realized savings |
| F-008 | Commitment autopilot | P1 | Planned | ESR uplift | Phase 2 | TBD | F-001, F-005 | AWS/Azure/GCP commitment strategy |
| F-009 | Policy engine: guidelines and guardrails | P1 | Planned | policy compliance rate | Phase 2 | TBD | F-002, F-007 | Simulation required |
| F-010 | Agentic remediation and PR automation | P1 | Planned | realized savings/month | Phase 2 | TBD | F-007, F-009 | Approval flow required |
| F-011 | Kubernetes cost module | P1 | Planned | K8s allocation coverage | Phase 2 | TBD | F-001, F-002 | OpenCost-style ingestion |
| F-012 | FinOps as code | P1 | Planned | % config version-controlled | Phase 2 | TBD | F-002, F-009 | YAML first, Terraform next |
| F-013 | AI cost intelligence | P1 | Planned | AI spend coverage | Phase 2 | TBD | F-001, F-002 | Track token and model costs |
| F-014 | Pricing and contract optimization | P2 | Planned | negotiated savings uplift | Phase 3 | TBD | F-005, F-008 | EDP/discount planning |

## 7. Wireframes

These are low-fidelity wireframes to guide layout and information hierarchy. Copilot should follow the structure, not necessarily the exact ASCII spacing.

---

## WF-01: CFO Home Dashboard

```text
+--------------------------------------------------------------------------------------------------+
| AASMAA | CFO Home                                           Scope: Global    Freshness: Daily    |
+--------------------------------------------------------------------------------------------------+
| MTD Spend        | MTD Budget       | Forecast EOM      | Realized Savings | Budget Risk        |
| $4.8M            | $5.1M            | $5.3M             | $420k            | Medium             |
+--------------------------------------------------------------------------------------------------+
| Spend vs Budget (line/area)                   | Forecast Confidence Bands                          |
|                                                |                                                     |
+--------------------------------------------------------------------------------------------------+
| Top 5 Cost Drivers                             | Anomalies Requiring Attention                      |
| 1. EKS compute +$140k                          | 3 high severity anomalies                          |
| 2. Cross-region data +$90k                     | 1 budget breach risk                               |
| 3. Databricks +$70k                            | 2 unassigned owners                                |
+--------------------------------------------------------------------------------------------------+
| Savings Pipeline                               | Allocation Coverage                                |
| Discover | Assigned | In Progress | Realized   | Allocated 92% | Inferred 5% | Unallocated 3%   |
+--------------------------------------------------------------------------------------------------+
| [Board-ready mode] [Download CFO Pack] [Create Budget] [View Drivers] [Open Savings Pipeline]   |
+--------------------------------------------------------------------------------------------------+
```

---

## WF-02: Data Sources Wizard

```text
+-----------------------------------------------------------------------------------------------+
| Add Data Source                                                                               |
+-----------------------------------------------------------------------------------------------+
| Step 1: Choose Source                                                                         |
| [AWS CUR] [Azure Export] [GCP Billing Export] [SaaS/AnyCost CSV] [AI API Cost Feed]          |
+-----------------------------------------------------------------------------------------------+
| Step 2: Connection Mode                                                                       |
| ( ) Connected mode   ( ) Advisory upload                                                      |
+-----------------------------------------------------------------------------------------------+
| Step 3: Security + Scope                                                                      |
| Access model: role / service principal / upload only                                          |
| Org visibility: [All org admins] [Specific roles]                                             |
| Retention: [12 mo] [24 mo] [custom]                                                           |
+-----------------------------------------------------------------------------------------------+
| Step 4: Validation                                                                            |
| Currency detected     ✔                                                                       |
| Billing period        ✔                                                                       |
| Account/project IDs   ✔                                                                       |
| Service dimensions    ✔                                                                       |
| Missing fields        none                                                                    |
+-----------------------------------------------------------------------------------------------+
| [Back] [Save draft] [Test connection] [Ingest now]                                            |
+-----------------------------------------------------------------------------------------------+
```

---

## WF-03: Allocation Studio

```text
+-------------------------------------------------------------------------------------------------------+
| Allocation Studio                                      Coverage 92%   Inferred 5%   Unallocated 3%   |
+-------------------------------------------------------------------------------------------------------+
| Left rail: Cost dimensions                                                                            |
| - Team                                                                                               |
| - Product                                                                                            |
| - Customer                                                                                           |
| - Environment                                                                                        |
| - Region                                                                                             |
| - Custom...                                                                                          |
+-------------------------------------------------------------------------------------------------------+
| Rule Builder                                                                                          |
| IF provider = aws AND tag.team exists => Team = tag.team                                              |
| ELSE IF account_name contains "prod-payments" => Product = Payments                                  |
| ELSE distribute shared EKS cluster costs by CPU requests across namespaces                            |
|                                                                                                       |
| [Preview impact] [Simulate last month] [Publish] [Rollback]                                          |
+-------------------------------------------------------------------------------------------------------+
| Preview Results                                                                                        |
| Before: 78% allocated      After: 96% allocated                                                       |
| Spend moved: $1.8M         Shared cost reallocated: $420k                                             |
| Warnings: 2 overlapping rules                                                                          |
+-------------------------------------------------------------------------------------------------------+
```

---

## WF-04: Budget and Forecast Workspace

```text
+------------------------------------------------------------------------------------------------------+
| Budgets & Forecasts                                                                                  |
+------------------------------------------------------------------------------------------------------+
| Budget Scope: [Global] [Team] [Product] [Environment] [Customer]                                    |
| Time Horizon: [Month] [Quarter] [Year] [18 months]                                                  |
+------------------------------------------------------------------------------------------------------+
| Current actuals | Forecast EOM | Variance to budget | Confidence                                     |
| $4.8M           | $5.3M        | +$200k             | 83%                                            |
+------------------------------------------------------------------------------------------------------+
| Chart: Actuals / Forecast / Budget / Confidence band                                                 |
+------------------------------------------------------------------------------------------------------+
| Why this forecast?                                                                                   |
| - EKS compute trending +11% WoW                                                                      |
| - data transfer spike in APAC                                                                        |
| - reserved coverage drops in 42 days                                                                 |
+------------------------------------------------------------------------------------------------------+
| Top actions                                                                                          |
| [assign owner] [create ticket] [open savings opportunity] [adjust budget]                            |
+------------------------------------------------------------------------------------------------------+
```

---

## WF-05: Anomaly Investigation Workspace

```text
+-----------------------------------------------------------------------------------------------------+
| Anomaly #AN-1042                            Severity: High     Forecast budget impact: +$95k        |
+-----------------------------------------------------------------------------------------------------+
| Summary                                                                                             |
| Sudden increase in cross-region data transfer for Payments in us-east-1 -> eu-west-1               |
+-----------------------------------------------------------------------------------------------------+
| Timeline                                 | Top Contributors                                          |
| - detected 09:40 UTC                     | S3 transfer    +$42k                                     |
| - widened 13:20 UTC                      | EKS egress     +$31k                                     |
| - owner missing                          | CloudFront     +$12k                                     |
+-----------------------------------------------------------------------------------------------------+
| Likely causes                                                                                        |
| [x] traffic shift   [x] deployment change   [ ] new service launch   [ ] tag drift                 |
+-----------------------------------------------------------------------------------------------------+
| Evidence                                                                                             |
| linked line items | linked queries | linked resources | linked cost dimensions                       |
+-----------------------------------------------------------------------------------------------------+
| Actions                                                                                              |
| [Assign owner] [Create Jira] [Open Slack thread] [Mark resolved] [Create remediation PR]           |
+-----------------------------------------------------------------------------------------------------+
```

---

## WF-06: Savings Pipeline

```text
+-----------------------------------------------------------------------------------------------------+
| Savings Pipeline                                                                                    |
+-----------------------------------------------------------------------------------------------------+
| Discover ($820k) | Validate ($600k) | Assigned ($410k) | In Progress ($190k) | Realized ($280k)   |
+-----------------------------------------------------------------------------------------------------+
| Card                                                                                                 |
| Opportunity: gp2 -> gp3 migration                                                                    |
| Estimated savings: $38k/month                                                                        |
| Owner: Platform Storage                                                                              |
| Status: Assigned                                                                                     |
| Ticket: FIN-221                                                                                      |
| Evidence: 126 volumes                                                                                |
| [Open] [Re-estimate] [Add note]                                                                      |
+-----------------------------------------------------------------------------------------------------+
```

---

## WF-07: Policy Studio

```text
+------------------------------------------------------------------------------------------------------+
| Policy Studio                                                                                        |
+------------------------------------------------------------------------------------------------------+
| Policy Type: ( ) Guideline   ( ) Guardrail                                                           |
| Scope: [Org] [Team] [Product] [Environment]                                                          |
| Schedule: [Hourly] [Daily] [Weekly] [Monthly]                                                        |
+------------------------------------------------------------------------------------------------------+
| Template library                                                                                     |
| - Untagged cost threshold                                                                            |
| - Idle non-prod shutdown                                                                             |
| - Budget overrun notification                                                                        |
| - EBS unattached volume cleanup                                                                      |
+------------------------------------------------------------------------------------------------------+
| Simulation                                                                                            |
| "What would this have done last month?"                                                              |
| Violations: 82                                                                                        |
| Estimated savings: $64k                                                                              |
| Auto-actions blocked by policy: 12                                                                   |
+------------------------------------------------------------------------------------------------------+
| [Save draft] [Run simulation] [Publish] [Progressive rollout]                                        |
+------------------------------------------------------------------------------------------------------+
```

---

## WF-08: K8s Efficiency Dashboard

```text
+------------------------------------------------------------------------------------------------------+
| Kubernetes Efficiency                                                                                |
+------------------------------------------------------------------------------------------------------+
| Cluster selector: [All] [prod-1] [prod-2] [ml-gpu]                                                  |
+------------------------------------------------------------------------------------------------------+
| Cluster cost | idle cost | CPU over-request | memory over-request | GPU idle                        |
| $1.4M        | $120k     | $85k             | $63k                | $22k                            |
+------------------------------------------------------------------------------------------------------+
| Top waste workloads                                                                                  |
| namespace/payments-api | over-requested CPU | est. save $14k                                         |
| namespace/recommenders | idle pods         | est. save $11k                                          |
+------------------------------------------------------------------------------------------------------+
| [Create ticket] [Generate PR] [View allocation] [See namespace unit costs]                          |
+------------------------------------------------------------------------------------------------------+
```

---

## WF-09: AI Cost Console

```text
+------------------------------------------------------------------------------------------------------+
| AI Cost Intelligence                                                                                 |
+------------------------------------------------------------------------------------------------------+
| Total AI Spend | External APIs | Bedrock/OpenAI/Anthropic | Cost / request | Cost / 1k tokens      |
| $420k          | $280k         | mixed                    | $0.032          | $0.0018                |
+------------------------------------------------------------------------------------------------------+
| Spend by model / team / environment                                                                  |
+------------------------------------------------------------------------------------------------------+
| Efficiency insights                                                                                  |
| - prompt size growth in support-bot +18%                                                             |
| - retrieval traffic stable but token output increasing                                               |
| - cheaper model candidate for 23% of requests                                                        |
+------------------------------------------------------------------------------------------------------+
| [Create model policy] [View token anomalies] [Download AI cost report]                               |
+------------------------------------------------------------------------------------------------------+
```

## 8. Shared technical standards for all features

### 8.1 Standard API shape
Every new domain should expose:
- list endpoint
- detail endpoint
- create
- update
- delete or archive
- simulate or preview endpoint if the domain changes finance-facing outputs
- export endpoint if the domain supports CFO/finance workflows

### 8.2 Standard metadata fields
Every new major entity should include:
- `id`
- `organization_id`
- `created_at`
- `updated_at`
- `created_by`
- `updated_by`
- `status`
- `version`
- `is_deleted` or soft-delete equivalent where appropriate

### 8.3 Standard audit fields
Audit all:
- creation and modification of budgets, allocation rules, policies, dashboards, reports, anomaly states, and remediation actions
- export/download of executive packs
- configuration drift between UI and code-driven resources

### 8.4 Standard observability
Each feature should emit:
- request count
- failure count
- processing duration
- job queue lag if async
- resource freshness
- feature-specific KPI metrics

## 9. Phased roadmap

### Phase 1: must ship first
- F-001 Multi-cloud ingestion and normalization
- F-002 Allocation engine and virtual tagging
- F-003 Executive dashboards and builder
- F-004 Scheduled reporting and board packs
- F-005 Budgets, forecasting, explainability
- F-006 Anomaly detection and investigation
- F-007 Ownership workflows and savings pipeline

### Phase 2: differentiation moat
- F-008 Commitment autopilot
- F-009 Policy engine
- F-010 Agentic remediation
- F-011 Kubernetes cost
- F-012 FinOps as code
- F-013 AI cost intelligence

### Phase 3: strategic expansion
- F-014 Pricing and contract optimization

## 10. Detailed feature specifications

---

# F-001 Multi-cloud ingestion and FOCUS normalization

## Implementation status
- Status: Implemented (MVP) as of 2026-04-08
- Shipped: data-source registry, advisory upload ingestion, FOCUS-style normalization for AWS CUR/Azure/GCP/generic CSV, checksum-based idempotency, source run history, freshness indicators, and unified spend preview
- Remaining follow-up: connected-mode provider pulls, normalized parquet/object-storage publication, Athena/Glue publishing, async scheduled ingestion, and frontend automated tests

## Why this exists
Aasmaa is currently strongest in AWS. To beat market leaders and AWS native experiences, the data layer must expand to Azure, GCP, and non-hyperscaler cost feeds.

## Personas
- CFO
- Head of FinOps
- Platform engineering lead
- Solutions architect / cloud governance lead

## User stories
- As a CFO, I want a single cloud-spend view across AWS, Azure, and GCP.
- As a FinOps lead, I want normalized billing data so one dashboard works across providers.
- As a solutions architect, I want advisory uploads for prospects and disconnected environments.

## Scope
### In scope
- AWS CUR ingestion
- Azure Cost Management export ingestion
- GCP Billing export ingestion
- generic CSV/API ingest for other cost sources
- connected mode and advisory upload mode
- FOCUS-aligned normalized storage model

### Out of scope
- real-time cloud inventory for all providers in phase one
- deep provider-specific optimization beyond core normalization

## Backend design
### New services
- `backend/services/data_source_registry.py`
- `backend/services/focus_normalizer.py`
- `backend/services/provider_connectors/aws_cur_connector.py`
- `backend/services/provider_connectors/azure_export_connector.py`
- `backend/services/provider_connectors/gcp_billing_connector.py`
- `backend/services/provider_connectors/generic_cost_connector.py`

### New APIs
- `backend/api/data_sources.py`
- `POST /data-sources`
- `POST /data-sources/{id}/test`
- `POST /data-sources/{id}/ingest`
- `GET /data-sources`
- `GET /data-sources/{id}`
- `GET /data-sources/{id}/runs`
- `POST /data-sources/upload`
- `GET /data-sources/capabilities`

### New models
- `data_sources`
- `data_source_runs`
- `normalized_cost_partitions`
- `source_file_registry`

### Data model notes
- store raw file metadata and checksum
- store schema version
- store provider type
- store currency and timezone
- store ingestion status and validation errors

## Frontend design
### New pages/components
- `frontend/src/pages/DataSourcesPage.tsx`
- `frontend/src/components/DataSources/DataSourceWizard.tsx`
- `frontend/src/components/DataSources/SourceRunHistoryTable.tsx`
- `frontend/src/components/DataSources/DataFreshnessBadge.tsx`

## UX requirements
- use WF-02
- show plain-language security summary
- show freshness at both source and dashboard level
- allow save as draft before credentials are complete
- validation errors must be user-readable, not stack traces

## Deployment and infra changes
- S3 prefix per org and provider for raw uploads
- S3 prefix for normalized parquet
- Athena/Glue tables or views for normalized dataset
- optional async worker or scheduled ingestion job
- secrets storage for provider credentials
- metrics for ingest success/failure and freshness lag

## Tests
### Backend tests
- connector validation tests
- normalization mapping tests
- scoping tests
- ingestion idempotency tests
- bad file and partial schema tests

### Frontend tests
- wizard step transitions
- validation state rendering
- source run history rendering
- permissions checks

### Integration tests
- upload Azure/GCP sample export and query unified spend
- ingest same file twice and verify idempotency
- verify org isolation in source listings

## Acceptance criteria
- one unified query can return spend by provider, service, and month
- advisory upload supports AWS, Azure, GCP
- freshness and validation state visible in UI
- no cross-tenant source leakage

## Current implementation notes
- The current production-ready path is advisory upload.
- Connected-mode endpoint shape exists and is intentionally explicit about being disabled in this deployment.
- Normalized records are persisted in Postgres-backed partition tables today; object-storage and Athena publication are planned infrastructure follow-up work.

## Copilot prompts
### UI/UX prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-001 frontend only. Build the Data Sources page and wizard using WF-02. Use the existing React, TypeScript, and Material UI patterns in the repo. Add validation, draft save, run history, freshness badges, and scoped permissions. Do not stub fake fields that the backend will not support.`

### Backend prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-001 backend only. Add provider connectors for AWS CUR, Azure export, GCP billing export, and generic cost CSV. Normalize outputs into a FOCUS-aligned schema, track source runs, preserve org scoping, emit audit logs, and expose typed FastAPI endpoints. Reuse existing storage, auth, validation, and settings patterns.`

### Deployment prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement the infrastructure and deployment changes for feature F-001. Update CloudFormation, setup scripts, env vars, and any required S3/Athena/Glue resources for raw and normalized cost ingestion. Keep demo mode minimal and production mode robust.`

### Test prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement automated tests for feature F-001. Add backend unit tests, integration tests using representative AWS/Azure/GCP export fixtures, and frontend tests for the wizard, validation, run history, and permissions.`

---

# F-002 Allocation engine and virtual tagging

## Why this exists
This is the biggest competitive gap. CFOs do not want raw cloud bills. They want accountability by team, product, customer, and business unit.

## User stories
- As a FinOps lead, I want to allocate shared platform spend even when native tags are incomplete.
- As a CFO, I want near-100% spend mapped to an owner.
- As an engineer, I want guidance on what tag or rule change would improve allocation coverage fastest.

## Scope
### In scope
- custom cost dimensions
- direct, derived, inferred, and shared-cost allocation
- virtual tagging without changing cloud provider tags
- rule simulation and rollback
- allocation snapshots per billing period

### Out of scope
- ML-heavy allocation inference in phase one beyond explainable rule-based inference

## Backend design
### New services
- `backend/services/allocation_rules_service.py`
- `backend/services/allocation_compiler.py`
- `backend/services/allocation_snapshot_service.py`
- `backend/services/allocation_simulation_service.py`

### New APIs
- `backend/api/allocation.py`
- `GET /allocation/dimensions`
- `POST /allocation/dimensions`
- `GET /allocation/rules`
- `POST /allocation/rules`
- `POST /allocation/rules/{id}/simulate`
- `POST /allocation/rules/{id}/publish`
- `POST /allocation/rules/{id}/rollback`
- `GET /allocation/coverage`
- `GET /allocation/snapshots`
- `GET /allocation/export`

### New models
- `allocation_dimensions`
- `allocation_rules`
- `allocation_rule_versions`
- `allocation_simulations`
- `allocation_snapshots`

## Frontend design
### New pages/components
- `frontend/src/pages/AllocationStudioPage.tsx`
- `frontend/src/components/Allocation/RuleBuilder.tsx`
- `frontend/src/components/Allocation/CoverageMeter.tsx`
- `frontend/src/components/Allocation/SimulationResultPanel.tsx`

## UX requirements
- use WF-03
- natural-language rule helper
- overlap warnings and precedence visualization
- allocation coverage meter always visible
- simulation required before publish for finance-facing rules
- show “cost moved” and “new coverage achieved” before publish

## Deployment and infra changes
- scheduled monthly snapshot job
- optional daily coverage recomputation
- metrics: allocated %, inferred %, unallocated %, snapshot duration

## Tests
### Backend
- rule compile tests
- precedence tests
- shared cost distribution tests
- version rollback tests
- snapshot immutability tests

### Frontend
- rule editor interactions
- simulation diff rendering
- validation and overlap warnings
- coverage meter updates

### Integration
- partial tagging dataset improves to target coverage after rules applied
- exports remain stable after later rule changes due to snapshots

## Acceptance criteria
- at least 95% allocation achievable on representative partially tagged datasets
- monthly snapshots are stable and exportable
- rollback restores prior finance-facing state without data corruption

## Copilot prompts
### UI/UX prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-002 frontend only. Build Allocation Studio using WF-03 with dimensions, rule builder, simulation results, coverage meter, warnings, and publish/rollback flows. Preserve a finance-grade UX with strong guardrails.`

### Backend prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-002 backend only. Create a rule-based allocation engine with direct, derived, inferred, and shared-cost allocation. Add versioning, simulation, monthly snapshots, exports, audit logs, and strict org scoping. Reuse Athena-oriented query generation where practical.`

### Deployment prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement the scheduling and infrastructure changes for feature F-002. Add snapshot jobs, metrics, environment configuration, and any storage/index changes required for allocation coverage queries and immutable monthly exports.`

### Test prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement tests for feature F-002. Cover rule precedence, simulation, snapshotting, rollback, exports, frontend validation, and multi-tenant isolation.`

---

# F-003 Executive dashboards and dashboard builder

## Why this exists
The README already identifies dashboard builder as a gap. This is mandatory for CFO and exec adoption.

## User stories
- As a CFO, I want a calm default dashboard that answers spend, budget, forecast, risk, and savings.
- As a FinOps lead, I want custom dashboards for execs, business units, and engineering teams.
- As an admin, I want shareable links that remain scope-safe.

## Scope
### In scope
- dashboard builder
- widget library
- saved dashboards
- shareable links
- board-ready mode
- multi-cloud and allocation-aware filtering

### Out of scope
- pixel-perfect BI tool parity

## Backend design
### New services
- `backend/services/dashboard_service.py`
- `backend/services/dashboard_render_service.py`
- `backend/services/widget_query_service.py`

### APIs
- `backend/api/dashboards.py`
- `GET /dashboards`
- `POST /dashboards`
- `GET /dashboards/{id}`
- `PATCH /dashboards/{id}`
- `POST /dashboards/{id}/duplicate`
- `GET /dashboards/{id}/render`
- `POST /dashboards/{id}/share-link`

### Models
- `dashboards`
- `dashboard_widgets`
- `dashboard_shares`

## Frontend design
### New pages/components
- `frontend/src/pages/DashboardsPage.tsx`
- `frontend/src/pages/CFOHomePage.tsx`
- `frontend/src/components/Dashboards/WidgetLibrary.tsx`
- `frontend/src/components/Dashboards/DashboardCanvas.tsx`
- `frontend/src/components/Dashboards/BoardReadyToggle.tsx`

## UX requirements
- use WF-01
- default presets: CFO Home, FinOps Ops, Engineering Efficiency, Budget Control
- support drag/drop and resize
- each widget shows freshness and source scope
- board-ready mode hides noisy operator-only panels

## Deployment and infra changes
- caching for dashboard render payloads
- read-optimized materialized views for common widgets
- metrics for widget render latency and dashboard view usage

## Tests
- widget query correctness
- share link scope enforcement
- dashboard CRUD tests
- board-ready rendering behavior
- dashboard filter persistence

## Acceptance criteria
- a CFO can land on a default dashboard and understand current cloud health in under 60 seconds
- custom dashboards can be saved and shared without exposing data outside allowed scope

## Copilot prompts
### UI/UX prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-003 frontend only. Build CFO Home and the dashboard builder using WF-01, with a widget library, drag/drop layout, filter controls, board-ready mode, freshness badges, and role-safe sharing flows.`

### Backend prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-003 backend only. Add dashboards, widgets, render APIs, share links, and scope-safe filtering. Reuse existing chart and response formatting capabilities where possible. Keep widget queries typed and testable.`

### Deployment prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement infrastructure changes for feature F-003. Add any caching, materialized views, env vars, and operational metrics needed for fast dashboard rendering in demo and production modes.`

### Test prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement tests for feature F-003 covering CRUD, widget rendering, sharing, filtering, RBAC, and frontend interactions for the dashboard builder.`

---

# F-004 Scheduled reports and board packs

## Why this exists
Reports are currently scaffolded or mock-only. This must become a real product surface.

## User stories
- As a CFO, I want monthly board-ready cloud cost packs delivered automatically.
- As a FinOps lead, I want weekly operational reports with changes, drivers, actions, and savings.
- As an admin, I want templated report definitions with retention and auditability.

## Scope
### In scope
- scheduled reports
- PDF export
- PPTX export
- email delivery
- Slack delivery
- report templates with strongly typed placeholders
- immutable artifact retention

### Out of scope
- fully free-form templating in phase one

## Backend design
### Services
- extend `backend/services/scheduled_report_service.py`
- add `backend/services/report_artifact_service.py`
- add `backend/services/report_template_service.py`

### APIs
- extend `backend/api/reports.py`
- `GET /reports/templates`
- `POST /reports/schedules`
- `GET /reports/schedules`
- `POST /reports/{id}/run-now`
- `GET /reports/runs`
- `GET /reports/artifacts/{id}`

### Models
- `report_templates`
- `report_schedules`
- `report_runs`
- `report_artifacts`

## Frontend design
### Pages/components
- `frontend/src/pages/ReportsPage.tsx`
- `frontend/src/components/Reports/ReportTemplatePicker.tsx`
- `frontend/src/components/Reports/ReportScheduleForm.tsx`
- `frontend/src/components/Reports/ArtifactHistoryTable.tsx`

## UX requirements
- reports must answer: what changed, why, what we did, what we saved
- templates: CFO pack, QBR pack, weekly ops pack, business-unit report
- show last successful run, artifact links, and failure diagnostics
- show strong security note for delivery channels

## Deployment and infra changes
- secure storage for report artifacts
- background worker for scheduled report generation
- SMTP/email or existing email service integration
- Slack integration secrets
- SSRF-safe webhook support only if explicitly enabled

## Tests
- schedule creation tests
- artifact generation tests
- placeholder safety tests
- delivery success/failure handling
- retention tests

## Acceptance criteria
- monthly CFO pack can be generated and delivered without manual slide assembly
- artifacts are immutable and auditable
- failed runs are diagnosable without reading raw logs

## Copilot prompts
### UI/UX prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-004 frontend only. Build the Reports page with template selection, schedule form, artifact history, delivery channel configuration, run-now support, and failure diagnostics. Keep the UX executive-friendly and operationally clear.`

### Backend prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-004 backend only. Replace report mocks with real templates, schedules, report runs, artifact storage, PDF/PPTX generation hooks, delivery integrations, retention, and audit logs. Preserve SSRF and SSTI protections.`

### Deployment prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement deployment changes for feature F-004. Add background scheduling support, artifact storage configuration, secrets wiring for email/Slack, and operational metrics for report run success and latency.`

### Test prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement tests for feature F-004 covering template safety, schedule execution, artifact creation, delivery outcomes, and frontend run history behavior.`

---

# F-005 Budgets, forecasting, and explainability

## Why this exists
Customers and CFOs need predictability, not just optimization findings.

## User stories
- As a CFO, I want to know whether we will exceed plan and why.
- As a FinOps lead, I want budgets at org, team, product, and environment level.
- As an engineering manager, I want budget issues tied to concrete drivers and actions.

## Scope
### In scope
- hierarchical budgets
- forecast horizons: 1 month, 3 month, 12 month, 18 month
- confidence bands
- forecast driver explanations
- alerting
- budget breach workflows

### Out of scope
- black-box ML forecasting without explainability

## Backend design
### Services
- `backend/services/budget_service.py`
- `backend/services/forecast_service.py`
- `backend/services/forecast_explainability_service.py`

### APIs
- `backend/api/budgets.py`
- `GET /budgets`
- `POST /budgets`
- `PATCH /budgets/{id}`
- `GET /budgets/{id}/forecast`
- `GET /budgets/{id}/drivers`
- `POST /budgets/{id}/alerts/test`

### Models
- `budgets`
- `budget_alerts`
- `forecasts`
- `forecast_explanations`

## Frontend design
### Pages/components
- `frontend/src/pages/BudgetsPage.tsx`
- `frontend/src/components/Budgets/BudgetForm.tsx`
- `frontend/src/components/Budgets/ForecastChart.tsx`
- `frontend/src/components/Budgets/WhyPanel.tsx`

## UX requirements
- use WF-04
- every budget page must show current actuals, forecast, variance, confidence
- “why” panel must be plain-language and chart-aligned
- breach states should expose assign owner and create ticket actions

## Deployment and infra changes
- scheduled forecast refresh jobs
- metrics for forecast freshness and forecast accuracy
- alert delivery wiring

## Tests
- budget calculation tests
- forecast decomposition tests
- driver explanation consistency tests
- alert threshold tests
- UI rendering for confidence bands and breach states

## Acceptance criteria
- budgets work at org and dimension level
- forecast explanations match observable drivers
- budget alerts can be actioned directly from the UI

## Copilot prompts
### UI/UX prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-005 frontend only. Build the Budgets and Forecasts workspace using WF-04 with forms, charts, confidence bands, plain-language why panels, and direct owner/ticket actions.`

### Backend prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-005 backend only. Add hierarchical budgets, explainable forecast services, forecast driver APIs, and alerting. Prefer decomposition-based forecasts and chart-aligned explanations over opaque models.`

### Deployment prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement infrastructure changes for feature F-005 including scheduled forecast jobs, alert configuration, feature flags, and metrics for freshness and forecast accuracy.`

### Test prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement tests for feature F-005 covering budgets, forecast outputs, explanation consistency, alerts, and frontend breach/why states.`

---

# F-006 Anomaly detection and investigation

## Why this exists
Anomaly detection is already partially present in Aasmaa’s signal set, but it needs to become a first-class workflow.

## User stories
- As a FinOps analyst, I want anomalies that are fast, explainable, and actionable.
- As a CFO, I want to know which anomaly threatens month-end results.
- As an engineer, I want the likely cause, evidence, and next step.

## Scope
### In scope
- anomaly entities
- multi-level anomaly detection
- timeline, contributors, evidence
- budget impact estimation
- action links to tickets and remediation

### Out of scope
- fully autonomous auto-remediation in phase one

## Backend design
### Services
- `backend/services/anomaly_detection_service.py`
- `backend/services/anomaly_investigation_service.py`
- `backend/services/anomaly_alert_service.py`

### APIs
- `backend/api/anomalies.py`
- `GET /anomalies`
- `GET /anomalies/{id}`
- `PATCH /anomalies/{id}`
- `POST /anomalies/{id}/assign`
- `POST /anomalies/{id}/link-ticket`
- `POST /anomalies/{id}/estimate-budget-impact`

### Models
- `anomalies`
- `anomaly_evidence`
- `anomaly_assignments`
- `anomaly_alerts`

## Frontend design
### Pages/components
- `frontend/src/pages/AnomaliesPage.tsx`
- `frontend/src/pages/AnomalyDetailPage.tsx`
- `frontend/src/components/Anomalies/AnomalyTimeline.tsx`
- `frontend/src/components/Anomalies/ContributorTable.tsx`
- `frontend/src/components/Anomalies/BudgetImpactBanner.tsx`

## UX requirements
- use WF-05
- high-severity anomaly detail should show owner status prominently
- one-click journey to create ticket or open remediation PR
- anomalies should be filterable by severity, team, budget risk, provider, service

## Deployment and infra changes
- scheduled anomaly jobs
- optional faster “estimated cost anomaly” layer where available
- metrics: time-to-detect, time-to-root-cause, time-to-resolution

## Tests
- anomaly detection unit tests by detector type
- contributor ranking tests
- budget impact estimation tests
- anomaly state transition tests
- frontend detail page and filter tests

## Acceptance criteria
- anomaly can be triaged and handed off in under 2 minutes
- anomaly detail shows top contributors and likely causes
- scope-safe links can be shared to the relevant org users

## Copilot prompts
### UI/UX prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-006 frontend only. Build anomaly list and detail pages using WF-05 with timelines, contributors, likely causes, evidence, budget impact banners, filters, and action buttons for assign, ticket, and remediation.`

### Backend prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-006 backend only. Convert anomaly detection into a first-class domain with detectors, evidence, budget impact estimation, alerting, state transitions, and assignment/ticket linking APIs.`

### Deployment prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement infrastructure changes for feature F-006. Add scheduled anomaly jobs, optional faster anomaly estimation hooks, env vars, and Prometheus metrics for detection and resolution lifecycle.`

### Test prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement tests for feature F-006 covering detectors, evidence generation, budget impact, state transitions, sharing, and frontend filtering/detail interactions.`

---

# F-007 Ownership workflows and savings pipeline

## Why this exists
Aasmaa must prove realized savings, not only predicted savings.

## User stories
- As a CFO, I want realized savings separated from estimated pipeline.
- As a FinOps lead, I want every recommendation owned and traceable.
- As an engineering lead, I want a clean handoff into Jira, Slack, or ServiceNow.

## Scope
### In scope
- ownership mapping
- ticket integrations
- savings pipeline stages
- realized savings measurement
- variance between predicted and realized savings

### Out of scope
- bespoke workflow engine rivaling enterprise ITSM products

## Backend design
### Services
- `backend/services/ownership_service.py`
- `backend/services/savings_pipeline_service.py`
- `backend/services/realized_savings_service.py`
- `backend/services/ticketing_integrations/`

### APIs
- `backend/api/savings_pipeline.py`
- `GET /savings-pipeline`
- `GET /savings-pipeline/{id}`
- `PATCH /savings-pipeline/{id}`
- `POST /savings-pipeline/{id}/assign`
- `POST /savings-pipeline/{id}/create-ticket`
- `POST /savings-pipeline/{id}/measure-realized`

### Models
- `owners`
- `savings_opportunities`
- `savings_stage_history`
- `external_tickets`
- `realized_savings_measurements`

## Frontend design
### Pages/components
- extend `Opportunities` workspace
- add `frontend/src/pages/SavingsPipelinePage.tsx`
- add `frontend/src/components/Savings/SavingsBoard.tsx`
- add `frontend/src/components/Savings/RealizedSavingsPanel.tsx`

## UX requirements
- use WF-06
- show stage totals by dollars, not just counts
- show owner, linked ticket, predicted savings, realized savings, confidence
- realized savings measurement must explain caveats such as traffic or seasonal changes

## Deployment and infra changes
- secure integration configs for Jira/Slack/ServiceNow
- periodic remeasurement jobs
- metrics for percent actioned and realized-savings lag

## Tests
- stage transition tests
- external ticket mapping tests
- realized savings measurement tests
- UI board movement and totals tests

## Acceptance criteria
- every opportunity can be assigned and linked to external workflow
- realized savings can be measured after implementation
- executive views separate in-flight from realized savings

## Copilot prompts
### UI/UX prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-007 frontend only. Build the Savings Pipeline board using WF-06, with stage columns, dollar totals, owner visibility, ticket links, realized savings panels, and confidence/caveat messaging.`

### Backend prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-007 backend only. Add ownership mapping, ticketing integration abstractions, savings pipeline stages, and realized savings measurement APIs. Reuse existing opportunities data where practical and preserve audit trails.`

### Deployment prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement infrastructure and config changes for feature F-007 including integration secrets, scheduled realized-savings remeasurement, and metrics for action rates and value realization.`

### Test prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement tests for feature F-007 covering stage transitions, ticket linking, realized savings calculations, and frontend pipeline board behavior.`

---

# F-008 Commitment autopilot

## Why this exists
After waste cleanup, commitments become one of the biggest CFO levers.

## Scope
- RI/SP/CUD coverage and utilization planning
- renewal and expiry views
- laddered recommendations
- approval-based purchase workflow
- ESR reporting

## Backend design
### Services
- `backend/services/commitment_strategy_service.py`
- `backend/services/esr_service.py`
- `backend/services/commitment_recommendation_service.py`

### APIs
- `backend/api/commitments.py`
- recommendations
- scenario simulation
- coverage/utilization
- expiry
- approval workflow endpoints

## UX requirements
- focus on finance safety and approval
- show downside risk and upside opportunity
- show ESR prominently

## Tests
- scenario simulation
- ESR calculation
- renewal workflows

## Acceptance criteria
- customer can simulate commitment strategies and see ESR impact
- approval required before any purchase recommendation is actioned

## Copilot prompts
### UI/UX prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-008 frontend only. Build commitment strategy views that emphasize utilization, expiry, ESR, scenario comparison, and safe approval workflows.`

### Backend prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-008 backend only. Add commitment strategy simulation, ESR calculation, renewal planning, and approval-based workflow APIs for RI/SP/CUD recommendations.`

### Deployment prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement infra/config changes for feature F-008, including scheduled commitment refresh jobs and metrics for utilization, expiry, and ESR.`

### Test prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement tests for feature F-008 covering scenario modeling, ESR, expiry handling, and approval workflows.`

---

# F-009 Policy engine: guidelines and guardrails

## Why this exists
Governance turns one-off savings into sustained savings.

## Scope
- policy types: guideline and guardrail
- org, team, product, and environment scope
- scheduled evaluation
- template library
- simulation and progressive rollout

## Backend design
### Services
- `backend/services/policy_engine_service.py`
- `backend/services/policy_simulation_service.py`
- `backend/services/policy_job_runner.py`

### APIs
- `backend/api/policies.py`
- CRUD
- simulate
- publish
- rollout
- violations list

## Frontend design
- `frontend/src/pages/PolicyStudioPage.tsx`
- `frontend/src/components/Policies/PolicyEditor.tsx`
- `frontend/src/components/Policies/SimulationPanel.tsx`

## UX requirements
- use WF-07
- strong distinction between guideline and guardrail
- default templates for tag compliance, idle shutdown, budget notification
- progressive rollout and simulation mandatory before guardrail activation

## Deployment and infra changes
- job runner for policy evaluation
- action allowlists
- metrics for violations, actions, suppressed actions

## Tests
- policy schedule tests
- simulation accuracy tests
- rollout tests
- allowlist safety tests

## Acceptance criteria
- guidelines can notify and open tickets
- guardrails require policy approval and safe action allowlists
- users can simulate historical impact before enabling

## Copilot prompts
### UI/UX prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-009 frontend only. Build Policy Studio using WF-07 with template library, simulation, guideline vs guardrail choice, rollout controls, and finance-safe warning language.`

### Backend prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-009 backend only. Add a policy engine with versioned policies, simulation, rollout states, violations, and safe job execution with explicit allowlists.`

### Deployment prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement infra/config changes for feature F-009 including policy evaluation jobs, metrics, and settings for allowlists and progressive rollout.`

### Test prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement tests for feature F-009 covering simulations, scheduling, rollouts, violation generation, and frontend policy configuration flows.`

---

# F-010 Agentic remediation and PR automation

## Why this exists
This is a key differentiation moat versus dashboard-only tools.

## Scope
- generate IaC pull requests for supported opportunity types
- safe one-click actions for non-prod or low-risk resources
- blast-radius summary
- rollback plan
- approval workflow
- auditability

## Backend design
### Services
- `backend/services/remediation_service.py`
- `backend/services/pr_generation_service.py`
- `backend/services/remediation_approval_service.py`

### APIs
- `backend/api/remediation.py`
- generate PR
- preview action
- request approval
- apply approved action
- rollback

## Frontend design
- `frontend/src/pages/RemediationPage.tsx`
- `frontend/src/components/Remediation/ActionPreviewPanel.tsx`
- `frontend/src/components/Remediation/BlastRadiusSummary.tsx`

## UX requirements
- remediation must start with preview, not execution
- show risk, blast radius, estimated savings, rollback steps
- prod resources require stricter approval policies

## Deployment and infra changes
- Git provider credentials and repo mapping
- secure action execution role
- action allowlists and environment gates

## Tests
- PR generation tests
- approval workflow tests
- rollback tests
- non-prod guardrail tests

## Acceptance criteria
- supported opportunities can create reviewable PRs
- unsafe production actions are blocked without approval
- all remediation events are audit logged

## Copilot prompts
### UI/UX prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-010 frontend only. Build remediation preview and approval UI with blast radius, risk, estimated savings, rollback plan, and PR links. Keep the UX conservative and enterprise-safe.`

### Backend prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-010 backend only. Add PR generation, remediation preview, approval workflow, safe apply actions, and rollback APIs. Reuse existing IaC capabilities where helpful and preserve strong auditability.`

### Deployment prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement infra/config changes for feature F-010, including Git credentials wiring, action execution roles, allowlists, environment gates, and operational metrics.`

### Test prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement tests for feature F-010 covering PR generation, approval states, blocked unsafe actions, rollback flows, and frontend remediation previews.`

---

# F-011 Kubernetes cost module

## Why this exists
Kubernetes is one of the most requested and most painful cost domains at scale.

## Scope
- multi-cluster views
- namespace/workload/label allocation
- request-vs-usage efficiency
- idle and GPU waste
- feed K8s costs into the common allocation engine

## Backend design
### Services
- `backend/services/k8s_cost_ingestion_service.py`
- `backend/services/k8s_allocation_service.py`
- `backend/services/k8s_efficiency_service.py`

### APIs
- `backend/api/kubernetes_costs.py`
- clusters
- namespaces
- workloads
- efficiency insights
- waste recommendations

## Frontend design
- `frontend/src/pages/KubernetesCostPage.tsx`
- `frontend/src/components/Kubernetes/ClusterEfficiencyDashboard.tsx`

## UX requirements
- use WF-08
- optimize for engineering teams, not finance only
- connect K8s cost waste to tickets and remediation

## Deployment and infra changes
- cluster agent deployment docs and manifests
- ingestion pipeline for agent telemetry
- metrics for cluster freshness and agent health

## Tests
- ingestion tests
- namespace/workload allocation tests
- efficiency calculations
- UI rendering and cluster filters

## Acceptance criteria
- K8s costs can be shown by cluster, namespace, workload, label
- cluster efficiency dashboard highlights actionable waste

## Copilot prompts
### UI/UX prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-011 frontend only. Build the Kubernetes Efficiency page using WF-08 with cluster selectors, request-vs-usage insights, waste panels, and action buttons for tickets and PRs.`

### Backend prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-011 backend only. Add Kubernetes cost ingestion, namespace/workload allocation, request-vs-usage analysis, idle and GPU waste detection, and APIs that feed the common allocation engine.`

### Deployment prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement deployment changes for feature F-011 including cluster agent manifests, ingestion configuration, secrets, metrics, and health checks.`

### Test prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement tests for feature F-011 covering ingestion, allocation, efficiency logic, UI cluster filters, and org-safe visibility.`

---

# F-012 FinOps as code

## Why this exists
Platform teams increasingly expect configuration to be version-controlled.

## Scope
- export/import allocation rules, budgets, policies, anomaly monitors, dashboards
- YAML apply CLI in phase one
- Terraform provider in phase two
- drift visibility between UI and code source of truth

## Backend design
### Services
- `backend/services/config_export_service.py`
- `backend/services/config_apply_service.py`
- `backend/services/drift_detection_service.py`

### APIs
- `backend/api/finops_as_code.py`
- export bundle
- validate bundle
- apply bundle
- drift report

## Frontend design
- show source-of-truth badges inside relevant pages
- drift warning banner
- import/export actions

## Deployment and infra changes
- CLI packaging pipeline
- optional git sync settings

## Tests
- export/import fidelity
- drift detection tests
- YAML validation tests

## Acceptance criteria
- major FinOps resources can be exported, validated, and reapplied
- UI clearly shows whether a resource is UI-managed or code-managed

## Copilot prompts
### UI/UX prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-012 frontend only. Add source-of-truth badges, drift warnings, and import/export entry points across dashboards, policies, budgets, and allocation pages.`

### Backend prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-012 backend only. Add export, validate, apply, and drift APIs for major FinOps configuration objects, with YAML support first and architecture ready for a Terraform provider later.`

### Deployment prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement packaging and deployment changes for feature F-012, including CLI release support, feature flags, and optional git sync configuration.`

### Test prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement tests for feature F-012 covering export/import fidelity, validation failures, drift detection, and UI drift badges.`

---

# F-013 AI cost intelligence

## Why this exists
AI spend is rising quickly and is one of the next lucrative FinOps categories.

## Scope
- track spend for Bedrock and external model APIs
- cost per request, cost per token, cost per workflow
- model-level and team-level allocation
- token anomalies
- cheaper-model recommendations
- AI budget and governance integration

## Backend design
### Services
- `backend/services/ai_cost_ingestion_service.py`
- `backend/services/ai_token_analytics_service.py`
- `backend/services/ai_model_recommendation_service.py`

### APIs
- `backend/api/ai_costs.py`
- spend summaries
- model breakdowns
- token anomalies
- recommendations
- policy hooks

## Frontend design
- `frontend/src/pages/AICostPage.tsx`
- `frontend/src/components/AICost/ModelSpendTable.tsx`
- `frontend/src/components/AICost/TokenAnomalyPanel.tsx`

## UX requirements
- use WF-09
- emphasize efficiency and model fit, not just total spend
- integrate with budgets, policies, anomalies, and allocation

## Deployment and infra changes
- support ingestion from internal logs and external API exports
- secrets and schema for model-provider feeds
- metrics for AI spend freshness and anomaly counts

## Tests
- token analytics
- model cost rollups
- anomaly detection
- UI breakdown rendering

## Acceptance criteria
- AI spend can be broken down by model, team, environment, workflow
- cheaper-model candidates can be surfaced with confidence caveats

## Copilot prompts
### UI/UX prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-013 frontend only. Build the AI Cost Intelligence page using WF-09 with model/team/workflow breakdowns, token anomaly panels, efficiency insights, and action links into budgets and policies.`

### Backend prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-013 backend only. Add AI spend ingestion, token analytics, model-level rollups, anomaly detection, and recommendation APIs for model-cost optimization.`

### Deployment prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement infra/config changes for feature F-013, including ingestion feeds for model provider data, secrets, env vars, and metrics for freshness and anomaly counts.`

### Test prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement tests for feature F-013 covering token analytics, spend rollups, anomaly detection, and frontend AI-cost visualizations.`

---

# F-014 Pricing and contract optimization

## Why this exists
This is a later-stage enterprise differentiator for larger customers and high-spend accounts.

## Scope
- EDP/commitment planning
- discount coverage analysis
- contract utilization
- vendor negotiation pack support
- scenario planning

## Backend design
- pricing scenario service
- contract registry
- discount model service

## UX requirements
- keep this finance-heavy and later-phase
- show scenario comparison and contract expiry risk

## Tests
- scenario calculations
- contract lifecycle handling

## Acceptance criteria
- user can model high-level contract/discount scenarios with auditable assumptions

## Copilot prompts
### UI/UX prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-014 frontend only. Build a finance-oriented pricing and contract optimization workspace with scenario comparison, discount coverage, and expiry risk views.`

### Backend prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-014 backend only. Add contract registry, pricing scenario calculations, discount coverage modeling, and auditable assumptions for enterprise negotiation planning.`

### Deployment prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement any infra/config changes required for feature F-014, including secure contract data handling and metrics.`

### Test prompt
`Read docs/aasmaa-copilot-spec-v1.md and implement tests for feature F-014 covering scenario math, expiry handling, and frontend scenario comparison behavior.`

## 11. Cross-feature dependencies

| Depends On | Needed By | Reason |
|---|---|---|
| F-001 | F-002, F-003, F-005, F-006, F-008, F-011, F-013 | normalized multi-cloud data foundation |
| F-002 | F-003, F-005, F-007, F-009, F-011, F-013 | business mapping and accountability |
| F-003 | F-004 | report generation consumes dashboard/widgets |
| F-006 | F-007 | anomalies should feed ownership workflows |
| F-007 | F-010 | remediation must tie back to owner and realized savings |
| F-009 | F-010, F-012 | policy engine drives guardrails and code-defined governance |

## 12. Metrics and success criteria

### Executive success metrics
- monthly active executive users
- monthly CFO pack delivery success rate
- percentage of monthly reporting automated
- forecast accuracy at org and business-unit level

### FinOps success metrics
- percentage spend allocated
- anomaly mean time to detect
- anomaly mean time to root cause
- percent opportunities actioned
- realized savings per month
- ESR uplift where commitment features are enabled

### Engineering success metrics
- percent remediation items converted into PRs or approved actions
- K8s cost coverage by namespace/workload
- policy compliance rate
- configuration drift detected and resolved

## 13. Definition of done for any feature

A feature is not done unless all of the following are true:

- backend APIs implemented and documented
- frontend UX implemented and role-gated
- migrations created
- audit logging added
- metrics added
- feature flag added
- unit tests added
- integration tests added
- negative-path tests added
- deployment docs or scripts updated
- acceptance criteria met

## 14. Recommended implementation order

### Sprint order
1. F-001
2. F-002
3. F-003
4. F-004
5. F-005
6. F-006
7. F-007
8. F-009
9. F-010
10. F-008
11. F-011
12. F-012
13. F-013
14. F-014

### Why this order
- F-001 and F-002 create the data and accountability foundation.
- F-003 and F-004 close the most visible executive gaps.
- F-005 and F-006 make the system predictive and proactive.
- F-007 proves realized outcomes.
- F-009 and F-010 create an enforcement moat.
- remaining features deepen differentiation.

## 15. Suggested repo location

Save this file at:

`docs/aasmaa-copilot-spec-v1.md`

## 16. Immediate next command for Copilot

Start with:

`Read docs/aasmaa-copilot-spec-v1.md and implement feature F-001 end-to-end.`

Then continue in order.
