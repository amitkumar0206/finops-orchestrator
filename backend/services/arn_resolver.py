import os
import re
import json
from typing import Dict, Optional

from backend.utils.aws_session import create_aws_session
from backend.utils.aws_constants import AwsService


ARN_REGEX = re.compile(r"^arn:(?P<partition>aws|aws-us-gov|aws-cn):(?P<service>[a-z0-9-]+):(?P<region>[a-z0-9-]*):(?P<account>\d{12}):(?P<resource>.+)$")


def parse_arn(arn: str) -> Optional[Dict[str, str]]:
    m = ARN_REGEX.match(arn)
    if not m:
        return None
    parts = m.groupdict()
    resource = parts["resource"]
    # Split common forms: resourceType/resourceId or resourceType:resourceId
    rtype = resource
    rid = resource
    if "/" in resource:
        rtype, rid = resource.split("/", 1)
    elif ":" in resource:
        rtype, rid = resource.split(":", 1)
    parts["resource_type"] = rtype
    parts["resource_id"] = rid
    return parts


def get_boto3_client(service: str, region: str):
    session = create_aws_session(region_name=region or None)
    return session.client(service)


def resolve_ec2_instance(parts: Dict[str, str]) -> Optional[Dict]:
    instance_id = parts.get("resource_id")
    region = parts.get("region")
    account = parts.get("account")
    ec2 = get_boto3_client("ec2", region)
    resp = ec2.describe_instances(InstanceIds=[instance_id])
    for res in resp.get("Reservations", []):
        for inst in res.get("Instances", []):
            tags = inst.get("Tags") or []
            name = next((t["Value"] for t in tags if t.get("Key") == "Name"), None)
            return {
                "service": "AmazonEC2",
                "region": region,
                "account_id": account,
                "resource_id": instance_id,
                "tags": {t["Key"]: t.get("Value") for t in tags},
                "metadata": {
                    "instance_type": inst.get("InstanceType"),
                    "state": (inst.get("State") or {}).get("Name"),
                    "name": name,
                },
            }
    return None


def resolve_lambda_function(parts: Dict[str, str]) -> Optional[Dict]:
    function_name = parts.get("resource_id")
    region = parts.get("region")
    account = parts.get("account")
    lam = get_boto3_client("lambda", region)
    try:
        resp = lam.get_function(FunctionName=function_name)
    except lam.exceptions.ResourceNotFoundException:
        return None
    conf = resp.get("Configuration", {})
    # Lambda ARNs often include version; resource_id should be function name for CUR mapping heuristics
    return {
        "service": "AWSLambda",
        "region": region,
        "account_id": account,
        "resource_id": function_name,
        "tags": {},
        "metadata": {
            "runtime": conf.get("Runtime"),
            "memory_size": conf.get("MemorySize"),
        },
    }


def resolve_arn(arn: str) -> Optional[Dict]:
    parts = parse_arn(arn)
    if not parts:
        return None
    service = parts.get("service")
    if service == "ec2" and parts.get("resource_type") == "instance":
        return resolve_ec2_instance(parts)
    if service == "lambda":
        return resolve_lambda_function(parts)
    if service == "rds":
        return resolve_rds_instance(parts)
    if service == "ecs":
        return resolve_ecs_resource(parts)
    if service == "s3":
        return resolve_s3_resource(parts)
    if service == "eks":
        return resolve_eks_resource(parts)
    if service in ["elasticloadbalancing", "elbv2"]:
        return resolve_elb_resource(parts)
    if service == "ec2" and parts.get("resource_type") == "volume":
        return resolve_ebs_volume(parts)
    # TODO: add RDS, ECS, S3, EKS, ELB, etc.
    return {
        "service": service,
        "region": parts.get("region"),
        "account_id": parts.get("account"),
        "resource_id": parts.get("resource_id"),
        "tags": {},
        "metadata": {},
    }


def cur_filters_from_resolution(res: Dict) -> Dict:
    # Map resolver result to CUR filters we can apply in templates
    filters = {
        "accounts": [res.get("account_id")] if res.get("account_id") else [],
        "regions": [res.get("region")] if res.get("region") else [],
        "services": [res.get("service")] if res.get("service") else [],
    }
    # Some services populate resource_id in CUR, EC2 frequently does
    rid = res.get("resource_id")
    if rid:
        filters["resource_ids"] = [rid]
    # Tags if available
    if res.get("tags"):
        filters["tags"] = res["tags"]
    return filters


def resolve_rds_instance(parts: Dict[str, str]) -> Optional[Dict]:
    # ARN example: arn:aws:rds:region:account-id:db:identifier
    region = parts.get("region")
    account = parts.get("account")
    rtype = parts.get("resource_type")
    rid = parts.get("resource_id")
    if rtype != "db":
        return None
    rds = get_boto3_client("rds", region)
    try:
        resp = rds.describe_db_instances(DBInstanceIdentifier=rid)
    except Exception:
        return None
    dbs = resp.get("DBInstances", [])
    if not dbs:
        return None
    db = dbs[0]
    tags = {}
    return {
        "service": "AmazonRDS",
        "region": region,
        "account_id": account,
        "resource_id": rid,
        "tags": tags,
        "metadata": {
            "engine": db.get("Engine"),
            "db_instance_class": db.get("DBInstanceClass"),
        },
    }


def resolve_ecs_resource(parts: Dict[str, str]) -> Optional[Dict]:
    # ECS ARNs can be cluster/service/task
    region = parts.get("region")
    account = parts.get("account")
    rtype = parts.get("resource_type")
    rid = parts.get("resource_id")
    ecs = get_boto3_client("ecs", region)
    if rtype == "service":
        # rid format: cluster-name/service-name
        try:
            cluster, service_name = rid.split("/", 1)
            resp = ecs.describe_services(cluster=cluster, services=[service_name])
            svcs = resp.get("services", [])
            if svcs:
                return {
                    "service": "AmazonECS",
                    "region": region,
                    "account_id": account,
                    "resource_id": service_name,
                    "tags": {},
                    "metadata": {"cluster": cluster},
                }
        except Exception:
            return None
    elif rtype == "task":
        # rid format: cluster-name/task-id
        try:
            cluster, task_id = rid.split("/", 1)
            resp = ecs.describe_tasks(cluster=cluster, tasks=[task_id])
            tasks = resp.get("tasks", [])
            if tasks:
                return {
                    "service": "AmazonECS",
                    "region": region,
                    "account_id": account,
                    "resource_id": task_id,
                    "tags": {},
                    "metadata": {"cluster": cluster},
                }
        except Exception:
            return None
    return None


def resolve_s3_resource(parts: Dict[str, str]) -> Optional[Dict]:
    # S3 bucket ARNs: arn:aws:s3:::bucket_name
    # Object ARNs: arn:aws:s3:::bucket_name/key
    account = parts.get("account")
    rid = parts.get("resource_id")
    # region may be empty for S3; rely on CUR mapping via service only
    s3 = get_boto3_client(AwsService.S3, parts.get("region"))
    bucket = rid
    key = None
    if "/" in rid:
        bucket, key = rid.split("/", 1)
    metadata = {}
    try:
        # Try bucket tagging
        tagging = s3.get_bucket_tagging(Bucket=bucket)
        tagset = tagging.get("TagSet", [])
        tags = {t["Key"]: t.get("Value") for t in tagset}
    except Exception:
        tags = {}
    if key:
        metadata["object_key"] = key
    return {
        "service": "AmazonS3",
        "region": parts.get("region") or "",
        "account_id": account,
        "resource_id": bucket,
        "tags": tags,
        "metadata": metadata,
    }


def resolve_eks_resource(parts: Dict[str, str]) -> Optional[Dict]:
    # ARN example: arn:aws:eks:region:account-id:cluster/cluster-name
    region = parts.get("region")
    account = parts.get("account")
    rtype = parts.get("resource_type")
    rid = parts.get("resource_id")
    if rtype != "cluster":
        return None
    eks = get_boto3_client("eks", region)
    try:
        resp = eks.describe_cluster(name=rid)
        if resp.get("cluster"):
            return {
                "service": "AmazonEKS",
                "region": region,
                "account_id": account,
                "resource_id": rid,
                "tags": {},
                "metadata": {"version": resp["cluster"].get("version")},
            }
    except Exception:
        return None
    return None


def resolve_elb_resource(parts: Dict[str, str]) -> Optional[Dict]:
    # Classic ELB ARN: arn:aws:elasticloadbalancing:region:account-id:loadbalancer/name
    # ALB/NLB (elbv2) ARN: arn:aws:elasticloadbalancing:region:account-id:loadbalancer/app/name/id
    region = parts.get("region")
    account = parts.get("account")
    rtype = parts.get("resource_type")
    rid = parts.get("resource_id")
    elb = get_boto3_client("elbv2", region)
    # We won't fully parse type here; use name/id heuristics
    try:
        resp = elb.describe_load_balancers()
        lbs = resp.get("LoadBalancers", [])
        for lb in lbs:
            name = lb.get("LoadBalancerName")
            if name and name in rid:
                return {
                    "service": "AmazonElasticLoadBalancing",
                    "region": region,
                    "account_id": account,
                    "resource_id": name,
                    "tags": {},
                    "metadata": {"type": lb.get("Type")},
                }
    except Exception:
        return None
    return None


def resolve_ebs_volume(parts: Dict[str, str]) -> Optional[Dict]:
    # ARN example: arn:aws:ec2:region:account-id:volume/vol-1234567890abcdef0
    region = parts.get("region")
    account = parts.get("account")
    rid = parts.get("resource_id")
    ec2 = get_boto3_client("ec2", region)
    try:
        resp = ec2.describe_volumes(VolumeIds=[rid])
        vols = resp.get("Volumes", [])
        if vols:
            vol = vols[0]
            return {
                "service": "AmazonEC2",
                "region": region,
                "account_id": account,
                "resource_id": rid,
                "tags": {t.get("Key"): t.get("Value") for t in vol.get("Tags", [])},
                "metadata": {"size_gb": vol.get("Size")},
            }
    except Exception:
        return None
    return None
