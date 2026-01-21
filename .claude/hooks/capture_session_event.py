#!/usr/bin/env python3
"""
Hook to capture session start/end events.
Cross-platform support for Windows, macOS, and Linux.
"""
import json
import sys
import os
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from claude_code_capture_utils import get_log_file_path, add_ab_metadata, detect_model_lane, get_experiment_root

def get_git_metadata(repo_dir):
    """Get current git commit and branch."""
    try:
        # Get current commit hash
        commit_result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=repo_dir, 
            capture_output=True, 
            text=True, 
            timeout=10
        )
        
        # Get current branch
        branch_result = subprocess.run(
            ['git', 'branch', '--show-current'],
            cwd=repo_dir, 
            capture_output=True, 
            text=True, 
            timeout=10
        )
        
        git_metadata = {
            "base_commit": commit_result.stdout.strip() if commit_result.returncode == 0 else None,
            "branch": branch_result.stdout.strip() if branch_result.returncode == 0 else None,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        if git_metadata["base_commit"]:
            return git_metadata
        else:
            return None
            
    except Exception as e:
        print(f"Warning: Could not capture git metadata: {e}", file=sys.stderr)
        return None

def create_repository_snapshot_zip(source_dir, zip_file_path):
    """Create a zip file of the repository, excluding system files."""
    try:
        if os.path.exists(zip_file_path):
            os.remove(zip_file_path)
        
        exclude_patterns = {'.git', '.claude', '.DS_Store', '__pycache__', '.vscode', '.idea', 
                          'node_modules', '.pytest_cache', '.mypy_cache', '*.pyc', '*.pyo'}
        
        def should_exclude(file_path):
            path_parts = Path(file_path).parts
            name = os.path.basename(file_path)
            
            for part in path_parts:
                if part in exclude_patterns or part.startswith('.'):
                    if part not in {'.gitignore', '.env.example', '.dockerignore'}:
                        return True
            
            if name.endswith(('.pyc', '.pyo', '.DS_Store')):
                return True
                
            return False
        
        with zipfile.ZipFile(zip_file_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            source_path = Path(source_dir)
            
            for file_path in source_path.rglob('*'):
                if file_path.is_file():
                    relative_path = file_path.relative_to(source_path)
                    
                    if not should_exclude(str(relative_path)):
                        zipf.write(file_path, relative_path)
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Creating repository snapshot: {e}", file=sys.stderr)
        return False

def generate_git_diff(repo_dir, output_file, base_commit):
    """Generate git diff from base commit to current state."""
    try:
        original_cwd = os.getcwd()
        os.chdir(repo_dir)
        
        if not base_commit:
            os.chdir(original_cwd)
            return False
        
        # Add untracked files with intent-to-add
        excluded_patterns = ['.claude/', '__pycache__/', 'node_modules/', '.mypy_cache/', 
                           '.pytest_cache/', '.DS_Store', '.vscode/', '.idea/']
        
        untracked_result = subprocess.run(
            ['git', 'ls-files', '--others', '--exclude-standard'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if untracked_result.returncode == 0 and untracked_result.stdout.strip():
            untracked_files = []
            for file in untracked_result.stdout.strip().split('\n'):
                file = file.strip()
                if file and not any(pattern in file for pattern in excluded_patterns):
                    untracked_files.append(file)
            
            for file in untracked_files:
                subprocess.run(['git', 'add', '-N', file], capture_output=True, timeout=5)
        
        # Generate git diff
        result = subprocess.run(
            ['git', 'diff', base_commit, '--', '.', 
             ':!.claude', ':!**/.mypy_cache', ':!**/__pycache__', ':!**/.pytest_cache',
             ':!**/.DS_Store', ':!**/node_modules', ':!**/.vscode', ':!**/.idea'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(result.stdout)
        
        os.chdir(original_cwd)
        return result.returncode == 0
        
    except Exception as e:
        print(f"[ERROR] Generating git diff: {e}", file=sys.stderr)
        if 'original_cwd' in locals():
            os.chdir(original_cwd)
        return False

def main():
    try:
        if len(sys.argv) < 2:
            print("Usage: capture_session_event.py [start|end]", file=sys.stderr)
            sys.exit(1)
        
        event_type = sys.argv[1].lower()
        if event_type not in ["start", "end"]:
            print("Event type must be 'start' or 'end'", file=sys.stderr)
            sys.exit(1)
        
        input_data = json.load(sys.stdin)
        
        session_id = input_data.get("session_id", "unknown")
        transcript_path = input_data.get("transcript_path", "")
        cwd = input_data.get("cwd", "")
        
        if event_type == "start":
            # Session start: git metadata + initial snapshot
            git_metadata = get_git_metadata(cwd)
            
            log_entry = {
                "type": "session_start",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": session_id,
                "transcript_path": transcript_path,
                "cwd": cwd,
                "git_metadata": git_metadata
            }
            
            log_entry = add_ab_metadata(log_entry, cwd)
            
            if git_metadata:
                print(f"[OK] Captured git metadata: {git_metadata['base_commit'][:8]} on {git_metadata['branch']}")
            
            # Create initial snapshot
            model_lane = detect_model_lane(cwd)
            experiment_root = get_experiment_root(cwd)
            
            if model_lane and experiment_root:
                snapshots_dir = os.path.join(experiment_root, "snapshots")
                os.makedirs(snapshots_dir, exist_ok=True)
                snapshot_zip = os.path.join(snapshots_dir, f"{model_lane}_start.zip")
                
                if create_repository_snapshot_zip(cwd, snapshot_zip):
                    print(f"[OK] Created start snapshot for {model_lane}")
            
            # Write session_start event
            log_file = get_log_file_path(session_id, cwd)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
                
        elif event_type == "end":
            # Session end: final snapshot + git diff
            log_entry = {
                "type": "session_end",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": session_id,
                "transcript_path": transcript_path,
                "cwd": cwd,
                "reason": input_data.get("reason", "")
            }
            
            log_entry = add_ab_metadata(log_entry, cwd)
            
            model_lane = detect_model_lane(cwd)
            experiment_root = get_experiment_root(cwd)
            
            if model_lane and experiment_root:
                snapshots_dir = os.path.join(experiment_root, "snapshots")
                os.makedirs(snapshots_dir, exist_ok=True)
                
                # Create final snapshot
                snapshot_zip = os.path.join(snapshots_dir, f"{model_lane}_end.zip")
                if create_repository_snapshot_zip(cwd, snapshot_zip):
                    print(f"[OK] Created end snapshot for {model_lane}")
                
                # Generate git diff
                log_file = get_log_file_path(session_id, cwd)
                base_commit = get_base_commit_from_log(log_file)
                
                if base_commit:
                    diff_file = os.path.join(snapshots_dir, f"{model_lane}_diff.patch")
                    if generate_git_diff(cwd, diff_file, base_commit):
                        print(f"[OK] Generated git diff from {base_commit[:8]}")
            
            # Write session_end event
            log_file = get_log_file_path(session_id, cwd)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
            
    except Exception as e:
        print(f"[ERROR] Session {event_type}: {e}", file=sys.stderr)
        sys.exit(1)

def get_base_commit_from_log(log_file):
    """Extract base commit from session_start event in log."""
    try:
        if not os.path.exists(log_file):
            return None
        
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        event = json.loads(line)
                        if event.get('type') == 'session_start':
                            git_metadata = event.get('git_metadata', {})
                            return git_metadata.get('base_commit')
                    except json.JSONDecodeError:
                        continue
        return None
    except Exception:
        return None

if __name__ == "__main__":
    main()

