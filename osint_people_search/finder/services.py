from django.conf import settings
from django.utils import timezone

from .adapters import get_adapters
from .adapters.base import SearchQuery
from .fetcher import Fetcher
from .httpclient import BudgetExceeded, FetchError, PoliteClient, RequestBudget
from .models import Finding, SearchJob
from .scoring import score_result
from .utils import normalize_url


def run_job(job, adapters=None, session=None):
    """Run every adapter for a job, score + dedupe results, save findings."""
    cfg = settings.OSINT
    adapters = adapters or get_adapters()
    budget = RequestBudget(job.request_budget)
    client = PoliteClient(
        allowed_hosts=set().union(*(a.allowed_hosts for a in adapters)),
        user_agent=cfg["USER_AGENT"], min_interval=cfg["MIN_INTERVAL"],
        max_bytes=cfg["MAX_BYTES"], timeout=cfg["TIMEOUT"], budget=budget, session=session,
    )
    fetcher = Fetcher(client, ttl_seconds=cfg["CACHE_TTL"])

    job.status = SearchJob.Status.RUNNING
    job.save(update_fields=["status"])

    query = SearchQuery(job.full_name, job.country, job.organization, job.field)
    scored, errors = [], []
    for adapter in adapters:
        try:
            for result in adapter.search(query, fetcher):
                scored.append((result, *score_result(query, result)))
        except BudgetExceeded as exc:
            errors.append(f"{adapter.name}: {exc}")
            break
        except FetchError as exc:
            errors.append(f"{adapter.name}: {exc}")

    best = {}  # dedupe on normalized URL, keep highest confidence
    for result, confidence, signals in scored:
        key = normalize_url(result.url)
        if key not in best or confidence > best[key][1]:
            best[key] = (result, confidence, signals)

    Finding.objects.bulk_create([
        Finding(job=job, source=r.source, url=r.url, title=r.title[:300],
                snippet=r.snippet, confidence=c, signals=s)
        for r, c, s in best.values()
    ])

    job.requests_used = budget.used
    job.cache_hits = fetcher.cache_hits
    job.errors = errors
    job.finished_at = timezone.now()
    if errors and not best:
        job.status = SearchJob.Status.FAILED
    elif errors:
        job.status = SearchJob.Status.PARTIAL
    else:
        job.status = SearchJob.Status.DONE
    job.save()
    return job
