"""
RBAC (Role-Based Access Control) Service
Handles permissions, role management, and access control
"""

from typing import List, Dict, Any, Optional, Callable
from functools import wraps
import structlog
from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.services.database import DatabaseService
from backend.utils.pii_masking import mask_email, hash_identifier

logger = structlog.get_logger(__name__)
security = HTTPBearer()


class RBACService:
    """Service for role-based access control"""
    
    def __init__(self):
        self.db = DatabaseService()
        # Cache for permissions (would use Redis in production)
        self._permission_cache = {}
    
    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email"""
        query = """
            SELECT id, email, full_name, is_active, is_admin
            FROM users
            WHERE email = $1 AND is_active = true
        """
        return await self.db.fetch_one(query, email)
    
    async def get_or_create_user(
        self,
        email: str,
        full_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get or create user"""
        user = await self.get_user_by_email(email)
        
        if not user:
            query = """
                INSERT INTO users (email, full_name)
                VALUES ($1, $2)
                RETURNING id, email, full_name, is_active, is_admin
            """
            user = await self.db.execute(query, email, full_name)
            logger.info("user_created", user=hash_identifier(email, "user"))
        
        return user
    
    async def get_user_permissions(self, user_id: str) -> List[str]:
        """Get all permissions for a user"""
        
        # Check cache first
        cache_key = f"permissions:{user_id}"
        if cache_key in self._permission_cache:
            return self._permission_cache[cache_key]
        
        # Query user's roles and aggregate permissions
        query = """
            SELECT DISTINCT unnest(r.permissions) as permission
            FROM users u
            JOIN user_roles ur ON u.id = ur.user_id
            JOIN roles r ON ur.role_id = r.id
            WHERE u.id = $1
            AND u.is_active = true
            AND (ur.expires_at IS NULL OR ur.expires_at > NOW())
        """
        
        results = await self.db.fetch_all(query, user_id)
        permissions = [row['permission'] for row in results]
        
        # Cache permissions
        self._permission_cache[cache_key] = permissions
        
        return permissions
    
    async def check_permission(
        self,
        user_id: str,
        permission: str
    ) -> bool:
        """Check if user has a specific permission"""
        
        # Check if user is admin (has all permissions)
        query = "SELECT is_admin FROM users WHERE id = $1"
        user = await self.db.fetch_one(query, user_id)
        
        if user and user['is_admin']:
            return True
        
        # Check specific permission
        permissions = await self.get_user_permissions(user_id)
        return permission in permissions
    
    async def assign_role_to_user(
        self,
        user_id: str,
        role_name: str,
        granted_by: str,
        expires_at: Optional[str] = None
    ):
        """Assign a role to a user"""
        
        # Get role ID
        role_query = "SELECT id FROM roles WHERE name = $1"
        role = await self.db.fetch_one(role_query, role_name)
        
        if not role:
            raise ValueError(f"Role {role_name} not found")
        
        query = """
            INSERT INTO user_roles (user_id, role_id, granted_by, expires_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, role_id) DO UPDATE
            SET granted_by = $3, expires_at = $4, granted_at = NOW()
        """
        
        await self.db.execute(query, user_id, role['id'], granted_by, expires_at)
        
        # Invalidate cache
        cache_key = f"permissions:{user_id}"
        if cache_key in self._permission_cache:
            del self._permission_cache[cache_key]
        
        logger.info(
            "role_assigned",
            user_id=hash_identifier(user_id, "user"),
            role=role_name,
            granted_by=hash_identifier(granted_by, "user")
        )
    
    async def create_role(
        self,
        name: str,
        permissions: List[str],
        description: Optional[str] = None
    ):
        """Create a new role"""
        query = """
            INSERT INTO roles (name, description, permissions)
            VALUES ($1, $2, $3)
            RETURNING id, name
        """
        return await self.db.execute(query, name, description, permissions)
    
    async def update_role_permissions(
        self,
        role_name: str,
        permissions: List[str]
    ):
        """Update permissions for a role"""
        query = """
            UPDATE roles
            SET permissions = $1, updated_at = NOW()
            WHERE name = $2 AND is_system_role = false
            RETURNING id
        """
        result = await self.db.execute(query, permissions, role_name)
        
        if not result:
            raise ValueError(f"Role {role_name} not found or is a system role")
        
        # Clear all permission caches (would use Redis SCAN in production)
        self._permission_cache.clear()
        
        logger.info("role_permissions_updated", role=role_name)


# Global RBAC service instance
rbac_service = RBACService()


def require_permission(permission: str):
    """Decorator to require a specific permission"""
    
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, request: Request = None, **kwargs):
            # Extract user from authenticated request state (set by AuthenticationMiddleware)
            auth_user = getattr(request.state, 'auth_user', None)

            if not auth_user or not auth_user.is_authenticated:
                raise HTTPException(status_code=401, detail="Not authenticated")

            user_email = auth_user.email
            user = await rbac_service.get_user_by_email(user_email)
            
            if not user:
                raise HTTPException(status_code=403, detail="User not found")
            
            # Check permission
            has_permission = await rbac_service.check_permission(
                user['id'],
                permission
            )
            
            if not has_permission:
                logger.warning(
                    "permission_denied",
                    user=hash_identifier(user_email, "user"),
                    permission=permission
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission denied: {permission}"
                )
            
            # Call the actual function
            return await func(*args, request=request, **kwargs)
        
        return wrapper
    return decorator


def require_any_permission(*permissions: str):
    """Decorator to require any of the specified permissions"""

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, request: Request = None, **kwargs):
            # Extract user from authenticated request state (set by AuthenticationMiddleware)
            auth_user = getattr(request.state, 'auth_user', None)

            if not auth_user or not auth_user.is_authenticated:
                raise HTTPException(status_code=401, detail="Not authenticated")

            user_email = auth_user.email
            user = await rbac_service.get_user_by_email(user_email)
            
            if not user:
                raise HTTPException(status_code=403, detail="User not found")
            
            # Check if user has any of the required permissions
            user_permissions = await rbac_service.get_user_permissions(user['id'])
            
            has_any = any(p in user_permissions for p in permissions)
            
            if not has_any and not user['is_admin']:
                logger.warning(
                    "permission_denied",
                    user=hash_identifier(user_email, "user"),
                    required_permissions=permissions
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Requires one of: {', '.join(permissions)}"
                )
            
            return await func(*args, request=request, **kwargs)
        
        return wrapper
    return decorator


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """Dependency to get current authenticated user from JWT token"""

    # User is authenticated by AuthenticationMiddleware which validates JWT
    auth_user = getattr(request.state, 'auth_user', None)

    if not auth_user or not auth_user.is_authenticated:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_email = auth_user.email
    user = await rbac_service.get_or_create_user(user_email)
    
    if not user or not user['is_active']:
        raise HTTPException(status_code=403, detail="User inactive or not found")
    
    # Update last login
    await rbac_service.db.execute(
        "UPDATE users SET last_login_at = NOW(), last_login_ip = $1 WHERE id = $2",
        request.client.host,
        user['id']
    )
    
    return user
