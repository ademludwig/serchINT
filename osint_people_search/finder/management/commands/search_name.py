from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from finder.adapters.base import SearchQuery
from finder.models import SearchJob
from finder.services import run_job


class Command(BaseCommand):
    help = "Search public sources for a person's name and print ranked findings."

    def add_arguments(self, parser):
        parser.add_argument("name")
        parser.add_argument("--country", default="")
        parser.add_argument("--org", default="")
        parser.add_argument("--field", default="")
        parser.add_argument("--purpose", default="unspecified", help="why you are searching (audit log)")
        parser.add_argument("--budget", type=int, default=settings.OSINT["DEFAULT_BUDGET"])

    def handle(self, *args, **o):
        try:
            SearchQuery(o["name"])  # validates input
        except ValueError as exc:
            raise CommandError(str(exc))

        job = SearchJob.objects.create(
            full_name=o["name"], country=o["country"], organization=o["org"],
            field=o["field"], purpose=o["purpose"], request_budget=o["budget"],
        )
        run_job(job)

        self.stdout.write(f"\nJob {job.pk} [{job.status}] - {job.requests_used} request(s), "
                          f"{job.cache_hits} cache hit(s)")
        for err in job.errors:
            self.stderr.write(f"  ! {err}")
        for f in job.findings.all():
            self.stdout.write(f"\n{f.confidence:.2f}  {f.title}  ({f.source})")
            self.stdout.write(f"      {f.url}")
            if f.snippet:
                self.stdout.write(f"      {f.snippet}")
            self.stdout.write(f"      signals: {f.signals}")
        if not job.findings.exists():
            self.stdout.write("No findings.")
