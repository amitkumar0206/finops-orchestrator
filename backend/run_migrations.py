#!/usr/bin/env python3
"""
Migration Runner Script for FinOps Conversation Threading System

This script provides a convenient interface for managing database migrations
with validation, backup, and rollback capabilities.

Usage:
    python run_migrations.py upgrade    # Run all pending migrations
    python run_migrations.py downgrade  # Rollback one migration
    python run_migrations.py status     # Show current migration status
    python run_migrations.py backup     # Create database backup
"""

import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path


class MigrationRunner:
    """Handle database migrations with safety checks and logging."""
    
    def __init__(self):
        self.script_dir = Path(__file__).parent
        self.alembic_ini = self.script_dir / "alembic.ini"
        
    def run_command(self, command: list) -> tuple[int, str, str]:
        """Execute a shell command and return exit code, stdout, stderr."""
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self.script_dir
        )
        stdout, stderr = process.communicate()
        return process.returncode, stdout, stderr
    
    def check_prerequisites(self) -> bool:
        """Verify that alembic is installed and configuration exists."""
        # Check if alembic is available
        returncode, _, _ = self.run_command(["alembic", "--version"])
        if returncode != 0:
            print("❌ Error: Alembic is not installed.")
            print("Install it with: pip install alembic")
            return False
        
        # Check if alembic.ini exists
        if not self.alembic_ini.exists():
            print(f"❌ Error: alembic.ini not found at {self.alembic_ini}")
            return False
        
        print("✅ Prerequisites check passed")
        return True
    
    def get_current_revision(self) -> str:
        """Get the current database revision."""
        returncode, stdout, stderr = self.run_command(["alembic", "current"])
        if returncode != 0:
            return "Unknown (Database may not be initialized)"
        
        # Parse the output to get revision number
        for line in stdout.split('\n'):
            if '(head)' in line or 'Rev:' in line:
                return line.strip()
        
        return stdout.strip() if stdout.strip() else "No migrations applied"
    
    def show_status(self):
        """Display current migration status."""
        print("\n" + "="*60)
        print("📊 Migration Status")
        print("="*60)
        
        current = self.get_current_revision()
        print(f"\n📍 Current Revision: {current}")
        
        print("\n📋 Migration History:")
        returncode, stdout, stderr = self.run_command(["alembic", "history", "--verbose"])
        if returncode == 0:
            print(stdout)
        else:
            print(f"❌ Error retrieving history: {stderr}")
        
        print("\n" + "="*60 + "\n")
    
    def backup_database(self) -> bool:
        """Create a database backup before running migrations."""
        print("\n💾 Creating database backup...")
        
        # Get database URL from environment or alembic.ini
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            print("⚠️  Warning: DATABASE_URL not set. Skipping backup.")
            print("Set DATABASE_URL environment variable for automatic backups.")
            return True
        
        # Parse database URL to get connection details
        # Format: postgresql://user:password@host:port/database
        try:
            from urllib.parse import urlparse
            parsed = urlparse(db_url)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = f"backup_{parsed.path[1:]}_{timestamp}.sql"
            backup_path = self.script_dir / "backups" / backup_file
            
            # Create backups directory if it doesn't exist
            backup_path.parent.mkdir(exist_ok=True)
            
            # Run pg_dump
            pg_dump_cmd = [
                "pg_dump",
                "-h", parsed.hostname or "localhost",
                "-p", str(parsed.port or 5432),
                "-U", parsed.username,
                "-d", parsed.path[1:],
                "-f", str(backup_path)
            ]
            
            returncode, stdout, stderr = self.run_command(pg_dump_cmd)
            
            if returncode == 0:
                print(f"✅ Backup created: {backup_path}")
                return True
            else:
                print(f"⚠️  Backup failed: {stderr}")
                response = input("Continue without backup? (y/N): ")
                return response.lower() == 'y'
                
        except Exception as e:
            print(f"⚠️  Backup error: {e}")
            response = input("Continue without backup? (y/N): ")
            return response.lower() == 'y'
    
    def upgrade(self, create_backup: bool = True):
        """Run pending migrations."""
        print("\n" + "="*60)
        print("⬆️  Running Database Migrations")
        print("="*60)
        
        # Show current status
        current = self.get_current_revision()
        print(f"\n📍 Current Revision: {current}")
        
        # Create backup if requested
        if create_backup:
            if not self.backup_database():
                print("\n❌ Migration cancelled due to backup failure")
                return False
        
        # Run migrations
        print("\n🚀 Applying migrations...")
        returncode, stdout, stderr = self.run_command(["alembic", "upgrade", "head"])
        
        if returncode == 0:
            print("\n" + stdout)
            print("✅ Migrations completed successfully!")
            
            # Show new status
            new_revision = self.get_current_revision()
            print(f"\n📍 New Revision: {new_revision}")
            return True
        else:
            print(f"\n❌ Migration failed:\n{stderr}")
            return False
    
    def downgrade(self, steps: int = 1):
        """Rollback migrations."""
        print("\n" + "="*60)
        print("⬇️  Rolling Back Migrations")
        print("="*60)
        
        # Show current status
        current = self.get_current_revision()
        print(f"\n📍 Current Revision: {current}")
        
        # Confirm rollback
        print(f"\n⚠️  WARNING: This will rollback {steps} migration(s)")
        response = input("Are you sure? (yes/N): ")
        
        if response.lower() != 'yes':
            print("❌ Rollback cancelled")
            return False
        
        # Create backup before rollback
        if not self.backup_database():
            print("\n❌ Rollback cancelled due to backup failure")
            return False
        
        # Run rollback
        print(f"\n🔄 Rolling back {steps} migration(s)...")
        downgrade_target = f"-{steps}"
        returncode, stdout, stderr = self.run_command(["alembic", "downgrade", downgrade_target])
        
        if returncode == 0:
            print("\n" + stdout)
            print("✅ Rollback completed successfully!")
            
            # Show new status
            new_revision = self.get_current_revision()
            print(f"\n📍 New Revision: {new_revision}")
            return True
        else:
            print(f"\n❌ Rollback failed:\n{stderr}")
            return False
    
    def validate_migrations(self):
        """Validate migration scripts for common issues."""
        print("\n" + "="*60)
        print("🔍 Validating Migrations")
        print("="*60)
        
        versions_dir = self.script_dir / "alembic" / "versions"
        if not versions_dir.exists():
            print("❌ Versions directory not found")
            return False
        
        migration_files = sorted(versions_dir.glob("*.py"))
        if not migration_files:
            print("❌ No migration files found")
            return False
        
        print(f"\n✅ Found {len(migration_files)} migration file(s)")
        
        issues_found = False
        for migration_file in migration_files:
            print(f"\n📄 Checking {migration_file.name}")
            
            with open(migration_file, 'r') as f:
                content = f.read()
                
                # Check for required functions
                if 'def upgrade()' not in content:
                    print("  ❌ Missing upgrade() function")
                    issues_found = True
                else:
                    print("  ✅ upgrade() function found")
                
                if 'def downgrade()' not in content:
                    print("  ❌ Missing downgrade() function")
                    issues_found = True
                else:
                    print("  ✅ downgrade() function found")
                
                # Check for revision identifiers
                if 'revision =' not in content:
                    print("  ❌ Missing revision identifier")
                    issues_found = True
                else:
                    print("  ✅ Revision identifier found")
        
        if not issues_found:
            print("\n✅ All validations passed!")
            return True
        else:
            print("\n⚠️  Some issues found. Please review.")
            return False


def main():
    """Main entry point for the migration runner."""
    runner = MigrationRunner()
    
    # Check prerequisites
    if not runner.check_prerequisites():
        sys.exit(1)
    
    # Parse command
    if len(sys.argv) < 2:
        print("Usage: python run_migrations.py <command>")
        print("\nCommands:")
        print("  upgrade       - Apply all pending migrations")
        print("  downgrade     - Rollback one migration")
        print("  status        - Show current migration status")
        print("  validate      - Validate migration scripts")
        print("  backup        - Create database backup")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "upgrade":
        success = runner.upgrade(create_backup=True)
        sys.exit(0 if success else 1)
    
    elif command == "downgrade":
        steps = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        success = runner.downgrade(steps=steps)
        sys.exit(0 if success else 1)
    
    elif command == "status":
        runner.show_status()
        sys.exit(0)
    
    elif command == "validate":
        success = runner.validate_migrations()
        sys.exit(0 if success else 1)
    
    elif command == "backup":
        success = runner.backup_database()
        sys.exit(0 if success else 1)
    
    else:
        print(f"❌ Unknown command: {command}")
        print("\nAvailable commands: upgrade, downgrade, status, validate, backup")
        sys.exit(1)


if __name__ == "__main__":
    main()
