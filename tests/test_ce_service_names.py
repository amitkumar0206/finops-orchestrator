#!/usr/bin/env python3
"""
Test Cost Explorer API directly to see what service names it returns for EC2
"""

import boto3
from datetime import datetime, timedelta
import json


def main():
    # Initialize Cost Explorer client
    ce_client = boto3.client('ce', region_name='us-east-1')

    # Get 200 days of data
    end_date = datetime.now()
    start_date = end_date - timedelta(days=200)

    # Format dates
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    print(f"Querying Cost Explorer for {start_str} to {end_str}")
    print("=" * 80)

    # Query without filter to see all services
    response = ce_client.get_cost_and_usage(
        TimePeriod={
            "Start": start_str,
            "End": end_str
        },
        Granularity="MONTHLY",
        Metrics=["BlendedCost"],
        GroupBy=[
            {"Type": "DIMENSION", "Key": "SERVICE"}
        ]
    )

    # Collect all unique services
    all_services = set()
    ec2_services = []

    for result_by_time in response.get("ResultsByTime", []):
        for group in result_by_time.get("Groups", []):
            service_name = group["Keys"][0] if group["Keys"] else "Unknown"
            all_services.add(service_name)

            # Check if this looks like EC2
            if "elastic compute" in service_name.lower() or "ec2" in service_name.lower():
                cost = float(group["Metrics"]["BlendedCost"]["Amount"])
                if cost > 0:
                    ec2_services.append((service_name, cost))

    print(f"\nTotal unique services: {len(all_services)}")
    print("\nServices containing 'EC2' or 'Elastic Compute':")
    print("-" * 80)

    if ec2_services:
        for service, cost in sorted(ec2_services, key=lambda x: x[1], reverse=True):
            print(f"  {service}: ${cost:,.2f}")
    else:
        print("  None found!")

    print("\n\nFull list of all services:")
    print("-" * 80)
    for service in sorted(all_services):
        print(f"  - {service}")


if __name__ == "__main__":
    main()
