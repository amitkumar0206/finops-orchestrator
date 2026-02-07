# RBAC System Documentation

## Overview

The FinOps platform uses a **configuration-based Role-Based Access Control (RBAC) system** for managing user permissions. This system replaces hardcoded role checks with a flexible, maintainable configuration file that defines roles, permissions, and hierarchies.

## Key Features

- ✅ **Configuration-Driven**: Roles and permissions defined in YAML
- ✅ **No Hardcoded Roles**: All role checks use the RBAC service
- ✅ **Wildcard Support**: Flexible permission matching with wildcards
- ✅ **Resource-Action-Scope Model**: Fine-grained permission control
- ✅ **Role Hierarchy**: Owners can manage admins, admins can manage members
- ✅ **Easy to Extend**: Add new roles/permissions without code changes
- ✅ **Backward Compatible**: Existing functionality preserved

---

## Architecture

### Permission Format

Permissions follow the pattern: **`resource:action:scope`**

- **resource**: The resource type (saved_views, organization, account, query, etc.)
- **action**: The action being performed (read, write, delete, manage, execute)
- **scope**: The scope of the permission (all, own, shared, assigned, org)

**Examples:**
- `saved_views:read:all` - Read all saved views in organization
- `saved_views:write:own` - Write only own saved views
- `organization:manage_members` - Manage organization members
- `query:execute:all` - Execute queries on all AWS accounts

### Wildcard Permissions

The system supports wildcards for flexible permission matching:

- `*:*:*` - All permissions (system admin)
- `saved_views:*:all` - Any action on saved views with scope "all"
- `saved_views:read:*` - Read action on saved views with any scope

---

## Configuration File

Location: **`config/rbac_config.yaml`**

### Structure

```yaml
# Permission Definitions
permissions:
  saved_views:read:all:
    description: "Read all saved views in organization"
    resource: "saved_views"
    action: "read"
    scope: "all"

# Role Definitions
roles:
  owner:
    display_name: "Organization Owner"
    description: "Full control over organization and all resources"
    priority: 100
    permissions:
      - saved_views:read:all
      - saved_views:write:all
      - organization:manage_members
      # ... more permissions

# Role Hierarchy
role_hierarchy:
  can_assign_roles:
    owner:
      - owner
      - admin
      - member
      - viewer
```

---

## Standard Roles

### System Admin
- **Priority**: 1000
- **Permissions**: `*:*:*` (all permissions)
- **Use Case**: Platform administrators with full access
- **Special**: Bypasses all organization-level checks

### Owner
- **Priority**: 100
- **Permissions**: Full control over their organization
- **Can Assign**: owner, admin, member, viewer
- **Key Permissions**:
  - All saved views operations
  - Manage organization members
  - Change member roles
  - Delete organization
  - All AWS accounts access
  - All query execution

### Admin
- **Priority**: 90
- **Permissions**: Most privileges except changing owner
- **Can Assign**: member, viewer
- **Key Permissions**:
  - All saved views operations
  - Manage organization members (but cannot change roles)
  - All AWS accounts access
  - All query execution

### Member
- **Priority**: 50
- **Permissions**: Standard user access
- **Can Assign**: None
- **Key Permissions**:
  - Read shared saved views
  - Write/delete own saved views
  - View organization members
  - Access assigned AWS accounts only
  - Execute queries on assigned accounts only

### Viewer
- **Priority**: 10
- **Permissions**: Read-only access
- **Can Assign**: None
- **Key Permissions**:
  - Read shared saved views
  - View organization members
  - Access assigned AWS accounts (read-only)
  - View analytics

---

## Usage

### In Service Code

```python
from backend.services.rbac_permission_service import get_rbac_service

# Get RBAC service instance
rbac = get_rbac_service()

# Check if user has permission
if rbac.has_permission(context, "saved_views:read:all"):
    # User can read all saved views
    pass

# Check ownership-based permission
resource_owner_id = str(view['created_by'])
if rbac.has_permission(context, "saved_views:write:own", resource_owner_id):
    # User can write this view (they own it)
    pass

# Require permission (raises ValueError if denied)
rbac.require_permission(
    context,
    "organization:manage_members",
    error_message="Admin access required to add members"
)

# Check if user has privileged role (owner/admin)
if rbac.is_privileged_role(context):
    # User is owner or admin
    pass

# Check if user can assign a role
if rbac.can_manage_role(context, "admin"):
    # User can assign admin role
    pass
```

### Convenience Functions

```python
from backend.services.rbac_permission_service import check_permission

# Quick permission check
if check_permission(context, "saved_views:read:all"):
    # User has permission
    pass
```

---

## Migration from Hardcoded Checks

### Before (Hardcoded)

```python
# ❌ OLD: Hardcoded role check
if context.is_admin or context.org_role in ('owner', 'admin'):
    # Allow access
    pass
else:
    raise ValueError("Admin access required")
```

### After (RBAC)

```python
# ✅ NEW: Configuration-based check
rbac = get_rbac_service()
rbac.require_permission(
    context,
    "organization:manage_members",
    error_message="Admin access required"
)
```

---

## Adding New Roles

1. **Edit Configuration** (`config/rbac_config.yaml`):

```yaml
roles:
  analyst:
    display_name: "Data Analyst"
    description: "Can analyze cost data but not modify"
    priority: 40
    permissions:
      - saved_views:read:shared
      - analytics:read:all
      - query:execute:assigned
```

2. **No Code Changes Required!** The RBAC service loads the configuration automatically.

3. **Assign Role** to users through the UI or API.

---

## Adding New Permissions

1. **Define Permission** in `config/rbac_config.yaml`:

```yaml
permissions:
  budget:create:
    description: "Create new budgets"
    resource: "budget"
    action: "create"
    scope: "org"
```

2. **Add to Roles**:

```yaml
roles:
  owner:
    permissions:
      - budget:create
      # ... other permissions
```

3. **Use in Code**:

```python
rbac.require_permission(context, "budget:create")
```

---

## Testing

### Unit Tests

Location: `tests/unit/services/test_rbac_permission_service.py`

**Coverage:**
- 43 comprehensive tests
- All standard roles tested
- Permission inheritance verified
- Wildcard matching validated
- Role hierarchy enforcement tested

**Run Tests:**
```bash
pytest tests/unit/services/test_rbac_permission_service.py -v
```

### Integration Tests

Existing service tests automatically cover RBAC integration since the refactored services use the RBAC system.

---

## Best Practices

### 1. Always Use RBAC Service

❌ **Don't:**
```python
if context.org_role == 'owner':
    # Do something
```

✅ **Do:**
```python
rbac = get_rbac_service()
if rbac.has_permission(context, "resource:action:scope"):
    # Do something
```

### 2. Use Descriptive Permissions

✅ **Good:**
```python
rbac.require_permission(context, "organization:manage_members")
```

❌ **Bad:**
```python
rbac.require_permission(context, "org:do:stuff")
```

### 3. Provide Clear Error Messages

```python
rbac.require_permission(
    context,
    "organization:delete",
    error_message="Only organization owners can delete the organization"
)
```

### 4. Check Ownership for "own" Scope

```python
# For permissions with :own scope, pass the resource owner ID
resource_owner = str(resource['created_by'])
if rbac.has_permission(context, "saved_views:write:own", resource_owner):
    # User can modify this resource
```

### 5. Use is_privileged_role() for Common Checks

```python
# Instead of checking multiple permissions
if rbac.is_privileged_role(context):
    # Quick check for owner/admin
    pass
```

---

## Runtime Configuration Updates

The RBAC service supports runtime configuration reloading:

```python
rbac = get_rbac_service()
rbac.reload_config()
```

This allows updating roles and permissions without restarting the application (use with caution in production).

---

## Security Considerations

### 1. Configuration File Protection

- **Restrict Access**: Only administrators should modify `rbac_config.yaml`
- **Version Control**: Track changes in git
- **Review Changes**: Require code review for permission changes

### 2. System Admin Usage

- **Limited Use**: System admin role should be used sparingly
- **Audit Logging**: All system admin actions should be logged
- **Principle of Least Privilege**: Use org-level roles when possible

### 3. Permission Granularity

- **Fine-Grained**: Define specific permissions rather than broad wildcards
- **Resource-Specific**: Create resource-specific permissions
- **Scope-Aware**: Use appropriate scope (all, own, shared)

### 4. Role Assignment

- **Owner Control**: Only owners can change roles
- **Hierarchy Enforcement**: Admins cannot escalate to owner
- **Audit Trail**: Log all role changes

---

## Troubleshooting

### Permission Denied Errors

1. **Check User's Role**:
```python
print(f"User role: {context.org_role}")
```

2. **Check User's Permissions**:
```python
rbac = get_rbac_service()
permissions = rbac.get_user_permissions(context)
print(f"User permissions: {permissions}")
```

3. **Verify Configuration**:
```python
role_info = rbac.get_role_info(context.org_role)
print(f"Role config: {role_info}")
```

### Configuration Not Loading

1. **Check File Path**:
   - Default: `config/rbac_config.yaml`
   - Environment variable: `RBAC_CONFIG_PATH`

2. **Validate YAML Syntax**:
   ```bash
   python -c "import yaml; yaml.safe_load(open('config/rbac_config.yaml'))"
   ```

3. **Check Logs**:
   - Look for "rbac_config_loaded" or "rbac_config_not_found" messages

### Performance Issues

The RBAC service uses `@lru_cache` for permission lookups. If you update roles at runtime, clear the cache:

```python
rbac._get_role_permissions.cache_clear()
```

---

## Migration Checklist

- [x] Create `config/rbac_config.yaml`
- [x] Create `backend/services/rbac_permission_service.py`
- [x] Add PyYAML to requirements.txt
- [x] Refactor `backend/services/saved_views_service.py`
- [x] Refactor `backend/services/organization_service.py`
- [x] Refactor `backend/services/athena_query_service.py`
- [x] Refactor `backend/services/text_to_sql_service.py`
- [x] Refactor `backend/services/request_context.py`
- [x] Create unit tests (`test_rbac_permission_service.py`)
- [x] Verify all existing tests pass
- [x] Create documentation

---

## Future Enhancements

### Planned Features

1. **Database-Backed Roles**: Store custom roles in database
2. **Dynamic Permissions**: Allow runtime permission creation
3. **Permission Inheritance**: Role-based inheritance
4. **Audit Logging Integration**: Log all permission checks
5. **UI for Role Management**: Admin interface for managing roles
6. **Permission Caching**: Redis-based permission cache
7. **Multi-Tenancy**: Organization-specific role overrides

### Extensibility

The RBAC system is designed to be extended. See the source code docstrings for details on:
- Creating custom permission matchers
- Implementing permission transformers
- Adding permission decorators
- Building permission middleware

---

## References

- Configuration: `config/rbac_config.yaml`
- Service Code: `backend/services/rbac_permission_service.py`
- Tests: `tests/unit/services/test_rbac_permission_service.py`
- Migration Examples: See git history for refactoring patterns

---

**Last Updated**: 2026-02-07
**Version**: 1.0.0
**Maintainer**: Platform Team
