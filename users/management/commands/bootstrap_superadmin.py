import os

from django.core.management.base import BaseCommand, CommandError

from users.services import create_or_update_superadmin_account


class Command(BaseCommand):
    help = (
        "Create or update the backend-controlled Super Admin account "
        "(superadmin@gmail.com)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            dest="password",
            type=str,
            help="Super Admin password (or use SUPERADMIN_PASSWORD env var).",
        )

    def handle(self, *args, **options):
        password = options.get("password") or os.getenv("SUPERADMIN_PASSWORD")
        if not password:
            raise CommandError(
                "Provide password via --password or SUPERADMIN_PASSWORD env var."
            )

        try:
            user, created = create_or_update_superadmin_account(password=password)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        action = "created" if created else "updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"Super Admin {action} successfully: {user.email} (id={user.id})"
            )
        )
