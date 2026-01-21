# Multi-Tenant Support Implementation Summary

## Overview

This document summarizes the implementation of multi-tenant support for the FinOps AI Cost Intelligence Platform. The implementation enables organizations to manage users, accounts, and saved views while ensuring data isolation through account-level scoping.

## Implementation Date
January 21, 2026

---

## Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │ ScopeIndicator  │  │ SavedViewsList  │  │ SavedViewEditor │ │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘ │
└───────────┼────────────────────┼────────────────────┼───────────┘
            │                    │                    │
            ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                      API Layer (FastAPI)                         │
│  ┌──────────┐  ┌──────────────┐  ┌───────┐  ┌────────────────┐ │
│  │ /scope/* │  │ /views/*     │  │/orgs/*│  │ /chat (scoped) │ │
│  └────┬─────┘  └──────┬───────┘  └───┬───┘  └───────┬────────┘ │
└───────┼───────────────┼──────────────┼──────────────┼───────────┘
        │               │              │              │
        ▼               ▼              ▼              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Account Scoping Middleware                      │
│  - Extracts user from X-User-Email header                       │
│  - Loads organization and saved view context                    │
│  - Attaches RequestContext to request.state                     │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Service Layer                               │
│  ┌───────────────┐  ┌──────────────┐  ┌─────────────────────┐  │
│  │ Organization  │  │ SavedViews   │  │ RequestContext      │  │
│  │ Service       │  │ Service      │  │ (Dataclass)         │  │
│  └───────────────┘  └──────────────┘  └─────────────────────┘  │
│                                                                  │
│  ┌───────────────┐  ┌──────────────┐  ┌─────────────────────┐  │
│  │ Text-to-SQL   │  │ Athena Query │  │ Audit Log Service   │  │
│  │ (with scoping)│  │ (with scoping│  │ (scope-aware)       │  │
│  └───────────────┘  └──────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Database Layer                              │
│  ┌──────────────┐  ┌───────────────────┐  ┌─────────────────┐  │
│  │ organizations│  │organization_members│  │ saved_views     │  │
│  └──────────────┘  └───────────────────┘  └─────────────────┘  │
│  ┌──────────────┐  ┌───────────────────┐  ┌─────────────────┐  │
│  │user_active_  │  │ aws_accounts      │  │ audit_logs      │  │
│  │views         │  │ (tenant_org_id)   │  │ (scope_context) │  │
│  └──────────────┘  └───────────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Database Schema

### New Tables

#### 1. organizations
Core tenant table for multi-organization support.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| name | VARCHAR(255) | Organization name |
| slug | VARCHAR(100) | URL-friendly identifier (unique) |
| subscription_tier | VARCHAR(50) | 'free', 'standard', 'enterprise' |
| settings | JSONB | Organization settings |
| max_users | INT | Maximum allowed users (default: 50) |
| max_accounts | INT | Maximum AWS accounts (default: 100) |
| saved_view_default_expiration_days | INT | Default view expiration (NULL = no expiration) |
| is_active | BOOLEAN | Soft delete flag |
| created_at | TIMESTAMPTZ | Creation timestamp |
| updated_at | TIMESTAMPTZ | Last update timestamp |

#### 2. organization_members
User-to-organization mapping with roles.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| organization_id | UUID | FK to organizations |
| user_id | UUID | FK to users |
| role | VARCHAR(50) | 'owner', 'admin', 'member' |
| joined_at | TIMESTAMPTZ | Join timestamp |
| invited_by | UUID | FK to users (who invited) |

**Constraints:** Unique (organization_id, user_id)

#### 3. saved_views
User-configurable query scopes.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| organization_id | UUID | FK to organizations |
| name | VARCHAR(255) | View name |
| description | TEXT | Optional description |
| created_by | UUID | FK to users |
| account_ids | UUID[] | Array of aws_accounts.id |
| default_time_range | JSONB | Default time range filter |
| filters | JSONB | Additional filters |
| is_default | BOOLEAN | Organization default view |
| is_personal | BOOLEAN | Personal view (only creator sees) |
| shared_with_users | UUID[] | Users with access |
| shared_with_roles | UUID[] | Roles with access |
| expires_at | TIMESTAMPTZ | Expiration timestamp |
| is_active | BOOLEAN | Soft delete flag |
| created_at | TIMESTAMPTZ | Creation timestamp |
| updated_at | TIMESTAMPTZ | Last update timestamp |

**Constraints:** Unique (organization_id, name)

#### 4. user_active_views
Tracks which saved view each user has selected.

| Column | Type | Description |
|--------|------|-------------|
| user_id | UUID | PK, FK to users |
| saved_view_id | UUID | FK to saved_views (nullable) |
| updated_at | TIMESTAMPTZ | Last update timestamp |

### Modified Tables

#### aws_accounts
- Renamed `organization_id` to `aws_organization_id` (AWS Organization ID)
- Added `tenant_org_id` (UUID, FK to organizations) for multi-tenant linking

#### users
- Added `default_organization_id` (UUID, FK to organizations)

#### audit_logs
- Added `organization_id` (UUID, FK to organizations)
- Added `saved_view_id` (UUID, FK to saved_views)
- Added `scope_context` (JSONB) for detailed scope info

#### conversation_threads
- Added `organization_id` (UUID, FK to organizations)
- Added `saved_view_id` (UUID, FK to saved_views)

---

## API Endpoints

### Saved Views API (`/api/v1/views`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/views` | Create a new saved view |
| GET | `/views` | List all accessible views |
| GET | `/views/active` | Get user's active view |
| PUT | `/views/active/{id}` | Set active view |
| DELETE | `/views/active` | Clear active view |
| GET | `/views/{id}` | Get view details |
| PUT | `/views/{id}` | Update a view |
| DELETE | `/views/{id}` | Delete a view |

### Organizations API (`/api/v1/organizations`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/organizations` | List user's organizations |
| GET | `/organizations/current` | Get current organization |
| PUT | `/organizations/current/{id}` | Switch organization |
| GET | `/organizations/{id}` | Get organization details |
| GET | `/organizations/current/members` | List org members |
| POST | `/organizations/current/members` | Add member (admin) |
| PUT | `/organizations/current/members/{id}/role` | Update role (owner) |
| DELETE | `/organizations/current/members/{id}` | Remove member (admin) |

### Scope API (`/api/v1/scope`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/scope/current` | Get effective scope |
| GET | `/scope/accounts` | List allowed accounts |

### Opportunities API (`/api/v1/opportunities`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/opportunities` | List opportunities (filterable, paginated) |
| GET | `/opportunities/{id}` | Get opportunity details with evidence |
| PATCH | `/opportunities/{id}/status` | Update opportunity status |
| POST | `/opportunities/bulk-status` | Bulk update opportunity statuses |
| POST | `/opportunities/ingest` | Trigger AWS signals ingestion |
| POST | `/opportunities/export` | Export opportunities (CSV/JSON) |
| GET | `/opportunities/stats` | Get aggregated stats for dashboard |

**Query Parameters for List:**
- `category`: Filter by category (rightsizing, idle_resources, etc.)
- `service`: Filter by AWS service (EC2, RDS, S3, etc.)
- `status`: Filter by status (open, accepted, dismissed)
- `account_id`: Filter by AWS account ID
- `min_savings`: Filter by minimum estimated savings
- `max_savings`: Filter by maximum estimated savings
- `sort`: Sort field (savings_desc, savings_asc, created_desc, etc.)
- `page`, `page_size`: Pagination

**Note:** All opportunities endpoints respect organization scoping and account filters from saved views.

---

## Backend Services

### RequestContext (`services/request_context.py`)

Dataclass containing request-scoped context:

```python
@dataclass
class RequestContext:
    user_id: UUID
    user_email: str
    is_admin: bool
    organization_id: Optional[UUID]
    organization_name: Optional[str]
    organization_info: Optional[OrganizationInfo]
    allowed_account_ids: List[str]  # AWS 12-digit account IDs
    active_saved_view: Optional[SavedViewInfo]
    effective_time_range: Optional[Dict[str, Any]]
    effective_filters: Optional[Dict[str, Any]]
    org_role: str  # 'owner', 'admin', 'member'
```

Key methods:
- `has_account_access(account_id)` - Check if user can access an account
- `filter_accounts(account_ids)` - Filter list to allowed accounts
- `get_account_filter_sql()` - Generate SQL WHERE clause for filtering
- `to_scope_dict()` - Convert to API response format
- `to_audit_context()` - Convert to audit log format

### AccountScopingMiddleware (`middleware/account_scoping.py`)

Middleware that:
1. Extracts user email from `X-User-Email` header
2. Loads user from database
3. Loads user's organization and membership
4. Loads active saved view
5. Computes allowed account IDs
6. Attaches `RequestContext` to `request.state.context`

Skip paths: `/health`, `/metrics`, `/docs`, `/`

### SavedViewsService (`services/saved_views_service.py`)

Methods:
- `create_saved_view()` - Create new view with account selection
- `update_saved_view()` - Update view properties
- `delete_saved_view()` - Soft delete a view
- `list_saved_views()` - List accessible views (default + personal + shared)
- `get_saved_view()` - Get view by ID
- `get_active_view()` - Get user's current active view
- `set_active_view()` - Set/change active view
- `cleanup_expired_views()` - Background job for expiration

### OrganizationService (`services/organization_service.py`)

Methods:
- `create_organization()` - Create org with owner
- `get_user_organizations()` - List user's orgs
- `get_organization()` - Get org by ID
- `get_current_organization()` - Get from context
- `switch_organization()` - Change default org
- `add_member()` - Add user to org
- `remove_member()` - Remove user from org
- `update_member_role()` - Change member role
- `list_members()` - List org members

---

## Account Scoping Implementation

### Defense-in-Depth Approach

Three levels of protection ensure users can only access their allowed accounts:

#### Level 1: LLM Prompt Injection
When generating SQL, the allowed accounts are injected into the prompt:
```
**CRITICAL - Account Scoping:**
The user only has access to: 123456789012, 234567890123
You MUST include: AND line_item_usage_account_id IN ('123456789012', '234567890123')
```

#### Level 2: Post-Processing Validation
After SQL generation, the query is validated and modified if needed:
```python
sql_query, was_modified = self._enforce_account_filter(sql_query, allowed_account_ids)
```

#### Level 3: Execution-Time Enforcement
Before Athena execution, final validation occurs:
```python
is_valid, error = self._validate_account_scope(sql_query, allowed_account_ids)
if not is_valid:
    return {"status": "denied", "error": error}
```

### Account Filter Pattern
```sql
WHERE line_item_usage_account_id IN ('123456789012', '234567890123', ...)
```

---

## Frontend Components

### ScopeIndicator (`components/Scope/ScopeIndicator.tsx`)

Header component displaying:
- Organization name (chip)
- Active view name with dropdown selector
- Account count
- Expiration warning (if applicable)

Features:
- Click to open view selector dropdown
- Shows all accessible views (default, personal, shared)
- Real-time view switching with refresh

### SavedViewsList (`components/SavedViews/SavedViewsList.tsx`)

List component for managing saved views:
- Shows all accessible views with metadata
- Edit/Delete actions
- View type badges (Default, Personal, Shared)
- Expiration status
- Creator information

### SavedViewEditor (`components/SavedViews/SavedViewEditor.tsx`)

Create/Edit form with:
- Name and description fields
- Multi-select account picker
- Time range preset selector
- Expiration date picker
- Personal/Default toggle

---

## Audit Logging Enhancements

New audit log events:

| Event | Description |
|-------|-------------|
| `saved_view_created` | New view created |
| `saved_view_updated` | View modified |
| `saved_view_deleted` | View deleted |
| `saved_view_expired` | View expired (cleanup) |
| `active_view_changed` | User switched views |
| `data_exported` | Data exported with scope info |
| `query_executed_scoped` | Query with account scoping |
| `scope_violation_attempt` | Unauthorized account access attempt |

All events include `scope_context` JSONB with:
- Organization ID
- Saved view ID
- Allowed account count
- User role

---

## File Changes Summary

### New Files Created

| File | Purpose |
|------|---------|
| `backend/alembic/versions/010_create_organizations.py` | Organizations schema migration |
| `backend/alembic/versions/011_link_organizations.py` | Link existing tables migration |
| `backend/middleware/__init__.py` | Middleware package |
| `backend/middleware/account_scoping.py` | Account scoping middleware |
| `backend/services/request_context.py` | Request context dataclass |
| `backend/services/saved_views_service.py` | Saved views CRUD |
| `backend/services/organization_service.py` | Organization management |
| `backend/api/saved_views.py` | Saved views API |
| `backend/api/organizations.py` | Organizations API |
| `backend/api/scope.py` | Scope info API |
| `frontend/src/components/Scope/ScopeIndicator.tsx` | Scope header component |
| `frontend/src/components/Scope/index.ts` | Scope exports |
| `frontend/src/components/SavedViews/SavedViewsList.tsx` | Views list component |
| `frontend/src/components/SavedViews/SavedViewEditor.tsx` | Views editor component |
| `frontend/src/components/SavedViews/index.ts` | SavedViews exports |

### Modified Files

| File | Changes |
|------|---------|
| `backend/main.py` | Added middleware and routers |
| `backend/api/chat.py` | Added scope context to responses |
| `backend/services/text_to_sql_service.py` | Added scoped SQL generation |
| `backend/services/athena_query_service.py` | Added scoped query execution |
| `backend/services/audit_log_service.py` | Added scope-aware logging |
| `frontend/src/App.tsx` | Added ScopeIndicator to header |
| `frontend/src/components/Chat/ChatInterface.tsx` | Added scope display in responses |

---

## Usage Examples

### Creating an Organization
```python
from backend.services.organization_service import organization_service

org = await organization_service.create_organization(
    name="ACME Corp",
    owner_user_id=user_id,
    subscription_tier="enterprise",
    max_accounts=200
)
```

### Creating a Saved View
```python
from backend.services.saved_views_service import saved_views_service

view = await saved_views_service.create_saved_view(
    context=request_context,
    name="Production Only",
    account_ids=[prod_account_uuid],
    description="Only production AWS accounts",
    is_default=False,
    is_personal=False
)
```

### Using Scoped SQL Generation
```python
from backend.services.text_to_sql_service import text_to_sql_service

sql, metadata = await text_to_sql_service.generate_sql_with_scoping(
    user_query="Show me my EC2 costs",
    context=request_context,
    conversation_history=history
)
# SQL will include: AND line_item_usage_account_id IN ('allowed_accounts')
```

---

## Testing Recommendations

1. **Unit Tests**: Test each service method in isolation
2. **Integration Tests**: Test API endpoints with mock database
3. **Security Tests**: Verify account scoping enforcement
4. **UI Tests**: Test component rendering and interactions

---

## Migration Notes

- No automatic user migration required
- Organizations created fresh by admins
- Users and accounts linked manually
- Existing data remains accessible to admins

---

## AWS Data Infrastructure

### S3 Bucket Structure for Multi-Account CUR Data

The Cost and Usage Report (CUR) data from multiple AWS accounts is stored in S3 with the following structure:

```
s3://finops-intelligence-platform-data-{management-account-id}/
├── cur/
│   └── finops-cost-report/
│       └── finops-cost-report/
│           ├── year=2024/
│           │   ├── month=1/
│           │   │   ├── finops-cost-report-00001.snappy.parquet
│           │   │   ├── finops-cost-report-00002.snappy.parquet
│           │   │   └── ...
│           │   ├── month=2/
│           │   └── ...
│           └── year=2025/
│               └── ...
│
├── athena-results/
│   └── query-results/
│       └── {query-execution-id}.csv
│
└── metadata/
    └── cost-report-Manifest.json
```

#### Key Fields for Multi-Tenant Filtering

Each CUR parquet file contains data from ALL linked accounts in the AWS Organization. The critical field for multi-tenant filtering is:

| Field | Description | Example |
|-------|-------------|---------|
| `line_item_usage_account_id` | 12-digit AWS account ID where usage occurred | `123456789012` |
| `bill_payer_account_id` | Management/payer account ID | `999888777666` |
| `line_item_usage_start_date` | Usage period start | `2024-01-01T00:00:00Z` |
| `line_item_product_code` | AWS service code | `AmazonEC2` |
| `line_item_unblended_cost` | Cost before discounts | `12.50` |

#### Multi-Account Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        AWS Organization                                   │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐         │
│  │ Account A       │  │ Account B       │  │ Account C       │         │
│  │ 123456789012    │  │ 234567890123    │  │ 345678901234    │         │
│  │ (Production)    │  │ (Staging)       │  │ (Development)   │         │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘         │
│           │                    │                    │                   │
│           ▼                    ▼                    ▼                   │
│  ┌──────────────────────────────────────────────────────────────┐      │
│  │              Management Account (999888777666)                │      │
│  │                        CUR Export                             │      │
│  │   - Consolidates ALL account usage                           │      │
│  │   - Exports to S3 daily/hourly                               │      │
│  └──────────────────────────────────────────────────────────────┘      │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                              S3 Bucket                                     │
│  s3://finops-intelligence-platform-data-999888777666/cur/                 │
│                                                                            │
│  Each Parquet file contains rows for ALL accounts:                        │
│  ┌────────────────────────────┬──────────────┬─────────┬────────────┐    │
│  │ line_item_usage_account_id │ product_code │ cost    │ date       │    │
│  ├────────────────────────────┼──────────────┼─────────┼────────────┤    │
│  │ 123456789012               │ AmazonEC2    │ 1500.00 │ 2024-01-01 │    │
│  │ 234567890123               │ AmazonS3     │ 250.00  │ 2024-01-01 │    │
│  │ 345678901234               │ AmazonRDS    │ 800.00  │ 2024-01-01 │    │
│  │ 123456789012               │ AmazonS3     │ 100.00  │ 2024-01-01 │    │
│  └────────────────────────────┴──────────────┴─────────┴────────────┘    │
└───────────────────────────────────────────────────────────────────────────┘
```

---

### AWS Glue Integration

#### Glue Crawler Configuration

The Glue Crawler automatically discovers CUR data schema and creates/updates the table:

```yaml
Crawler Name: finops-cur-crawler
Database: cost_usage_db
S3 Target: s3://finops-intelligence-platform-data-{account}/cur/finops-cost-report/finops-cost-report/
Schedule: Daily at 6:00 AM UTC
Table Prefix: cur_
Partition Keys:
  - year (string)
  - month (string)
```

#### Glue Table Schema (cur_data)

```sql
CREATE EXTERNAL TABLE cost_usage_db.cur_data (
  -- Identity columns
  identity_line_item_id STRING,
  identity_time_interval STRING,

  -- Bill columns
  bill_invoice_id STRING,
  bill_billing_entity STRING,
  bill_bill_type STRING,
  bill_payer_account_id STRING,      -- Management account
  bill_billing_period_start_date TIMESTAMP,
  bill_billing_period_end_date TIMESTAMP,

  -- Line item columns (KEY FOR MULTI-TENANT)
  line_item_usage_account_id STRING,  -- << CRITICAL: Account being billed
  line_item_line_item_type STRING,
  line_item_usage_start_date TIMESTAMP,
  line_item_usage_end_date TIMESTAMP,
  line_item_product_code STRING,
  line_item_usage_type STRING,
  line_item_operation STRING,
  line_item_availability_zone STRING,
  line_item_resource_id STRING,
  line_item_usage_amount DOUBLE,
  line_item_normalization_factor DOUBLE,
  line_item_normalized_usage_amount DOUBLE,
  line_item_currency_code STRING,
  line_item_unblended_rate STRING,
  line_item_unblended_cost DOUBLE,
  line_item_blended_rate STRING,
  line_item_blended_cost DOUBLE,
  line_item_line_item_description STRING,

  -- Product columns
  product_product_name STRING,
  product_product_family STRING,
  product_region STRING,
  product_instance_type STRING,
  product_instance_family STRING,
  product_operating_system STRING,
  product_tenancy STRING,
  product_database_engine STRING,

  -- Pricing columns
  pricing_term STRING,
  pricing_unit STRING,

  -- Reservation columns
  reservation_reservation_a_r_n STRING,
  reservation_effective_cost DOUBLE,
  reservation_unused_quantity DOUBLE,
  reservation_unused_normalized_unit_quantity DOUBLE,

  -- Savings Plan columns
  savings_plan_savings_plan_a_r_n STRING,
  savings_plan_savings_plan_rate DOUBLE,
  savings_plan_savings_plan_effective_cost DOUBLE,

  -- Resource tags (user-defined)
  resource_tags_user_environment STRING,
  resource_tags_user_project STRING,
  resource_tags_user_cost_center STRING,
  resource_tags_user_team STRING

  -- ... additional tag columns as needed
)
PARTITIONED BY (year STRING, month STRING)
ROW FORMAT SERDE 'org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe'
STORED AS PARQUET
LOCATION 's3://finops-intelligence-platform-data-{account}/cur/finops-cost-report/finops-cost-report/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
```

#### Partition Management

After crawler runs, repair partitions:
```sql
MSCK REPAIR TABLE cost_usage_db.cur_data;
```

Or add partitions manually:
```sql
ALTER TABLE cost_usage_db.cur_data ADD
  PARTITION (year='2024', month='1')
  LOCATION 's3://finops-intelligence-platform-data-{account}/cur/.../year=2024/month=1/';
```

---

### Athena Query Execution with Multi-Tenant Scoping

#### How Account Scoping Works in Athena

When a user queries cost data, the platform enforces account-level isolation through SQL filtering:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        User Query Flow                                   │
│                                                                          │
│  User: "Show me EC2 costs for last month"                               │
│  User's Allowed Accounts: ['123456789012', '234567890123']              │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  1. Text-to-SQL Generation                                      │    │
│  │     LLM Prompt includes:                                        │    │
│  │     "CRITICAL: Filter by line_item_usage_account_id IN          │    │
│  │      ('123456789012', '234567890123')"                          │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                              │                                          │
│                              ▼                                          │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  2. Post-Processing Validation                                  │    │
│  │     - Check if account filter exists in SQL                     │    │
│  │     - Inject filter if missing                                  │    │
│  │     - Validate no unauthorized accounts                         │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                              │                                          │
│                              ▼                                          │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  3. Final SQL Sent to Athena                                    │    │
│  │                                                                  │    │
│  │  SELECT                                                          │    │
│  │    line_item_product_code,                                       │    │
│  │    SUM(line_item_unblended_cost) AS total_cost                  │    │
│  │  FROM cost_usage_db.cur_data                                    │    │
│  │  WHERE year = '2024' AND month = '12'                           │    │
│  │    AND line_item_product_code = 'AmazonEC2'                     │    │
│  │    AND line_item_usage_account_id IN                            │    │
│  │        ('123456789012', '234567890123')  << ENFORCED            │    │
│  │  GROUP BY line_item_product_code                                │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                              │                                          │
│                              ▼                                          │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  4. Athena Executes Query                                       │    │
│  │     - Scans only partitions needed (year/month)                 │    │
│  │     - Filters rows by account at storage level                  │    │
│  │     - Returns only authorized data                              │    │
│  └────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
```

#### Example Scoped Queries

**User in Organization A** (accounts: 123456789012, 234567890123):
```sql
-- Total cost by service
SELECT
  line_item_product_code AS service,
  SUM(line_item_unblended_cost) AS cost
FROM cost_usage_db.cur_data
WHERE year = '2024' AND month = '12'
  AND line_item_usage_account_id IN ('123456789012', '234567890123')
GROUP BY line_item_product_code
ORDER BY cost DESC;
```

**User in Organization B** (accounts: 345678901234):
```sql
-- Same query structure, different account filter
SELECT
  line_item_product_code AS service,
  SUM(line_item_unblended_cost) AS cost
FROM cost_usage_db.cur_data
WHERE year = '2024' AND month = '12'
  AND line_item_usage_account_id IN ('345678901234')
GROUP BY line_item_product_code
ORDER BY cost DESC;
```

#### Athena Workgroup Configuration

```yaml
Workgroup: finops-workgroup
Settings:
  Output Location: s3://finops-intelligence-platform-data-{account}/athena-results/
  Enforce Workgroup Configuration: true
  Data Scanned Limit: 10 GB per query
  Query Timeout: 30 minutes
  Encryption: SSE-S3
```

#### Query Performance Optimization

1. **Partition Pruning**: Always include `year` and `month` in WHERE clause
2. **Column Projection**: Select only needed columns (Parquet is columnar)
3. **Account Filter Early**: Place account filter early in WHERE for predicate pushdown

```sql
-- Optimized query pattern
SELECT columns_needed
FROM cost_usage_db.cur_data
WHERE
  year = '2024'                                           -- Partition prune
  AND month = '12'                                        -- Partition prune
  AND line_item_usage_account_id IN ('123456789012')     -- Early filter
  AND line_item_product_code = 'AmazonEC2'               -- Additional filter
```

---

### Security Considerations

#### Account ID Validation

All account IDs are validated before SQL inclusion to prevent injection:

```python
# From request_context.py
import re
validated_ids = []
for acc in self.allowed_account_ids:
    if re.match(r'^[0-9]{12}$', str(acc)):
        validated_ids.append(f"'{acc}'")
    else:
        logger.warning("invalid_account_id_skipped", account_id=str(acc)[:20])
```

#### IAM Permissions for Athena

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "athena:StartQueryExecution",
        "athena:GetQueryExecution",
        "athena:GetQueryResults",
        "athena:StopQueryExecution"
      ],
      "Resource": "arn:aws:athena:*:*:workgroup/finops-workgroup"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::finops-intelligence-platform-data-*",
        "arn:aws:s3:::finops-intelligence-platform-data-*/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "glue:GetTable",
        "glue:GetPartitions",
        "glue:GetDatabase"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## Future Enhancements

1. **SSO Integration**: SAML/OIDC for enterprise auth
2. **View Templates**: Pre-built view configurations
3. **Scheduled Reports**: Views for automated reports
4. **Cost Allocation Tags**: Tag-based scoping
5. **Cross-Org Sharing**: Share views between organizations
6. **Federated Queries**: Query across multiple AWS Organizations
