#!/usr/bin/env python3
"""
Upload parquet files from a local folder to the demo S3 bucket.

Maintains a local state file so subsequent runs only upload NEW files —
files already uploaded are skipped. Progress is saved after every successful
upload, so if the script is interrupted it will resume from where it left off.

Usage:
    python scripts/utilities/sync_to_demo_s3.py [OPTIONS]

    # First run — uploads everything found under LOCAL_DIR
    python scripts/utilities/sync_to_demo_s3.py

    # Subsequent runs — only uploads files not yet in state
    python scripts/utilities/sync_to_demo_s3.py

    # Override bucket or local dir
    python scripts/utilities/sync_to_demo_s3.py --bucket my-bucket --local-dir /path/to/data

    # See what would be uploaded without actually doing it
    python scripts/utilities/sync_to_demo_s3.py --dry-run

    # Show what has already been uploaded
    python scripts/utilities/sync_to_demo_s3.py --status
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

# ─── Defaults ────────────────────────────────────────────────────────────────

LOCAL_DIR_DEFAULT = "/Users/agranee/Documents/Code/S3Download"
AWS_PROFILE_DEFAULT = "aiverse-deployer"
AWS_REGION_DEFAULT = "us-east-1"

# State file lives in the user's home dir so it persists across checkouts and
# is never accidentally committed to git.
STATE_FILE_DEFAULT = Path.home() / ".aasmaa-demo-upload-state.json"


# ─── State helpers ────────────────────────────────────────────────────────────

def load_state(state_file: Path) -> dict:
    """Load upload state from disk; returns empty state if file doesn't exist."""
    if state_file.exists():
        with open(state_file) as f:
            return json.load(f)
    return {"uploaded": {}, "last_run": None, "local_dir": None, "bucket": None}


def save_state(state_file: Path, state: dict) -> None:
    """Persist state to disk atomically (write to temp then rename)."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(state_file)


# ─── File discovery ───────────────────────────────────────────────────────────

def get_local_files(local_dir: Path) -> list[tuple[Path, str]]:
    """
    Walk local_dir and return (absolute_path, relative_posix_path) for every file.
    Results are sorted so uploads are deterministic and resumable in order.
    """
    files = []
    for root, dirs, filenames in os.walk(local_dir):
        dirs.sort()  # deterministic traversal order
        for filename in sorted(filenames):
            abs_path = Path(root) / filename
            # Use POSIX separators for the relative path — S3 keys use forward slashes
            rel_path = abs_path.relative_to(local_dir).as_posix()
            files.append((abs_path, rel_path))
    return files


# ─── AWS helpers ──────────────────────────────────────────────────────────────

def resolve_bucket(session: boto3.Session, region: str) -> str:
    """Derive the demo bucket name from the current AWS account ID."""
    sts = session.client("sts", region_name=region)
    account_id = sts.get_caller_identity()["Account"]
    return f"aasmaa-demo-data-{account_id}"


def upload_file(s3_client, local_path: Path, bucket: str, s3_key: str) -> bool:
    """Upload a single file; returns True on success, False on failure."""
    try:
        s3_client.upload_file(str(local_path), bucket, s3_key)
        return True
    except ClientError as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return False


# ─── Commands ────────────────────────────────────────────────────────────────

def cmd_status(state: dict) -> None:
    """Print a summary of what has already been uploaded."""
    uploaded = state.get("uploaded", {})
    last_run = state.get("last_run")
    bucket = state.get("bucket", "unknown")
    local_dir = state.get("local_dir", "unknown")

    print(f"State summary")
    print(f"  Local dir  : {local_dir}")
    print(f"  Bucket     : s3://{bucket}")
    print(f"  Last run   : {last_run or 'never'}")
    print(f"  Uploaded   : {len(uploaded)} file(s)")
    if uploaded:
        print()
        print("  Files uploaded:")
        for rel_path, meta in sorted(uploaded.items()):
            size_mb = meta.get("size_bytes", 0) / (1024 * 1024)
            ts = meta.get("uploaded_at", "?")
            print(f"    {rel_path}  ({size_mb:.2f} MB)  uploaded: {ts}")


def cmd_upload(args, session: boto3.Session, s3, bucket: str, state: dict) -> bool:
    """
    Main upload loop. Returns True if everything succeeded (or nothing to do).
    """
    local_dir = Path(args.local_dir).expanduser().resolve()
    state_file = Path(args.state_file).expanduser().resolve()

    # Record config in state so --status is informative
    state["local_dir"] = str(local_dir)
    state["bucket"] = bucket

    already_uploaded: set[str] = set(state["uploaded"].keys())

    # Discover all local files
    print("Scanning local directory…")
    all_files = get_local_files(local_dir)
    new_files = [(p, r) for p, r in all_files if r not in already_uploaded]

    print(f"  Total files found  : {len(all_files)}")
    print(f"  Already uploaded   : {len(already_uploaded)}")
    print(f"  New files to upload: {len(new_files)}")
    print()

    if not new_files:
        print("Nothing to do — all files are already in S3.")
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        if not args.dry_run:
            save_state(state_file, state)
        return True

    success_count = 0
    fail_count = 0
    start_time = time.time()
    total_bytes = 0

    for i, (abs_path, rel_path) in enumerate(new_files, 1):
        # Build S3 key: optional prefix + relative path
        if args.s3_prefix:
            s3_key = args.s3_prefix.rstrip("/") + "/" + rel_path
        else:
            s3_key = rel_path

        file_size = abs_path.stat().st_size
        size_mb = file_size / (1024 * 1024)

        print(f"[{i:>{len(str(len(new_files)))}}/{len(new_files)}]  {rel_path}  ({size_mb:.2f} MB)")

        if args.dry_run:
            print(f"          -> s3://{bucket}/{s3_key}  [DRY RUN — skipped]")
            success_count += 1
            continue

        if upload_file(s3, abs_path, bucket, s3_key):
            state["uploaded"][rel_path] = {
                "s3_key": s3_key,
                "size_bytes": file_size,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            }
            total_bytes += file_size
            success_count += 1
            # Save state after EVERY file so interruption = safe resume
            save_state(state_file, state)
        else:
            fail_count += 1
            print(f"  Skipping {rel_path} and continuing…")

    elapsed = time.time() - start_time
    total_mb = total_bytes / (1024 * 1024)

    state["last_run"] = datetime.now(timezone.utc).isoformat()
    if not args.dry_run:
        save_state(state_file, state)

    print()
    print("─" * 60)
    if args.dry_run:
        print(f"DRY RUN complete — {success_count} file(s) would be uploaded")
    else:
        print(f"Done in {elapsed:.1f}s")
        print(f"  Uploaded : {success_count} file(s)  ({total_mb:.2f} MB)")
        if fail_count:
            print(f"  Failed   : {fail_count} file(s)  (re-run to retry)")

    return fail_count == 0


# ─── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Incrementally upload new parquet files to the demo S3 bucket.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--local-dir", default=LOCAL_DIR_DEFAULT,
        help=f"Local folder to upload from (default: {LOCAL_DIR_DEFAULT})",
    )
    parser.add_argument(
        "--bucket", default=None,
        help="S3 bucket name (default: auto-detected as aasmaa-demo-data-<account-id>)",
    )
    parser.add_argument(
        "--s3-prefix", default="",
        help="Optional S3 key prefix (default: empty — files land at bucket root preserving folder structure)",
    )
    parser.add_argument(
        "--profile", default=AWS_PROFILE_DEFAULT,
        help=f"AWS profile name (default: {AWS_PROFILE_DEFAULT})",
    )
    parser.add_argument(
        "--region", default=AWS_REGION_DEFAULT,
        help=f"AWS region (default: {AWS_REGION_DEFAULT})",
    )
    parser.add_argument(
        "--state-file", default=str(STATE_FILE_DEFAULT),
        help=f"Path to upload state JSON file (default: {STATE_FILE_DEFAULT})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be uploaded without actually uploading anything",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show upload history from the state file and exit",
    )
    args = parser.parse_args()

    state_file = Path(args.state_file).expanduser().resolve()
    state = load_state(state_file)

    # ── Status mode ──────────────────────────────────────────────────────────
    if args.status:
        cmd_status(state)
        return

    # ── Validate local dir ───────────────────────────────────────────────────
    local_dir = Path(args.local_dir).expanduser().resolve()
    if not local_dir.exists():
        print(f"ERROR: Local directory does not exist: {local_dir}", file=sys.stderr)
        sys.exit(1)

    # ── AWS session ──────────────────────────────────────────────────────────
    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        s3 = session.client("s3", region_name=args.region)
        bucket = args.bucket or resolve_bucket(session, args.region)
    except NoCredentialsError:
        print("ERROR: AWS credentials not found. Check --profile.", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("  Demo S3 Incremental Upload")
    print("=" * 60)
    print(f"  Source     : {local_dir}")
    print(f"  Destination: s3://{bucket}/{args.s3_prefix or '(root)'}")
    print(f"  State file : {state_file}")
    print(f"  AWS profile: {args.profile}  |  region: {args.region}")
    print(f"  Mode       : {'DRY RUN' if args.dry_run else 'UPLOAD'}")
    print("=" * 60)
    print()

    ok = cmd_upload(args, session, s3, bucket, state)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
