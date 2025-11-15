"""
Management command to download all data from the server database (Azure SQL Server)
and import it into the local SQLite database.

Usage:
    python manage.py sync_server_to_sqlite [--output-file OUTPUT_FILE] [--skip-migrations]

This command:
1. Connects to the Azure SQL Server database
2. Exports all data to a JSON fixture file
3. Switches to SQLite database
4. Clears existing SQLite data (optional)
5. Imports the exported data into SQLite
"""

import os
import json
import tempfile
from pathlib import Path
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.conf import settings
from common.logging_config import logger


class Command(BaseCommand):
    help = "Download all data from server database and import into SQLite"

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-file",
            type=str,
            default=None,
            help="Path to save the exported JSON fixture file (default: zauto/fixtures/server_data_export.json)",
        )
        parser.add_argument(
            "--skip-migrations",
            action="store_true",
            help="Skip running migrations on SQLite before import",
        )
        parser.add_argument(
            "--clear-sqlite",
            action="store_true",
            help="Clear all existing data from SQLite before import",
        )
        parser.add_argument(
            "--exclude-apps",
            nargs="+",
            default=["contenttypes", "sessions", "admin"],
            help="Apps to exclude from export (default: contenttypes, sessions, admin)",
        )
        parser.add_argument(
            "--import-only",
            type=str,
            default=None,
            help="Import from existing fixture file instead of exporting from server",
        )

    def handle(self, *args, **options):
        func_name = "sync_server_to_sqlite"
        output_file = options.get("output_file")
        skip_migrations = options.get("skip_migrations", False)
        clear_sqlite = options.get("clear_sqlite", False)
        exclude_apps = options.get("exclude_apps", [])
        import_only = options.get("import_only")

        # Check if we're currently using Azure database
        current_env = os.environ.get("DJANGO_ENV", "local").upper()
        is_azure = current_env == "AZURE"
        is_sqlite = settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"

        try:
            # If import-only mode, skip export
            if import_only:
                fixture_file = import_only
                if not Path(fixture_file).exists():
                    raise CommandError(f"Fixture file not found: {fixture_file}")
            else:
                # Step 1: Export data from server
                if not is_azure:
                    self.stdout.write(
                        self.style.WARNING(
                            "⚠️  Not connected to Azure database. "
                            "Set DJANGO_ENV=AZURE to connect to server."
                        )
                    )
                    response = input("Continue anyway? (yes/no): ")
                    if response.lower() != "yes":
                        raise CommandError("Aborted by user")

                self.stdout.write(self.style.SUCCESS("📥 Step 1: Exporting data from server..."))
                fixture_file = self.export_from_server(output_file, exclude_apps)
                self.stdout.write(
                    self.style.SUCCESS(f"✅ Exported data to: {fixture_file}")
                )

                # If we're still on Azure, tell user to switch
                if is_azure:
                    self.stdout.write(
                        self.style.SUCCESS(
                            "\n✅ Export complete!\n"
                            "📋 Next steps:\n"
                            f"   1. Set DJANGO_ENV=local (or unset it)\n"
                            f"   2. Run: python manage.py sync_server_to_sqlite --import-only {fixture_file}\n"
                            f"   OR: python manage.py loaddata {fixture_file}"
                        )
                    )
                    return

            # Step 2: Verify we're on SQLite
            if not is_sqlite:
                raise CommandError(
                    "Not using SQLite database. Set DJANGO_ENV=local to use SQLite."
                )

            # Step 3: Run migrations on SQLite (if needed)
            if not skip_migrations:
                self.stdout.write(
                    self.style.SUCCESS("🔧 Step 2: Running migrations on SQLite...")
                )
                call_command("migrate", verbosity=1, interactive=False)

            # Step 4: Clear SQLite data (if requested)
            if clear_sqlite:
                self.stdout.write(
                    self.style.WARNING("🗑️  Step 3: Clearing existing SQLite data...")
                )
                self.clear_sqlite_data()

            # Step 5: Import data into SQLite
            self.stdout.write(
                self.style.SUCCESS("📤 Step 4: Importing data into SQLite...")
            )
            self.import_to_sqlite(fixture_file)

            self.stdout.write(
                self.style.SUCCESS(
                    "\n✅ Successfully synced all data from server to SQLite!"
                )
            )
            if not import_only:
                self.stdout.write(f"📁 Fixture file saved at: {fixture_file}")

        except Exception as e:
            logger.exception(f"[{func_name}] Error syncing data: {e}")
            raise CommandError(f"Failed to sync data: {e}")

    def export_from_server(self, output_file=None, exclude_apps=None):
        """Export all data from the server database to a JSON fixture file."""
        func_name = "export_from_server"

        if output_file:
            fixture_path = Path(output_file)
            # Resolve relative paths from BASE_DIR
            if not fixture_path.is_absolute():
                fixture_path = Path(settings.BASE_DIR) / fixture_path
            # Ensure parent directory exists
            fixture_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            # Create temp file
            temp_dir = Path(settings.BASE_DIR) / "zauto" / "fixtures"
            temp_dir.mkdir(parents=True, exist_ok=True)
            fixture_path = temp_dir / "server_data_export.json"

        # Build exclude list for dumpdata
        exclude_args = []
        for app in exclude_apps or []:
            exclude_args.extend(["--exclude", app])

        # Export all data
        with open(fixture_path, "w", encoding="utf-8") as f:
            call_command(
                "dumpdata",
                "--natural-foreign",
                "--natural-primary",
                "--indent", "2",
                *exclude_args,
                stdout=f,
                verbosity=1,
            )

        logger.info(f"[{func_name}] Exported data to {fixture_path}")
        return str(fixture_path)

    def clear_sqlite_data(self):
        """Clear all data from SQLite database (except auth tables)."""
        func_name = "clear_sqlite_data"

        # Get all models from installed apps, ordered by dependencies
        from django.apps import apps
        from django.db import connection

        # Disable foreign key checks for SQLite
        if connection.vendor == "sqlite":
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA foreign_keys = OFF")

        models_to_clear = []
        for app_config in apps.get_app_configs():
            if app_config.label in ["contenttypes", "sessions", "admin", "auth"]:
                continue  # Skip system apps
            for model in app_config.get_models():
                models_to_clear.append(model)

        # Delete in reverse order to handle foreign keys
        with transaction.atomic():
            for model in reversed(models_to_clear):
                try:
                    count = model.objects.all().delete()[0]
                    if count > 0:
                        logger.info(
                            f"[{func_name}] Deleted {count} {model.__name__} records"
                        )
                        self.stdout.write(
                            f"   Deleted {count} {model.__name__} records"
                        )
                except Exception as e:
                    logger.warning(
                        f"[{func_name}] Could not delete {model.__name__}: {e}"
                    )

        # Re-enable foreign key checks
        if connection.vendor == "sqlite":
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA foreign_keys = ON")

    def import_to_sqlite(self, fixture_file):
        """Import data from fixture file into SQLite database."""
        func_name = "import_to_sqlite"

        if not Path(fixture_file).exists():
            raise CommandError(f"Fixture file not found: {fixture_file}")

        # Import data
        try:
            call_command(
                "loaddata",
                fixture_file,
                verbosity=2,
            )
            logger.info(f"[{func_name}] Successfully imported data from {fixture_file}")
        except Exception as e:
            logger.exception(f"[{func_name}] Error importing data: {e}")
            raise CommandError(f"Failed to import data: {e}")

