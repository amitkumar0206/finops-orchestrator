#!/usr/bin/env python3
"""
Optimization Opportunities Ingestion Script

Fetches optimization recommendations from AWS services:
- Cost Explorer rightsizing recommendations
- Trusted Advisor cost optimization checks
- Compute Optimizer recommendations

Stores results in the opportunities database table.

Usage:
    python opportunities_ingest.py [--dry-run] [--account-ids ID1,ID2]

Environment variables:
    DATABASE_URL: PostgreSQL connection string (required for non-dry-run)
    AWS_REGION: AWS region for API calls (default: us-east-1)
"""

import os
import sys
import json
import argparse
import asyncio
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError


def getenv(name: str, default: str = None) -> str:
    """Get environment variable with optional default."""
    val = os.getenv(name, default)
    if val is None or val == "":
        if default is None:
            raise RuntimeError(f"Missing required env var: {name}")
        return default
    return val


def fetch_cost_explorer_recommendations(ce_client, account_ids: Optional[List[str]] = None) -> List[Dict]:
    """
    Fetch rightsizing recommendations from Cost Explorer.

    Args:
        ce_client: Boto3 Cost Explorer client
        account_ids: Optional list of account IDs to filter

    Returns:
        List of recommendation dictionaries
    """
    recommendations = []

    try:
        kwargs = {
            "Service": "AmazonEC2",
            "PageSize": 100,
        }

        if account_ids:
            kwargs["Filter"] = {
                "And": [
                    {"Dimensions": {"Key": "LINKED_ACCOUNT", "Values": account_ids}}
                ]
            }

        paginator = ce_client.get_paginator("get_rightsizing_recommendation")

        for page in paginator.paginate(**kwargs):
            for rec in page.get("RightsizingRecommendations", []):
                current_instance = rec.get("CurrentInstance", {})
                resource_details = current_instance.get("ResourceDetails", {}).get("EC2ResourceDetails", {})

                monthly_savings = 0.0
                modify_rec = rec.get("ModifyRecommendationDetail", {})
                if modify_rec:
                    target = modify_rec.get("TargetInstances", [{}])[0]
                    savings_currency = target.get("EstimatedMonthlySavings", "0")
                    try:
                        monthly_savings = float(savings_currency)
                    except (ValueError, TypeError):
                        monthly_savings = 0.0

                # Also check terminate recommendations
                terminate_rec = rec.get("TerminateRecommendationDetail", {})
                if terminate_rec:
                    savings_currency = terminate_rec.get("EstimatedMonthlySavings", "0")
                    try:
                        monthly_savings = max(monthly_savings, float(savings_currency))
                    except (ValueError, TypeError):
                        pass

                recommendation = {
                    "source": "cost_explorer",
                    "source_id": rec.get("RightsizingRecommendationId", str(uuid4())),
                    "title": f"Rightsize EC2 Instance {resource_details.get('InstanceId', 'Unknown')}",
                    "description": _build_rightsizing_description(rec),
                    "service": "EC2",
                    "category": "rightsizing",
                    "resource_id": resource_details.get("InstanceId"),
                    "resource_arn": current_instance.get("ResourceId"),
                    "account_id": rec.get("AccountId", current_instance.get("ResourceId", "").split(":")[4] if ":" in current_instance.get("ResourceId", "") else None),
                    "region": resource_details.get("Region"),
                    "estimated_monthly_savings": monthly_savings,
                    "effort_level": "medium",
                    "risk_level": "low",
                    "evidence": {
                        "recommendation_type": rec.get("RightsizingType"),
                        "current_instance_type": resource_details.get("InstanceType"),
                        "recommended_action": "modify" if modify_rec else "terminate",
                        "utilization": current_instance.get("ResourceUtilization", {}),
                    },
                    "action_url": f"https://console.aws.amazon.com/cost-management/home#/rightsizing",
                }

                recommendations.append(recommendation)

    except ClientError as e:
        print(f"Warning: Failed to fetch Cost Explorer recommendations: {e}")
    except Exception as e:
        print(f"Warning: Unexpected error fetching Cost Explorer recommendations: {e}")

    return recommendations


def _build_rightsizing_description(rec: Dict) -> str:
    """Build a human-readable description for rightsizing recommendation."""
    rec_type = rec.get("RightsizingType", "unknown")
    current = rec.get("CurrentInstance", {})
    resource_details = current.get("ResourceDetails", {}).get("EC2ResourceDetails", {})

    instance_id = resource_details.get("InstanceId", "Unknown")
    current_type = resource_details.get("InstanceType", "Unknown")

    if rec_type == "Modify":
        modify = rec.get("ModifyRecommendationDetail", {})
        targets = modify.get("TargetInstances", [])
        if targets:
            target_type = targets[0].get("ResourceDetails", {}).get("EC2ResourceDetails", {}).get("InstanceType", "smaller instance")
            return f"Instance {instance_id} ({current_type}) is underutilized. Consider modifying to {target_type} for cost savings."
    elif rec_type == "Terminate":
        return f"Instance {instance_id} ({current_type}) appears idle and can be terminated for cost savings."

    return f"Instance {instance_id} ({current_type}) has an optimization opportunity."


def fetch_trusted_advisor_checks(support_client) -> List[Dict]:
    """
    Fetch cost optimization checks from Trusted Advisor.

    Args:
        support_client: Boto3 Support client

    Returns:
        List of recommendation dictionaries
    """
    recommendations = []

    # Trusted Advisor cost optimization check IDs
    COST_OPTIMIZATION_CHECKS = {
        "Qch7DwouX1": "Low Utilization Amazon EC2 Instances",
        "hjLMh88uM8": "Idle Load Balancers",
        "DAvU99Dc4C": "Underutilized Amazon EBS Volumes",
        "Z4AUBRNSmz": "Unassociated Elastic IP Addresses",
        "1iG5NDGVre": "Amazon RDS Idle DB Instances",
        "Ti39halfu8": "Underutilized Amazon Redshift Clusters",
        "R365s2Qddf": "Savings Plan",
    }

    try:
        # Get check results for cost optimization checks
        for check_id, check_name in COST_OPTIMIZATION_CHECKS.items():
            try:
                result = support_client.describe_trusted_advisor_check_result(
                    checkId=check_id,
                    language="en"
                )

                check_result = result.get("result", {})
                status = check_result.get("status", "not_available")

                if status in ["warning", "error"]:
                    flagged_resources = check_result.get("flaggedResources", [])

                    for resource in flagged_resources:
                        metadata = resource.get("metadata", [])
                        resource_id = metadata[1] if len(metadata) > 1 else resource.get("resourceId")

                        # Estimate savings from metadata (varies by check type)
                        estimated_savings = _extract_ta_savings(check_id, metadata)

                        recommendation = {
                            "source": "trusted_advisor",
                            "source_id": f"ta-{check_id}-{resource.get('resourceId', uuid4())}",
                            "title": f"{check_name}: {resource_id}",
                            "description": _build_ta_description(check_id, check_name, metadata),
                            "service": _get_service_from_check(check_id),
                            "category": _get_category_from_check(check_id),
                            "resource_id": resource_id,
                            "account_id": metadata[0] if metadata else None,
                            "region": metadata[2] if len(metadata) > 2 else None,
                            "estimated_monthly_savings": estimated_savings,
                            "effort_level": "low",
                            "risk_level": "low",
                            "evidence": {
                                "check_id": check_id,
                                "check_name": check_name,
                                "status": status,
                                "metadata": metadata,
                            },
                            "action_url": f"https://console.aws.amazon.com/trustedadvisor/home#/category/cost-optimizing",
                        }

                        recommendations.append(recommendation)

            except ClientError as e:
                if "SubscriptionRequiredException" in str(e):
                    print(f"Info: Trusted Advisor requires Business/Enterprise Support plan")
                    break
                print(f"Warning: Failed to fetch Trusted Advisor check {check_id}: {e}")

    except Exception as e:
        print(f"Warning: Unexpected error fetching Trusted Advisor recommendations: {e}")

    return recommendations


def _extract_ta_savings(check_id: str, metadata: List) -> float:
    """Extract estimated monthly savings from Trusted Advisor metadata."""
    try:
        # Different checks have savings in different positions
        if check_id == "Qch7DwouX1":  # Low Utilization EC2
            # Metadata format: [region, instance-id, instance-type, monthly-cost, ...]
            if len(metadata) > 3:
                return float(metadata[3].replace("$", "").replace(",", ""))
        elif check_id == "hjLMh88uM8":  # Idle Load Balancers
            if len(metadata) > 4:
                return float(metadata[4].replace("$", "").replace(",", ""))
        elif check_id == "DAvU99Dc4C":  # Underutilized EBS
            if len(metadata) > 5:
                return float(metadata[5].replace("$", "").replace(",", ""))
    except (ValueError, IndexError):
        pass
    return 0.0


def _build_ta_description(check_id: str, check_name: str, metadata: List) -> str:
    """Build description for Trusted Advisor recommendation."""
    resource_id = metadata[1] if len(metadata) > 1 else "Unknown"
    return f"Trusted Advisor identified {resource_id} in the '{check_name}' check. Review and take action to reduce costs."


def _get_service_from_check(check_id: str) -> str:
    """Map Trusted Advisor check ID to AWS service."""
    check_service_map = {
        "Qch7DwouX1": "EC2",
        "hjLMh88uM8": "ELB",
        "DAvU99Dc4C": "EBS",
        "Z4AUBRNSmz": "EC2",  # Elastic IP
        "1iG5NDGVre": "RDS",
        "Ti39halfu8": "Redshift",
        "R365s2Qddf": "Savings Plans",
    }
    return check_service_map.get(check_id, "Unknown")


def _get_category_from_check(check_id: str) -> str:
    """Map Trusted Advisor check ID to opportunity category."""
    check_category_map = {
        "Qch7DwouX1": "rightsizing",
        "hjLMh88uM8": "idle_resources",
        "DAvU99Dc4C": "storage_optimization",
        "Z4AUBRNSmz": "idle_resources",
        "1iG5NDGVre": "idle_resources",
        "Ti39halfu8": "rightsizing",
        "R365s2Qddf": "savings_plans",
    }
    return check_category_map.get(check_id, "other")


def fetch_compute_optimizer_recommendations(co_client) -> List[Dict]:
    """
    Fetch recommendations from AWS Compute Optimizer.

    Args:
        co_client: Boto3 Compute Optimizer client

    Returns:
        List of recommendation dictionaries
    """
    recommendations = []

    try:
        # Get EC2 instance recommendations
        paginator = co_client.get_paginator("get_ec2_instance_recommendations")

        for page in paginator.paginate():
            for rec in page.get("instanceRecommendations", []):
                finding = rec.get("finding", "")

                # Only include under-provisioned or over-provisioned instances
                if finding in ["UNDER_PROVISIONED", "OVER_PROVISIONED"]:
                    instance_arn = rec.get("instanceArn", "")
                    instance_id = instance_arn.split("/")[-1] if "/" in instance_arn else instance_arn

                    # Get top recommendation option
                    options = rec.get("recommendationOptions", [])
                    estimated_savings = 0.0
                    recommended_type = None

                    if options:
                        top_option = options[0]
                        recommended_type = top_option.get("instanceType")
                        savings_opportunity = top_option.get("savingsOpportunity", {})
                        estimated_savings = savings_opportunity.get("estimatedMonthlySavings", {}).get("value", 0.0)

                    category = "rightsizing" if finding == "OVER_PROVISIONED" else "rightsizing"

                    recommendation = {
                        "source": "compute_optimizer",
                        "source_id": f"co-{instance_id}",
                        "title": f"Optimize EC2 Instance {instance_id}",
                        "description": _build_co_description(rec, recommended_type),
                        "service": "EC2",
                        "category": category,
                        "resource_id": instance_id,
                        "resource_arn": instance_arn,
                        "account_id": rec.get("accountId"),
                        "region": instance_arn.split(":")[3] if ":" in instance_arn else None,
                        "estimated_monthly_savings": estimated_savings,
                        "effort_level": "medium",
                        "risk_level": "low" if finding == "OVER_PROVISIONED" else "medium",
                        "evidence": {
                            "finding": finding,
                            "finding_reason_codes": rec.get("findingReasonCodes", []),
                            "current_instance_type": rec.get("currentInstanceType"),
                            "recommended_instance_type": recommended_type,
                            "utilization_metrics": rec.get("utilizationMetrics", []),
                        },
                        "action_url": f"https://console.aws.amazon.com/compute-optimizer/home#/ec2-instances",
                    }

                    recommendations.append(recommendation)

    except ClientError as e:
        if "OptInRequiredException" in str(e):
            print("Info: Compute Optimizer requires opt-in. Visit AWS Console to enable.")
        else:
            print(f"Warning: Failed to fetch Compute Optimizer recommendations: {e}")
    except Exception as e:
        print(f"Warning: Unexpected error fetching Compute Optimizer recommendations: {e}")

    return recommendations


def _build_co_description(rec: Dict, recommended_type: Optional[str]) -> str:
    """Build description for Compute Optimizer recommendation."""
    finding = rec.get("finding", "Unknown")
    current_type = rec.get("currentInstanceType", "Unknown")
    instance_arn = rec.get("instanceArn", "")
    instance_id = instance_arn.split("/")[-1] if "/" in instance_arn else "Unknown"

    if finding == "OVER_PROVISIONED":
        if recommended_type:
            return f"Instance {instance_id} ({current_type}) is over-provisioned. Consider changing to {recommended_type} based on CPU and memory utilization patterns."
        return f"Instance {instance_id} ({current_type}) is over-provisioned and could use a smaller instance type."
    elif finding == "UNDER_PROVISIONED":
        if recommended_type:
            return f"Instance {instance_id} ({current_type}) is under-provisioned. Consider upgrading to {recommended_type} to improve performance."
        return f"Instance {instance_id} ({current_type}) is under-provisioned and may benefit from a larger instance type."

    return f"Instance {instance_id} has an optimization opportunity."


def store_opportunities(recommendations: List[Dict], dry_run: bool = False) -> int:
    """
    Store recommendations in the database.

    Args:
        recommendations: List of recommendation dictionaries
        dry_run: If True, only print without storing

    Returns:
        Number of opportunities stored
    """
    if dry_run:
        print(f"\n[DRY RUN] Would store {len(recommendations)} opportunities:")
        for rec in recommendations[:10]:  # Show first 10
            print(f"  - {rec['title']} (${rec['estimated_monthly_savings']:.2f}/month)")
        if len(recommendations) > 10:
            print(f"  ... and {len(recommendations) - 10} more")
        return len(recommendations)

    # Import database dependencies only when needed
    try:
        from sqlalchemy import create_engine, text
        from datetime import datetime

        database_url = getenv("DATABASE_URL")
        engine = create_engine(database_url)

        stored_count = 0

        with engine.connect() as conn:
            for rec in recommendations:
                # Check if opportunity already exists by source_id
                existing = conn.execute(
                    text("SELECT id FROM opportunities WHERE source_id = :source_id"),
                    {"source_id": rec["source_id"]}
                ).fetchone()

                if existing:
                    # Update existing opportunity
                    conn.execute(
                        text("""
                            UPDATE opportunities SET
                                title = :title,
                                description = :description,
                                estimated_monthly_savings = :estimated_monthly_savings,
                                evidence = :evidence,
                                updated_at = :updated_at
                            WHERE source_id = :source_id
                        """),
                        {
                            "source_id": rec["source_id"],
                            "title": rec["title"],
                            "description": rec["description"],
                            "estimated_monthly_savings": rec["estimated_monthly_savings"],
                            "evidence": json.dumps(rec.get("evidence", {})),
                            "updated_at": datetime.now(timezone.utc),
                        }
                    )
                else:
                    # Insert new opportunity
                    conn.execute(
                        text("""
                            INSERT INTO opportunities (
                                id, source, source_id, title, description, service, category,
                                resource_id, resource_arn, account_id, region,
                                estimated_monthly_savings, effort_level, risk_level,
                                evidence, action_url, status, created_at, updated_at
                            ) VALUES (
                                :id, :source, :source_id, :title, :description, :service, :category,
                                :resource_id, :resource_arn, :account_id, :region,
                                :estimated_monthly_savings, :effort_level, :risk_level,
                                :evidence, :action_url, 'open', :created_at, :updated_at
                            )
                        """),
                        {
                            "id": str(uuid4()),
                            "source": rec["source"],
                            "source_id": rec["source_id"],
                            "title": rec["title"],
                            "description": rec["description"],
                            "service": rec["service"],
                            "category": rec["category"],
                            "resource_id": rec.get("resource_id"),
                            "resource_arn": rec.get("resource_arn"),
                            "account_id": rec.get("account_id"),
                            "region": rec.get("region"),
                            "estimated_monthly_savings": rec["estimated_monthly_savings"],
                            "effort_level": rec.get("effort_level", "medium"),
                            "risk_level": rec.get("risk_level", "low"),
                            "evidence": json.dumps(rec.get("evidence", {})),
                            "action_url": rec.get("action_url"),
                            "created_at": datetime.now(timezone.utc),
                            "updated_at": datetime.now(timezone.utc),
                        }
                    )
                    stored_count += 1

            conn.commit()

        print(f"Successfully stored {stored_count} new opportunities ({len(recommendations) - stored_count} updated)")
        return stored_count

    except ImportError:
        print("Error: SQLAlchemy not installed. Run: pip install sqlalchemy")
        return 0
    except Exception as e:
        print(f"Error storing opportunities: {e}")
        return 0


def main():
    """Main entry point for opportunities ingestion."""
    parser = argparse.ArgumentParser(
        description="Ingest optimization opportunities from AWS services"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print recommendations without storing to database"
    )
    parser.add_argument(
        "--account-ids",
        type=str,
        help="Comma-separated list of AWS account IDs to filter"
    )
    parser.add_argument(
        "--region",
        type=str,
        default="us-east-1",
        help="AWS region for API calls (default: us-east-1)"
    )
    parser.add_argument(
        "--sources",
        type=str,
        default="all",
        help="Sources to fetch: all, cost-explorer, trusted-advisor, compute-optimizer"
    )

    args = parser.parse_args()

    account_ids = args.account_ids.split(",") if args.account_ids else None
    sources = args.sources.lower().split(",")

    print(f"{'='*60}")
    print("Optimization Opportunities Ingestion")
    print(f"{'='*60}")
    print(f"Region: {args.region}")
    print(f"Sources: {args.sources}")
    print(f"Account IDs: {account_ids or 'All'}")
    print(f"Dry Run: {args.dry_run}")
    print(f"{'='*60}\n")

    all_recommendations = []

    # Initialize AWS clients
    ce_client = boto3.client("ce", region_name=args.region)
    support_client = boto3.client("support", region_name="us-east-1")  # Support API is global
    co_client = boto3.client("compute-optimizer", region_name=args.region)

    # Fetch from Cost Explorer
    if "all" in sources or "cost-explorer" in sources:
        print("Fetching Cost Explorer rightsizing recommendations...")
        ce_recs = fetch_cost_explorer_recommendations(ce_client, account_ids)
        print(f"  Found {len(ce_recs)} recommendations")
        all_recommendations.extend(ce_recs)

    # Fetch from Trusted Advisor
    if "all" in sources or "trusted-advisor" in sources:
        print("Fetching Trusted Advisor cost optimization checks...")
        ta_recs = fetch_trusted_advisor_checks(support_client)
        print(f"  Found {len(ta_recs)} recommendations")
        all_recommendations.extend(ta_recs)

    # Fetch from Compute Optimizer
    if "all" in sources or "compute-optimizer" in sources:
        print("Fetching Compute Optimizer recommendations...")
        co_recs = fetch_compute_optimizer_recommendations(co_client)
        print(f"  Found {len(co_recs)} recommendations")
        all_recommendations.extend(co_recs)

    print(f"\nTotal recommendations found: {len(all_recommendations)}")

    # Calculate total potential savings
    total_savings = sum(rec.get("estimated_monthly_savings", 0) for rec in all_recommendations)
    print(f"Total potential monthly savings: ${total_savings:,.2f}")
    print(f"Total potential annual savings: ${total_savings * 12:,.2f}")

    # Store or display recommendations
    if all_recommendations:
        store_opportunities(all_recommendations, dry_run=args.dry_run)
    else:
        print("\nNo recommendations found. This could mean:")
        print("  - Your infrastructure is already well-optimized")
        print("  - AWS services require additional permissions or opt-in")
        print("  - Check AWS Console for service-specific requirements")

    print(f"\n{'='*60}")
    print("Ingestion complete!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
