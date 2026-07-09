#!/usr/bin/env python3
"""
Upload parquet files from a local folder to the demo S3 bucket,
then automatically register any new BILLING_PERIOD partitions with Athena.

Maintains a local state file so subsequent runs only upload NEW files —
files already uploaded are skipped. Progress is saved after every successful
upload, so if the script is interrupted it will resume from where it left off.

Usage:
    python scripts/utilities/sync_to_demo_s3.py [OPTIONS]

    # Upload everything found under LOCAL_DIR and register new partitions
    python scripts/utilities/sync_to_demo_s3.py --local-dir /path/to/export

    # See what would be uploaded without actually doing it
    python scripts/utilities/sync_to_demo_s3.py --dry-run

    # Show what has already been uploaded
    python scripts/utilities/sync_to_demo_s3.py --status
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

# ─── Defaults ────────────────────────────────────────────────────────────────

LOCAL_DIR_DEFAULT = "/Users/agranee/Documents/Code/S3Download"
AWS_PROFILE_DEFAULT = "aiverse-deployer"
AWS_REGION_DEFAULT = "ap-south-1"

# Athena / Glue config — must match the running app (cost_usage_db.cur_data in ap-south-1)
ATHENA_DATABASE = "cost_usage_db"
ATHENA_TABLE = "cur_data"

# S3 prefix under the bucket where CUR parquet files live
# Files land at: s3://<bucket>/CUR_S3_PREFIX/BILLING_PERIOD=YYYY-MM/
CUR_S3_PREFIX = "cur-data"

# State file lives in the user's home dir so it persists across checkouts and
# is never accidentally committed to git.
STATE_FILE_DEFAULT = Path.home() / ".aasmaa-demo-upload-state.json"

# Regex that matches the BILLING_PERIOD Hive partition folder name
_BILLING_PERIOD_RE = re.compile(r"BILLING_PERIOD=(\d{4}-\d{2})")


# ─── State helpers ────────────────────────────────────────────────────────────

def load_state(state_file: Path) -> dict:
    """Load upload state from disk; returns empty state if file doesn't exist."""
    if state_file.exists():
        with open(state_file) as f:
            return json.load(f)
    return {
        "uploaded": {},
        "registered_partitions": [],
        "last_run": None,
        "local_dir": None,
        "bucket": None,
    }


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
        dirs.sort()
        for filename in sorted(filenames):
            abs_path = Path(root) / filename
            rel_path = abs_path.relative_to(local_dir).as_posix()
            files.append((abs_path, rel_path))
    return files


def extract_billing_period(rel_path: str) -> str | None:
    """Return 'YYYY-MM' if the path contains a BILLING_PERIOD=YYYY-MM segment."""
    m = _BILLING_PERIOD_RE.search(rel_path)
    return m.group(1) if m else None


# ─── AWS helpers ──────────────────────────────────────────────────────────────

def resolve_bucket(session: boto3.Session, region: str) -> str:
    """Derive the demo bucket name from the current AWS account ID."""
    sts = session.client("sts", region_name=region)
    account_id = sts.get_caller_identity()["Account"]
    return f"aasmaa-demo-data-{account_id}-{region}"


def upload_file(s3_client, local_path: Path, bucket: str, s3_key: str) -> bool:
    """Upload a single file; returns True on success, False on failure."""
    try:
        s3_client.upload_file(str(local_path), bucket, s3_key)
        return True
    except ClientError as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return False


# ─── Partition registration ───────────────────────────────────────────────────

def register_partitions(
    session: boto3.Session,
    region: str,
    bucket: str,
    new_periods: list[str],
    dry_run: bool,
) -> None:
    """
    Register each new BILLING_PERIOD partition with Athena so queries can find
    the data immediately — no crawler run required.

    Uses ALTER TABLE ... ADD IF NOT EXISTS PARTITION which is idempotent.
    """
    if not new_periods:
        return

    print()
    print("─" * 60)
    print("Registering new partitions with Athena…")

    athena = session.client("athena", region_name=region)
    sts = session.client("sts", region_name=region)
    account_id = sts.get_caller_identity()["Account"]

    # Athena needs somewhere to write query results; use the bucket's athena-results prefix
    output_location = f"s3://{bucket}/athena-results/"

    for period in sorted(new_periods):
        s3_location = f"s3://{bucket}/{CUR_S3_PREFIX}/BILLING_PERIOD={period}/"
        sql = (
            f"ALTER TABLE {ATHENA_DATABASE}.{ATHENA_TABLE} "
            f"ADD IF NOT EXISTS PARTITION (billing_period='{period}') "
            f"LOCATION '{s3_location}'"
        )

        print(f"  Partition {period}  →  {s3_location}")

        if dry_run:
            print(f"    [DRY RUN] Would run: {sql}")
            continue

        try:
            resp = athena.start_query_execution(
                QueryString=sql,
                QueryExecutionContext={"Database": ATHENA_DATABASE},
                ResultConfiguration={"OutputLocation": output_location},
            )
            qid = resp["QueryExecutionId"]

            # Poll until done (usually < 5 seconds)
            for _ in range(60):
                status_resp = athena.get_query_execution(QueryExecutionId=qid)
                state = status_resp["QueryExecution"]["Status"]["State"]
                if state == "SUCCEEDED":
                    print(f"    ✓ Registered")
                    break
                if state in ("FAILED", "CANCELLED"):
                    reason = status_resp["QueryExecution"]["Status"].get(
                        "StateChangeReason", "unknown"
                    )
                    print(f"    ✗ Failed: {reason}", file=sys.stderr)
                    break
                time.sleep(1)

        except ClientError as e:
            code = e.response["Error"].get("Code", "")
            msg = e.response["Error"].get("Message", str(e))
            if "AccessDenied" in code or "AccessDeniedException" in code:
                print(
                    f"    ✗ No Athena permission to register partition.\n"
                    f"      Run this manually in the Athena console:\n"
                    f"      {sql}",
                    file=sys.stderr,
                )
            else:
                print(f"    ✗ Error: {msg}", file=sys.stderr)

    print()


# ─── Commands ────────────────────────────────────────────────────────────────

def cmd_status(state: dict) -> None:
    """Print a summary of what has already been uploaded."""
    uploaded = state.get("uploaded", {})
    registered = state.get("registered_partitions", [])
    last_run = state.get("last_run")
    bucket = state.get("bucket", "unknown")
    local_dir = state.get("local_dir", "unknown")

    print(f"State summary")
    print(f"  Local dir             : {local_dir}")
    print(f"  Bucket                : s3://{bucket}")
    print(f"  Last run              : {last_run or 'never'}")
    print(f"  Uploaded              : {len(uploaded)} file(s)")
    print(f"  Registered partitions : {', '.join(sorted(registered)) or 'none'}")
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

    state["local_dir"] = str(local_dir)
    state["bucket"] = bucket

    already_uploaded: set[str] = set(state["uploaded"].keys())
    already_registered: set[str] = set(state.get("registered_partitions", []))

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
    new_periods: set[str] = set()

    for i, (abs_path, rel_path) in enumerate(new_files, 1):
        if args.s3_prefix:
            s3_key = args.s3_prefix.rstrip("/") + "/" + rel_path
        else:
            s3_key = CUR_S3_PREFIX.rstrip("/") + "/" + rel_path

        file_size = abs_path.stat().st_size
        size_mb = file_size / (1024 * 1024)

        print(f"[{i:>{len(str(len(new_files)))}}/{len(new_files)}]  {rel_path}  ({size_mb:.2f} MB)")

        if args.dry_run:
            print(f"          -> s3://{bucket}/{s3_key}  [DRY RUN — skipped]")
            period = extract_billing_period(rel_path)
            if period:
                new_periods.add(period)
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
            # Track which BILLING_PERIOD partitions the new files belong to
            period = extract_billing_period(rel_path)
            if period and period not in already_registered:
                new_periods.add(period)
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

    # Register any new partitions that appeared in this batch
    if new_periods:
        register_partitions(session, args.region, bucket, list(new_periods), args.dry_run)
        if not args.dry_run:
            state.setdefault("registered_partitions", [])
            for p in new_periods:
                if p not in state["registered_partitions"]:
                    state["registered_partitions"].append(p)
            save_state(state_file, state)
    else:
        print(f"\nNo new BILLING_PERIOD partitions detected — Athena catalog unchanged.")

    return fail_count == 0


# ─── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Incrementally upload new parquet files to the demo S3 bucket, "
            "then register any new BILLING_PERIOD partitions with Athena automatically."
        ),
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
        help="Print what would be uploaded/registered without actually doing it",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show upload history from the state file and exit",
    )
    args = parser.parse_args()

    state_file = Path(args.state_file).expanduser().resolve()
    state = load_state(state_file)

    if args.status:
        cmd_status(state)
        return

    local_dir = Path(args.local_dir).expanduser().resolve()
    if not local_dir.exists():
        print(f"ERROR: Local directory does not exist: {local_dir}", file=sys.stderr)
        sys.exit(1)

    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        s3 = session.client("s3", region_name=args.region)
        bucket = args.bucket or resolve_bucket(session, args.region)
    except NoCredentialsError:
        print("ERROR: AWS credentials not found. Check --profile.", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("  Demo S3 Incremental Upload + Partition Registration")
    print("=" * 60)
    print(f"  Source     : {local_dir}")
    print(f"  Destination: s3://{bucket}/{args.s3_prefix or CUR_S3_PREFIX}/")
    print(f"  Athena     : {ATHENA_DATABASE}.{ATHENA_TABLE}")
    print(f"  State file : {state_file}")
    print(f"  AWS profile: {args.profile}  |  region: {args.region}")
    print(f"  Mode       : {'DRY RUN' if args.dry_run else 'UPLOAD + REGISTER'}")
    print("=" * 60)
    print()

    ok = cmd_upload(args, session, s3, bucket, state)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
