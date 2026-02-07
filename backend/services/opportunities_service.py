"""
Opportunities Service

Data access layer for opportunities table operations.
Handles CRUD, filtering, sorting, and aggregations.
"""

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID
from datetime import datetime, timezone
import json
import structlog

from backend.config.settings import get_settings
from backend.utils.sql_constants import build_sql_placeholders, SQL_VALUE_SEPARATOR
from backend.models.opportunities import (
    OpportunityStatus,
    OpportunitySource,
    OpportunityCategory,
    OpportunityFilter,
    OpportunitySort,
    OpportunitySummary,
    OpportunityDetail,
    OpportunityListResponse,
    OpportunitiesStats,
    OpportunityIngestResult,
)

logger = structlog.get_logger(__name__)
settings = get_settings()


class OpportunitiesService:
    """
    Service for managing optimization opportunities.

    Provides:
    - CRUD operations
    - Filtering and sorting
    - Status management
    - Statistics and aggregations
    - Bulk operations
    - Export functionality
    """

    def __init__(self, organization_id: Optional[UUID] = None):
        """Initialize service with optional organization scoping"""
        self.organization_id = organization_id
        self.db_config = {
            'host': settings.postgres_host,
            'port': settings.postgres_port,
            'database': settings.postgres_db,
            'user': settings.postgres_user,
            'password': settings.postgres_password
        }

    def _get_connection(self):
        """Get database connection"""
        return psycopg2.connect(**self.db_config)

    def _validate_ownership(
        self,
        opportunity: Dict[str, Any],
        user_id: Optional[UUID],
        allow_org_admins: bool = True
    ) -> None:
        """
        Validate that the user has permission to access/modify this opportunity.

        Args:
            opportunity: Opportunity data dict
            user_id: User ID to validate (None = admin bypass)
            allow_org_admins: Whether to allow organization admins access

        Raises:
            HTTPException: 403 if user doesn't have permission
        """
        from fastapi import HTTPException

        if not user_id:
            # No user_id provided - skip validation (for system operations)
            return

        created_by = opportunity.get('created_by_user_id')

        # If no creator recorded (legacy data or system-created), allow access
        if not created_by:
            return

        # Convert to UUID for comparison if needed
        if isinstance(created_by, str):
            try:
                from uuid import UUID as UUIDClass
                created_by = UUIDClass(created_by)
            except (ValueError, AttributeError):
                pass

        if isinstance(user_id, str):
            try:
                from uuid import UUID as UUIDClass
                user_id = UUIDClass(user_id)
            except (ValueError, AttributeError):
                pass

        # Allow owner access
        if str(created_by) == str(user_id):
            return

        # If allow_org_admins is True, the organization scoping should handle this
        # For now, deny access since we're implementing per-user ownership
        logger.warning(
            "Unauthorized opportunity access attempt",
            opportunity_id=opportunity.get('id'),
            requesting_user_id=str(user_id),
            owner_user_id=str(created_by)
        )
        raise HTTPException(
            status_code=403,
            detail="Access denied. You can only access opportunities you created."
        )

    def _build_where_clause(
        self,
        filter: Optional[OpportunityFilter],
        params: List[Any]
    ) -> str:
        """Build WHERE clause from filter criteria"""
        conditions = []

        # Organization scoping
        if self.organization_id:
            params.append(str(self.organization_id))
            conditions.append(f"organization_id = %s")

        if not filter:
            return " AND ".join(conditions) if conditions else "1=1"

        # Account IDs
        if filter.account_ids:
            placeholders = build_sql_placeholders(len(filter.account_ids))
            conditions.append(f"account_id IN ({placeholders})")
            params.extend(filter.account_ids)

        # Statuses
        if filter.statuses:
            placeholders = build_sql_placeholders(len(filter.statuses))
            conditions.append(f"status IN ({placeholders})")
            params.extend([s.value for s in filter.statuses])

        # Categories
        if filter.categories:
            placeholders = build_sql_placeholders(len(filter.categories))
            conditions.append(f"category IN ({placeholders})")
            params.extend([c.value for c in filter.categories])

        # Sources
        if filter.sources:
            placeholders = build_sql_placeholders(len(filter.sources))
            conditions.append(f"source IN ({placeholders})")
            params.extend([s.value for s in filter.sources])

        # Services
        if filter.services:
            placeholders = build_sql_placeholders(len(filter.services))
            conditions.append(f"service IN ({placeholders})")
            params.extend(filter.services)

        # Regions
        if filter.regions:
            placeholders = build_sql_placeholders(len(filter.regions))
            conditions.append(f"region IN ({placeholders})")
            params.extend(filter.regions)

        # Savings range
        if filter.min_savings is not None:
            params.append(filter.min_savings)
            conditions.append("estimated_monthly_savings >= %s")

        if filter.max_savings is not None:
            params.append(filter.max_savings)
            conditions.append("estimated_monthly_savings <= %s")

        # Effort levels
        if filter.effort_levels:
            placeholders = build_sql_placeholders(len(filter.effort_levels))
            conditions.append(f"effort_level IN ({placeholders})")
            params.extend([e.value for e in filter.effort_levels])

        # Risk levels
        if filter.risk_levels:
            placeholders = build_sql_placeholders(len(filter.risk_levels))
            conditions.append(f"risk_level IN ({placeholders})")
            params.extend([r.value for r in filter.risk_levels])

        # Tags (any match using JSONB containment)
        if filter.tags:
            tag_conditions = []
            for tag in filter.tags:
                params.append(json.dumps([tag]))
                tag_conditions.append("tags @> %s::jsonb")
            conditions.append(f"({' OR '.join(tag_conditions)})")

        # Full-text search
        if filter.search:
            params.append(filter.search)
            conditions.append(
                "(to_tsvector('english', title) @@ plainto_tsquery('english', %s) OR "
                "to_tsvector('english', description) @@ plainto_tsquery('english', %s))"
            )
            params.append(filter.search)

        # Date filtering
        if filter.first_detected_after:
            params.append(filter.first_detected_after)
            conditions.append("first_detected_at >= %s")

        if filter.first_detected_before:
            params.append(filter.first_detected_before)
            conditions.append("first_detected_at <= %s")

        return " AND ".join(conditions) if conditions else "1=1"

    def _get_order_clause(self, sort: OpportunitySort) -> str:
        """Get ORDER BY clause from sort option"""
        sort_map = {
            OpportunitySort.SAVINGS_DESC: "estimated_monthly_savings DESC NULLS LAST",
            OpportunitySort.SAVINGS_ASC: "estimated_monthly_savings ASC NULLS LAST",
            OpportunitySort.PRIORITY_DESC: "priority_score DESC NULLS LAST",
            OpportunitySort.PRIORITY_ASC: "priority_score ASC NULLS LAST",
            OpportunitySort.FIRST_DETECTED_DESC: "first_detected_at DESC",
            OpportunitySort.FIRST_DETECTED_ASC: "first_detected_at ASC",
            OpportunitySort.LAST_SEEN_DESC: "last_seen_at DESC",
            OpportunitySort.STATUS: "status ASC, priority_score DESC NULLS LAST",
            OpportunitySort.SERVICE: "service ASC, priority_score DESC NULLS LAST",
        }
        return sort_map.get(sort, "estimated_monthly_savings DESC NULLS LAST")

    def list_opportunities(
        self,
        filter: Optional[OpportunityFilter] = None,
        sort: OpportunitySort = OpportunitySort.SAVINGS_DESC,
        page: int = 1,
        page_size: int = 20,
        include_aggregations: bool = True
    ) -> OpportunityListResponse:
        """
        List opportunities with filtering, sorting, and pagination.

        Args:
            filter: Filter criteria
            sort: Sort order
            page: Page number (1-indexed)
            page_size: Items per page
            include_aggregations: Include counts and total savings

        Returns:
            Paginated list response with aggregations
        """
        try:
            conn = self._get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            params = []
            where_clause = self._build_where_clause(filter, params)
            order_clause = self._get_order_clause(sort)

            # Get total count
            count_query = f"SELECT COUNT(*) FROM opportunities WHERE {where_clause}"
            cur.execute(count_query, params)
            total = cur.fetchone()['count']

            # Calculate pagination
            offset = (page - 1) * page_size
            total_pages = (total + page_size - 1) // page_size if total > 0 else 0

            # Get items
            items_query = f"""
                SELECT
                    id, title, service, category, status,
                    estimated_monthly_savings, priority_score,
                    effort_level, risk_level, resource_id, region,
                    first_detected_at, last_seen_at
                FROM opportunities
                WHERE {where_clause}
                ORDER BY {order_clause}
                LIMIT %s OFFSET %s
            """
            cur.execute(items_query, params + [page_size, offset])
            items = [OpportunitySummary(**dict(row)) for row in cur.fetchall()]

            # Get aggregations if requested
            total_monthly_savings = None
            status_counts = None
            category_counts = None
            service_counts = None

            if include_aggregations:
                # Reset params for aggregation queries
                agg_params = []
                agg_where = self._build_where_clause(filter, agg_params)

                # Total savings
                savings_query = f"""
                    SELECT COALESCE(SUM(estimated_monthly_savings), 0) as total
                    FROM opportunities
                    WHERE {agg_where}
                """
                cur.execute(savings_query, agg_params)
                total_monthly_savings = float(cur.fetchone()['total'])

                # Status counts
                agg_params = []
                agg_where = self._build_where_clause(filter, agg_params)
                status_query = f"""
                    SELECT status::text, COUNT(*) as count
                    FROM opportunities
                    WHERE {agg_where}
                    GROUP BY status
                """
                cur.execute(status_query, agg_params)
                status_counts = {row['status']: row['count'] for row in cur.fetchall()}

                # Category counts
                agg_params = []
                agg_where = self._build_where_clause(filter, agg_params)
                category_query = f"""
                    SELECT category::text, COUNT(*) as count
                    FROM opportunities
                    WHERE {agg_where}
                    GROUP BY category
                """
                cur.execute(category_query, agg_params)
                category_counts = {row['category']: row['count'] for row in cur.fetchall()}

                # Service counts
                agg_params = []
                agg_where = self._build_where_clause(filter, agg_params)
                service_query = f"""
                    SELECT service, COUNT(*) as count
                    FROM opportunities
                    WHERE {agg_where}
                    GROUP BY service
                    ORDER BY count DESC
                    LIMIT 10
                """
                cur.execute(service_query, agg_params)
                service_counts = {row['service']: row['count'] for row in cur.fetchall()}

            cur.close()
            conn.close()

            return OpportunityListResponse(
                items=items,
                total=total,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
                has_next=page < total_pages,
                has_prev=page > 1,
                total_monthly_savings=total_monthly_savings,
                status_counts=status_counts,
                category_counts=category_counts,
                service_counts=service_counts
            )

        except Exception as e:
            logger.error(f"Error listing opportunities: {e}", exc_info=True)
            raise

    def get_opportunity(
        self,
        opportunity_id: UUID,
        user_id: Optional[UUID] = None
    ) -> Optional[OpportunityDetail]:
        """
        Get a single opportunity by ID with full details.

        Args:
            opportunity_id: Opportunity UUID
            user_id: Optional user ID for ownership validation

        Returns:
            OpportunityDetail or None if not found

        Raises:
            HTTPException: 403 if user doesn't have permission
        """
        try:
            conn = self._get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            query = """
                SELECT *
                FROM opportunities
                WHERE id = %s
            """

            params = [str(opportunity_id)]

            # Add organization scoping if set
            if self.organization_id:
                query += " AND organization_id = %s"
                params.append(str(self.organization_id))

            cur.execute(query, params)
            row = cur.fetchone()

            cur.close()
            conn.close()

            if not row:
                return None

            # Validate ownership if user_id provided
            opportunity_dict = dict(row)
            if user_id:
                self._validate_ownership(opportunity_dict, user_id)

            return OpportunityDetail(**opportunity_dict)

        except Exception as e:
            logger.error(f"Error getting opportunity {opportunity_id}: {e}", exc_info=True)
            raise

    def create_opportunity(self, data: Dict[str, Any]) -> OpportunityDetail:
        """
        Create a new opportunity.

        Args:
            data: Opportunity data dictionary

        Returns:
            Created opportunity
        """
        try:
            conn = self._get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Add organization_id if set
            if self.organization_id and 'organization_id' not in data:
                data['organization_id'] = str(self.organization_id)

            # Build insert query dynamically
            columns = list(data.keys())
            placeholders = ['%s'] * len(columns)
            values = []

            for col in columns:
                val = data[col]
                if isinstance(val, (dict, list)):
                    val = json.dumps(val)
                values.append(val)

            query = f"""
                INSERT INTO opportunities ({', '.join(columns)})
                VALUES ({', '.join(placeholders)})
                RETURNING *
            """

            cur.execute(query, values)
            row = cur.fetchone()
            conn.commit()

            cur.close()
            conn.close()

            logger.info(f"Created opportunity: {row['id']}")
            return OpportunityDetail(**dict(row))

        except Exception as e:
            logger.error(f"Error creating opportunity: {e}", exc_info=True)
            raise

    def update_opportunity(
        self,
        opportunity_id: UUID,
        data: Dict[str, Any],
        user_id: Optional[UUID] = None
    ) -> Optional[OpportunityDetail]:
        """
        Update an opportunity.

        Args:
            opportunity_id: Opportunity UUID
            data: Fields to update
            user_id: Optional user ID for ownership validation

        Returns:
            Updated opportunity or None if not found

        Raises:
            HTTPException: 403 if user doesn't have permission
        """
        try:
            conn = self._get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # First, fetch the opportunity to validate ownership
            fetch_query = "SELECT * FROM opportunities WHERE id = %s"
            fetch_params = [str(opportunity_id)]

            if self.organization_id:
                fetch_query += " AND organization_id = %s"
                fetch_params.append(str(self.organization_id))

            cur.execute(fetch_query, fetch_params)
            existing = cur.fetchone()

            if not existing:
                cur.close()
                conn.close()
                return None

            # Validate ownership if user_id provided
            if user_id:
                self._validate_ownership(dict(existing), user_id)

            # Build update query
            set_clauses = []
            values = []

            for col, val in data.items():
                set_clauses.append(f"{col} = %s")
                if isinstance(val, (dict, list)):
                    val = json.dumps(val)
                values.append(val)

            values.append(str(opportunity_id))

            query = f"""
                UPDATE opportunities
                SET {', '.join(set_clauses)}
                WHERE id = %s
            """

            # Add organization scoping
            if self.organization_id:
                query += " AND organization_id = %s"
                values.append(str(self.organization_id))

            query += " RETURNING *"

            cur.execute(query, values)
            row = cur.fetchone()
            conn.commit()

            cur.close()
            conn.close()

            if not row:
                return None

            logger.info(
                "Updated opportunity",
                opportunity_id=str(opportunity_id),
                user_id=str(user_id) if user_id else None
            )
            return OpportunityDetail(**dict(row))

        except Exception as e:
            logger.error(f"Error updating opportunity {opportunity_id}: {e}", exc_info=True)
            raise

    def update_status(
        self,
        opportunity_id: UUID,
        status: OpportunityStatus,
        reason: Optional[str] = None,
        changed_by: Optional[str] = None,
        user_id: Optional[UUID] = None
    ) -> Optional[OpportunityDetail]:
        """
        Update opportunity status.

        Args:
            opportunity_id: Opportunity UUID
            status: New status
            reason: Reason for status change
            changed_by: User who changed the status
            user_id: Optional user ID for ownership validation

        Returns:
            Updated opportunity or None if not found
        """
        return self.update_opportunity(
            opportunity_id,
            {
                'status': status.value,
                'status_reason': reason,
                'status_changed_by': changed_by,
                'status_changed_at': datetime.now(timezone.utc)
            },
            user_id=user_id
        )

    def bulk_update_status(
        self,
        opportunity_ids: List[UUID],
        status: OpportunityStatus,
        reason: Optional[str] = None,
        changed_by: Optional[str] = None
    ) -> Tuple[int, int, List[Dict[str, str]]]:
        """
        Update status for multiple opportunities.

        Args:
            opportunity_ids: List of opportunity UUIDs
            status: New status
            reason: Reason for status change
            changed_by: User who changed the status

        Returns:
            Tuple of (updated_count, failed_count, errors)
        """
        try:
            conn = self._get_connection()
            cur = conn.cursor()

            id_strings = [str(oid) for oid in opportunity_ids]
            placeholders = build_sql_placeholders(len(id_strings))

            query = f"""
                UPDATE opportunities
                SET status = %s,
                    status_reason = %s,
                    status_changed_by = %s,
                    status_changed_at = CURRENT_TIMESTAMP
                WHERE id IN ({placeholders})
            """

            params = [status.value, reason, changed_by] + id_strings

            # Add organization scoping
            if self.organization_id:
                query += " AND organization_id = %s"
                params.append(str(self.organization_id))

            cur.execute(query, params)
            updated = cur.rowcount
            conn.commit()

            cur.close()
            conn.close()

            failed = len(opportunity_ids) - updated
            errors = []

            if failed > 0:
                errors.append({"error": f"{failed} opportunities not found or not accessible"})

            logger.info(f"Bulk status update: {updated} updated, {failed} failed")
            return updated, failed, errors

        except Exception as e:
            logger.error(f"Error in bulk status update: {e}", exc_info=True)
            raise

    def delete_opportunity(
        self,
        opportunity_id: UUID,
        user_id: Optional[UUID] = None
    ) -> bool:
        """
        Delete an opportunity.

        Args:
            opportunity_id: Opportunity UUID
            user_id: Optional user ID for ownership validation

        Returns:
            True if deleted, False if not found

        Raises:
            HTTPException: 403 if user doesn't have permission
        """
        try:
            conn = self._get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # First, fetch the opportunity to validate ownership
            fetch_query = "SELECT * FROM opportunities WHERE id = %s"
            fetch_params = [str(opportunity_id)]

            if self.organization_id:
                fetch_query += " AND organization_id = %s"
                fetch_params.append(str(self.organization_id))

            cur.execute(fetch_query, fetch_params)
            existing = cur.fetchone()

            if not existing:
                cur.close()
                conn.close()
                return False

            # Validate ownership if user_id provided
            if user_id:
                self._validate_ownership(dict(existing), user_id)

            # Perform deletion
            delete_query = "DELETE FROM opportunities WHERE id = %s"
            delete_params = [str(opportunity_id)]

            if self.organization_id:
                delete_query += " AND organization_id = %s"
                delete_params.append(str(self.organization_id))

            cur.execute(delete_query, delete_params)
            deleted = cur.rowcount > 0
            conn.commit()

            cur.close()
            conn.close()

            if deleted:
                logger.info(
                    "Deleted opportunity",
                    opportunity_id=str(opportunity_id),
                    user_id=str(user_id) if user_id else None
                )
            return deleted

        except Exception as e:
            logger.error(f"Error deleting opportunity {opportunity_id}: {e}", exc_info=True)
            raise

    def get_stats(self) -> OpportunitiesStats:
        """
        Get statistics summary for opportunities.

        Returns:
            Statistics with counts and aggregations
        """
        try:
            conn = self._get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            org_filter = ""
            params = []

            if self.organization_id:
                org_filter = "WHERE organization_id = %s"
                params = [str(self.organization_id)]

            # Total counts
            cur.execute(f"""
                SELECT
                    COUNT(*) as total_opportunities,
                    COUNT(*) FILTER (WHERE status = 'open') as open_opportunities,
                    COALESCE(SUM(estimated_monthly_savings) FILTER (WHERE status = 'open'), 0) as potential_monthly,
                    COALESCE(SUM(estimated_monthly_savings) FILTER (WHERE status = 'implemented'), 0) as implemented_monthly
                FROM opportunities
                {org_filter}
            """, params)
            totals = cur.fetchone()

            # Status counts
            cur.execute(f"""
                SELECT status::text, COUNT(*) as count
                FROM opportunities
                {org_filter}
                GROUP BY status
            """, params)
            by_status = {row['status']: row['count'] for row in cur.fetchall()}

            # Category counts
            cur.execute(f"""
                SELECT category::text, COUNT(*) as count
                FROM opportunities
                {org_filter}
                GROUP BY category
            """, params)
            by_category = {row['category']: row['count'] for row in cur.fetchall()}

            # Service counts
            cur.execute(f"""
                SELECT service, COUNT(*) as count
                FROM opportunities
                {org_filter}
                GROUP BY service
                ORDER BY count DESC
            """, params)
            by_service = {row['service']: row['count'] for row in cur.fetchall()}

            # Source counts
            cur.execute(f"""
                SELECT source::text, COUNT(*) as count
                FROM opportunities
                {org_filter}
                GROUP BY source
            """, params)
            by_source = {row['source']: row['count'] for row in cur.fetchall()}

            # Effort level counts
            cur.execute(f"""
                SELECT effort_level, COUNT(*) as count
                FROM opportunities
                {org_filter}
                GROUP BY effort_level
            """, params)
            by_effort = {row['effort_level'] or 'unknown': row['count'] for row in cur.fetchall()}

            # Top opportunities
            cur.execute(f"""
                SELECT
                    id, title, service, category, status,
                    estimated_monthly_savings, priority_score,
                    effort_level, risk_level, resource_id, region,
                    first_detected_at, last_seen_at
                FROM opportunities
                {org_filter + ' AND ' if org_filter else 'WHERE '} status = 'open'
                ORDER BY estimated_monthly_savings DESC NULLS LAST
                LIMIT 10
            """, params)
            top_opportunities = [OpportunitySummary(**dict(row)) for row in cur.fetchall()]

            cur.close()
            conn.close()

            return OpportunitiesStats(
                total_opportunities=totals['total_opportunities'],
                open_opportunities=totals['open_opportunities'],
                total_potential_monthly_savings=float(totals['potential_monthly']),
                total_potential_annual_savings=float(totals['potential_monthly']) * 12,
                implemented_savings_monthly=float(totals['implemented_monthly']),
                implemented_savings_annual=float(totals['implemented_monthly']) * 12,
                by_status=by_status,
                by_category=by_category,
                by_service=by_service,
                by_source=by_source,
                by_effort_level=by_effort,
                top_opportunities=top_opportunities
            )

        except Exception as e:
            logger.error(f"Error getting stats: {e}", exc_info=True)
            raise

    def ingest_signals(self, signals: List[Dict[str, Any]]) -> OpportunityIngestResult:
        """
        Ingest optimization signals and create/update opportunities.

        Args:
            signals: List of signal dictionaries from AWS APIs

        Returns:
            Ingest result with counts
        """
        try:
            conn = self._get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            new_count = 0
            updated_count = 0
            skipped_count = 0
            error_count = 0
            error_details = []

            for signal in signals:
                try:
                    source_id = signal.get('source_id')

                    if source_id:
                        # Check for existing opportunity by source_id
                        cur.execute(
                            "SELECT id FROM opportunities WHERE source_id = %s",
                            [source_id]
                        )
                        existing = cur.fetchone()

                        if existing:
                            # Update last_seen_at
                            cur.execute(
                                "UPDATE opportunities SET last_seen_at = CURRENT_TIMESTAMP WHERE id = %s",
                                [existing['id']]
                            )
                            updated_count += 1
                            continue

                    # Create new opportunity
                    columns = list(signal.keys())
                    values = []

                    for col in columns:
                        val = signal[col]
                        if isinstance(val, (dict, list)):
                            val = json.dumps(val)
                        values.append(val)

                    placeholders = ['%s'] * len(columns)

                    query = f"""
                        INSERT INTO opportunities ({', '.join(columns)})
                        VALUES ({', '.join(placeholders)})
                        ON CONFLICT (source, source_id) WHERE source_id IS NOT NULL
                        DO UPDATE SET last_seen_at = CURRENT_TIMESTAMP
                        RETURNING id, (xmax = 0) as is_new
                    """

                    cur.execute(query, values)
                    result = cur.fetchone()

                    if result and result.get('is_new'):
                        new_count += 1
                    else:
                        updated_count += 1

                except Exception as e:
                    error_count += 1
                    error_details.append(str(e))
                    logger.warning(f"Error ingesting signal: {e}")

            conn.commit()
            cur.close()
            conn.close()

            logger.info(
                f"Ingested signals: {new_count} new, {updated_count} updated, "
                f"{skipped_count} skipped, {error_count} errors"
            )

            return OpportunityIngestResult(
                total_signals=len(signals),
                new_opportunities=new_count,
                updated_opportunities=updated_count,
                skipped=skipped_count,
                errors=error_count,
                error_details=error_details if error_details else None,
                ingested_at=datetime.now(timezone.utc)
            )

        except Exception as e:
            logger.error(f"Error ingesting signals: {e}", exc_info=True)
            raise

    def export_opportunities(
        self,
        filter: Optional[OpportunityFilter] = None,
        include_evidence: bool = False,
        include_steps: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Export opportunities for download.

        Args:
            filter: Filter criteria
            include_evidence: Include detailed evidence data
            include_steps: Include implementation steps

        Returns:
            List of opportunity dictionaries for export
        """
        try:
            conn = self._get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            params = []
            where_clause = self._build_where_clause(filter, params)

            # Select columns based on export options
            columns = [
                "id", "account_id", "title", "description", "category", "source",
                "service", "resource_id", "resource_name", "resource_type", "region",
                "estimated_monthly_savings", "estimated_annual_savings",
                "savings_percentage", "current_monthly_cost", "projected_monthly_cost",
                "effort_level", "risk_level", "status", "status_reason",
                "priority_score", "confidence_score", "tags",
                "first_detected_at", "last_seen_at", "deep_link"
            ]

            if include_steps:
                columns.append("implementation_steps")

            if include_evidence:
                columns.extend(["evidence", "api_trace", "cur_validation_sql"])

            query = f"""
                SELECT {', '.join(columns)}
                FROM opportunities
                WHERE {where_clause}
                ORDER BY estimated_monthly_savings DESC NULLS LAST
            """

            cur.execute(query, params)
            rows = cur.fetchall()

            cur.close()
            conn.close()

            return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Error exporting opportunities: {e}", exc_info=True)
            raise


# Singleton instance
_opportunities_service = None


def get_opportunities_service(
    organization_id: Optional[UUID] = None
) -> OpportunitiesService:
    """Get or create the opportunities service instance"""
    global _opportunities_service

    if _opportunities_service is None or _opportunities_service.organization_id != organization_id:
        _opportunities_service = OpportunitiesService(organization_id=organization_id)

    return _opportunities_service
