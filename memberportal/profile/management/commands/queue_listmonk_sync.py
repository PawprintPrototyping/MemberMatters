from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from profile.models import Profile, queue_listmonk_member_sync


class Command(BaseCommand):
    help = "Queue Listmonk synchronization for current active or inactive members."

    def add_arguments(self, parser):
        parser.add_argument(
            "--state",
            choices=("active", "inactive", "all"),
            default="all",
            help="Member state to queue (default: all).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report eligible profiles without creating sync records.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Maximum number of profiles to queue (default: no limit).",
        )

    def handle(self, *args, **options):
        state = options["state"]
        dry_run = options["dry_run"]
        limit = options["limit"]
        if limit < 0:
            raise CommandError("--limit must be zero or greater.")

        states = ("active", "inactive") if state == "all" else (state,)
        profiles = Profile.objects.filter(state__in=states).only("id", "state")
        if limit:
            profiles = profiles[:limit]

        queued = 0
        for profile in profiles.iterator():
            if dry_run:
                self.stdout.write(
                    f"DRY  profile={profile.pk} desired_state={profile.state}"
                )
            else:
                with transaction.atomic():
                    queue_listmonk_member_sync(profile, profile.state)
                self.stdout.write(
                    f"QUEUED profile={profile.pk} desired_state={profile.state}"
                )
            queued += 1

        action = "would queue" if dry_run else "queued"
        self.stdout.write(self.style.SUCCESS(f"Done. {action}={queued}"))
