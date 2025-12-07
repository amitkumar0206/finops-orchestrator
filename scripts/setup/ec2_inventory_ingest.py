import os
import sys
import json
import time
from datetime import datetime

import boto3
import pyarrow as pa
import pyarrow.parquet as pq


def getenv(name: str, default: str = None) -> str:
    val = os.getenv(name, default)
    if val is None or val == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return val


def build_s3_uri(bucket: str, prefix: str, filename: str) -> str:
    prefix = prefix.strip("/")
    return f"s3://{bucket}/{prefix}/{filename}"


def list_all_regions(ec2):
    return [r["RegionName"] for r in ec2.describe_regions(AllRegions=True)["Regions"]]


def fetch_ec2_instances(region: str):
    ec2 = boto3.client("ec2", region_name=region)
    paginator = ec2.get_paginator("describe_instances")
    instances = []
    for page in paginator.paginate():
        for reservation in page.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                instances.append(inst)
    return instances


def extract_record(account_id: str, region: str, inst: dict) -> dict:
    instance_id = inst.get("InstanceId")
    service = "AmazonEC2"
    resource_id = instance_id
    arn = f"arn:aws:ec2:{region}:{account_id}:instance/{instance_id}"
    state = (inst.get("State") or {}).get("Name")
    itype = inst.get("InstanceType")
    platform_details = inst.get("PlatformDetails")
    launch_time = inst.get("LaunchTime")
    tags = inst.get("Tags") or []
    name_tag = next((t["Value"] for t in tags if t.get("Key") == "Name"), None)
    return {
        "account_id": account_id,
        "region": region,
        "service": service,
        "resource_id": resource_id,
        "arn": arn,
        "instance_type": itype,
        "platform_details": platform_details,
        "state": state,
        "name": name_tag,
        "launch_time": launch_time.isoformat() if hasattr(launch_time, "isoformat") else None,
        "tags_json": json.dumps(tags, separators=(",", ":")),
        "ingested_at": datetime.utcnow().isoformat(timespec="seconds"),
    }


def write_parquet_s3(records, s3_bucket: str, s3_prefix: str, filename: str):
    table = pa.Table.from_pylist(records)
    local_path = f"/tmp/{filename}"
    pq.write_table(table, local_path)
    s3 = boto3.client("s3")
    key = f"{s3_prefix.strip('/')}/{filename}"
    s3.upload_file(local_path, s3_bucket, key)
    return f"s3://{s3_bucket}/{key}"


def ensure_glue_database(glue, database: str):
    try:
        glue.get_database(Name=database)
    except glue.exceptions.EntityNotFoundException:
        glue.create_database(DatabaseInput={"Name": database})


def ensure_glue_table(glue, database: str, table: str, s3_location: str):
    storage_desc = {
        "Columns": [
            {"Name": "account_id", "Type": "string"},
            {"Name": "region", "Type": "string"},
            {"Name": "service", "Type": "string"},
            {"Name": "resource_id", "Type": "string"},
            {"Name": "arn", "Type": "string"},
            {"Name": "instance_type", "Type": "string"},
            {"Name": "platform_details", "Type": "string"},
            {"Name": "state", "Type": "string"},
            {"Name": "name", "Type": "string"},
            {"Name": "launch_time", "Type": "string"},
            {"Name": "tags_json", "Type": "string"},
            {"Name": "ingested_at", "Type": "string"},
        ],
        "Location": s3_location,
        "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
        "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
        "Compressed": False,
        "NumberOfBuckets": -1,
        "SerdeInfo": {
            "SerializationLibrary": "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe",
            "Parameters": {"parquet.compression": "SNAPPY"},
        },
        "Parameters": {"classification": "parquet"},
    }

    try:
        glue.get_table(DatabaseName=database, Name=table)
        glue.update_table(
            DatabaseName=database,
            TableInput={
                "Name": table,
                "StorageDescriptor": storage_desc,
                "TableType": "EXTERNAL_TABLE",
                "Parameters": {"classification": "parquet"},
            },
        )
    except glue.exceptions.EntityNotFoundException:
        glue.create_table(
            DatabaseName=database,
            TableInput={
                "Name": table,
                "StorageDescriptor": storage_desc,
                "TableType": "EXTERNAL_TABLE",
                "Parameters": {"classification": "parquet"},
            },
        )


def main():
    account_id = boto3.client("sts").get_caller_identity()["Account"]
    aws_region = getenv("AWS_REGION", "us-east-1")
    s3_bucket = getenv("RESOURCE_INVENTORY_S3_BUCKET")
    s3_prefix = getenv("RESOURCE_INVENTORY_S3_PREFIX", "resource-inventory/")
    glue_db = getenv("RESOURCE_INVENTORY_DB", "resource_inventory")
    glue_table = getenv("RESOURCE_INVENTORY_TABLE", "resources")

    regions = [aws_region]
    # Optional: to index all regions, uncomment next line
    # regions = list_all_regions(boto3.client("ec2", region_name=aws_region))

    records = []
    for region in regions:
        insts = fetch_ec2_instances(region)
        for inst in insts:
            records.append(extract_record(account_id, region, inst))

    if not records:
        print("No EC2 instances found; nothing to ingest")
        return

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename = f"ec2_resources_{ts}.parquet"
    s3_uri = write_parquet_s3(records, s3_bucket, s3_prefix, filename)
    print(f"Uploaded inventory parquet to {s3_uri}")

    # Glue table should point to the prefix root, not specific file
    s3_location = f"s3://{s3_bucket}/{s3_prefix.strip('/')}"
    glue = boto3.client("glue", region_name=aws_region)
    # Ensure database exists before creating table
    ensure_glue_database(glue, glue_db)
    ensure_glue_table(glue, glue_db, glue_table, s3_location)
    print(f"Glue table ensured: {glue_db}.{glue_table} -> {s3_location}")


if __name__ == "__main__":
    main()
