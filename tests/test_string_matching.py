#!/usr/bin/env python3
"""
Test string matching logic locally
"""

requested_service = "Amazon Elastic Compute Cloud"
actual_services = [
    "AmazonCloudWatch",
    "Amazon Virtual Private Cloud",
    "Amazon Elastic Load Balancing",
    "Amazon Elastic Compute Cloud - Compute",
    "Amazon Managed Streaming for Apache Kafka",
    "Amazon ElastiCache",
    "EC2 - Other",
    "Amazon DynamoDB"
]

print("Testing partial string matching:")
print("=" * 80)
print(f"Requested service: '{requested_service}'")
print(f"Requested service (lower): '{requested_service.lower()}'")
print()

matches = []
for actual in actual_services:
    is_match = requested_service.lower() in actual.lower()
    print(f"  '{actual}'")
    print(f"    -> lower: '{actual.lower()}'")
    print(f"    -> match: {is_match}")
    if is_match:
        matches.append(actual)
    print()

print(f"\nTotal matches: {len(matches)}")
print(f"Matched services: {matches}")
