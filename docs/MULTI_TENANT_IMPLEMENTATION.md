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

## Future Enhancements

1. **SSO Integration**: SAML/OIDC for enterprise auth
2. **View Templates**: Pre-built view configurations
3. **Scheduled Reports**: Views for automated reports
4. **Cost Allocation Tags**: Tag-based scoping
5. **Cross-Org Sharing**: Share views between organizations
