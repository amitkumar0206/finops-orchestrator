"""
Optimization Engine Service
Provides service-specific cost optimization recommendations with confidence scoring.
"""

import structlog
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from backend.config.settings import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


class OptimizationEngine:
    """
    Generates service-specific cost optimization recommendations.
    
    Features:
    - Service-specific recommendation templates
    - Confidence scoring based on historical validation
    - Estimated savings calculations
    - Recommendation tracking and validation
    """
    
    def __init__(self):
        """Initialize optimization engine with database connection."""
        self.db_config = {
            'host': settings.postgres_host,
            'port': settings.postgres_port,
            'database': settings.postgres_db,
            'user': settings.postgres_user,
            'password': settings.postgres_password
        }
        self._initialize_templates()
    
    def _get_connection(self):
        """Get database connection."""
        return psycopg2.connect(**self.db_config)
    
    def _initialize_templates(self):
        """Initialize service-specific recommendation templates if not already in DB."""
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            # Check if templates already exist
            cur.execute("SELECT COUNT(*) FROM optimization_recommendations")
            count = cur.fetchone()[0]
            
            if count == 0:
                logger.warning("No optimization recommendations found in database. Please run seed script.")
                # Note: Templates are now seeded manually via SQL script
                # See: backend/scripts/seed_optimization_recommendations_fixed.sql
            else:
                logger.info(f"Found {count} optimization recommendations in database")
            
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"Could not check templates (table may not exist yet): {e}")
    
    def get_recommendations(
        self,
        service: str,
        current_metrics: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get optimization recommendations for a specific service.
        
        Args:
            service: AWS service name (e.g., EC2, Lambda, CloudWatch)
            current_metrics: Current usage metrics for tailored recommendations
            
        Returns:
            List of recommendation dicts sorted by effort ascending, savings descending
        """
        try:
            conn = self._get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Query recommendations for service
            cur.execute("""
                SELECT 
                    id, service, strategy_id, strategy_name, description,
                    estimated_savings_min_percent, estimated_savings_max_percent,
                    implementation_effort_hours, implementation_difficulty, confidence_score,
                    recommendation_steps, metadata, validation_count,
                    risk_level, tags
                FROM optimization_recommendations
                WHERE service ILIKE %s AND status = 'pending'
                ORDER BY 
                    implementation_effort_hours ASC,
                    estimated_savings_max_percent DESC,
                    confidence_score DESC
            """, (service,))
            
            recommendations = cur.fetchall()
            
            # Convert to list of dicts
            result = []
            for rec in recommendations:
                rec_dict = dict(rec)
                
                # Calculate estimated savings in dollars if current metrics provided
                if current_metrics and 'current_monthly_cost' in current_metrics:
                    current_cost = float(current_metrics['current_monthly_cost'])
                    min_savings = current_cost * (float(rec['estimated_savings_min_percent']) / 100)
                    max_savings = current_cost * (float(rec['estimated_savings_max_percent']) / 100)
                    
                    rec_dict['estimated_monthly_savings_min'] = round(min_savings, 2)
                    rec_dict['estimated_monthly_savings_max'] = round(max_savings, 2)
                
                # Add priority score (higher is better)
                savings_score = (float(rec['estimated_savings_min_percent']) + float(rec['estimated_savings_max_percent'])) / 2
                effort_score = 100 - min(float(rec['implementation_effort_hours']), 100)
                confidence_score = float(rec['confidence_score']) * 100
                
                rec_dict['priority_score'] = round(
                    (savings_score * 0.4) + (effort_score * 0.3) + (confidence_score * 0.3),
                    2
                )
                
                result.append(rec_dict)
            
            cur.close()
            conn.close()
            
            logger.info(f"Retrieved {len(result)} recommendations for {service}")
            return result
            
        except Exception as e:
            logger.error(f"Error getting recommendations: {e}", exc_info=True)
            return []
    
    def get_detailed_recommendations(
        self,
        service: str,
        recommendation_ids: List[str],
        current_metrics: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get detailed breakdown of already-shown recommendations.
        Includes full implementation steps, prerequisites, and risk analysis.
        
        Args:
            service: AWS service name
            recommendation_ids: List of recommendation IDs to get details for
            current_metrics: Current usage metrics for tailored recommendations
            
        Returns:
            List of detailed recommendation dicts with full implementation guidance
        """
        try:
            conn = self._get_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Query specific recommendations by ID
            if recommendation_ids:
                placeholders = ','.join(['%s'] * len(recommendation_ids))
                query = f"""
                    SELECT 
                        id, service, strategy_id, strategy_name, description,
                        estimated_savings_min_percent, estimated_savings_max_percent,
                        implementation_effort_hours, implementation_difficulty, confidence_score,
                        recommendation_steps, metadata, validation_count,
                        risk_level, tags, prerequisites, monitoring_metrics
                    FROM optimization_recommendations
                    WHERE id IN ({placeholders}) AND service ILIKE %s
                    ORDER BY priority_score DESC
                """
                cur.execute(query, tuple(recommendation_ids) + (service,))
            else:
                # Fallback: get top recommendations for service
                cur.execute("""
                    SELECT 
                        id, service, strategy_id, strategy_name, description,
                        estimated_savings_min_percent, estimated_savings_max_percent,
                        implementation_effort_hours, implementation_difficulty, confidence_score,
                        recommendation_steps, metadata, validation_count,
                        risk_level, tags, prerequisites, monitoring_metrics
                    FROM optimization_recommendations
                    WHERE service ILIKE %s AND status = 'pending'
                    ORDER BY priority_score DESC
                    LIMIT 3
                """, (service,))
            
            recommendations = cur.fetchall()
            result = [dict(rec) for rec in recommendations]
            
            cur.close()
            conn.close()
            
            logger.info(f"Retrieved {len(result)} detailed recommendations for {service}")
            return result
            
        except Exception as e:
            logger.error(f"Error getting detailed recommendations: {e}", exc_info=True)
            return []
    
    def validate_recommendation(
        self,
        recommendation_id: str,
        actual_savings_percent: float
    ) -> None:
        """
        Track recommendation effectiveness with actual savings data.
        
        Args:
            recommendation_id: UUID of the recommendation
            actual_savings_percent: Actual savings achieved (percentage)
        """
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            # Update validation count and recalculate confidence score
            cur.execute("""
                UPDATE optimization_recommendations
                SET 
                    validation_count = validation_count + 1,
                    total_actual_savings = COALESCE(total_actual_savings, 0) + %s,
                    confidence_score = (
                        (confidence_score * validation_count + %s / 100.0) / (validation_count + 1)
                    ),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (actual_savings_percent, actual_savings_percent, recommendation_id))
            
            conn.commit()
            cur.close()
            conn.close()
            
            logger.info(f"Validated recommendation {recommendation_id} with {actual_savings_percent}% savings")
            
        except Exception as e:
            logger.error(f"Error validating recommendation: {e}", exc_info=True)
    
    def calculate_confidence_score(
        self,
        service: str,
        strategy: str
    ) -> float:
        """
        Calculate confidence score for a recommendation strategy.
        
        Args:
            service: AWS service name
            strategy: Strategy ID
            
        Returns:
            Confidence score (0.0 to 1.0)
        """
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            cur.execute("""
                SELECT confidence_score, validation_count
                FROM optimization_recommendations
                WHERE service ILIKE %s AND strategy_id = %s
            """, (service, strategy))
            
            result = cur.fetchone()
            cur.close()
            conn.close()
            
            if result:
                return float(result[0])
            else:
                return 0.5  # Default confidence
                
        except Exception as e:
            logger.error(f"Error calculating confidence: {e}", exc_info=True)
            return 0.5
    
    def calculate_estimated_savings(
        self,
        service: str,
        strategy: str,
        current_metrics: Dict[str, Any]
    ) -> Tuple[float, float]:
        """
        Calculate estimated savings in dollars for a specific recommendation.
        
        Args:
            service: AWS service name
            strategy: Strategy ID
            current_metrics: Current usage metrics including 'current_monthly_cost'
            
        Returns:
            Tuple of (min_savings, max_savings) in dollars
        """
        try:
            if 'current_monthly_cost' not in current_metrics:
                return (0.0, 0.0)
            
            conn = self._get_connection()
            cur = conn.cursor()
            
            cur.execute("""
                SELECT estimated_savings_min_percent, estimated_savings_max_percent
                FROM optimization_recommendations
                WHERE service ILIKE %s AND strategy_id = %s
            """, (service, strategy))
            
            result = cur.fetchone()
            cur.close()
            conn.close()
            
            if result:
                current_cost = float(current_metrics['current_monthly_cost'])
                min_percent = float(result[0])
                max_percent = float(result[1])
                
                min_savings = current_cost * (min_percent / 100)
                max_savings = current_cost * (max_percent / 100)
                
                return (round(min_savings, 2), round(max_savings, 2))
            else:
                return (0.0, 0.0)
                
        except Exception as e:
            logger.error(f"Error calculating savings: {e}", exc_info=True)
            return (0.0, 0.0)


# Global instance
optimization_engine = OptimizationEngine()
