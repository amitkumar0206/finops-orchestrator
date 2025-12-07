import os
import json
import boto3

s3 = boto3.client('s3')

BUCKET = os.environ.get('BUCKET')
SOURCE_PREFIX = os.environ.get('SOURCE_PREFIX', 'cost-exports/finops-cost-export')
ARCHIVE_PREFIX = os.environ.get('ARCHIVE_PREFIX', '_archived-manifests')


def handler(event, context):
    # Moves any Manifest.json to archive; ignores everything else.
    for record in event.get('Records', []):
        key = record.get('s3', {}).get('object', {}).get('key', '')
        if not key or not key.startswith(SOURCE_PREFIX):
            continue
        if key.endswith('Manifest.json') and not key.startswith(ARCHIVE_PREFIX):
            dest_key = f"{ARCHIVE_PREFIX}/" + key.replace('/', '_')
            s3.copy_object(Bucket=BUCKET, CopySource={'Bucket': BUCKET, 'Key': key}, Key=dest_key)
            s3.delete_object(Bucket=BUCKET, Key=key)
    return {"status": "ok"}
