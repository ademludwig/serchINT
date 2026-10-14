from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from finder.models import CacheEntry, SearchJob


class Command(BaseCommand):
    help = "Delete jobs (and their findings) older than N days, plus expired cache entries."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=settings.OSINT["RETENTION_DAYS"])

    def handle(self, *args, days, **kwargs):
        cutoff = timezone.now() - timedelta(days=days)
        jobs, _ = SearchJob.objects.filter(created_at__lt=cutoff).delete()
        cache, _ = CacheEntry.objects.filter(expires_at__lt=timezone.now()).delete()
        self.stdout.write(f"Deleted {jobs} job/finding rows and {cache} expired cache entries.")
