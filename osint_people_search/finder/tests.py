import json

import requests
from django.conf import settings
from django.test import TestCase, override_settings

from .adapters.base import RawResult, SearchQuery
from .adapters.wikidata import WikidataAdapter
from .fetcher import Fetcher
from .httpclient import (BudgetExceeded, FetchError, HostNotAllowed, PoliteClient,
                         RateLimited, RequestBudget, ResponseTooLarge)
from .models import CacheEntry, SearchJob
from .scoring import NAME_ONLY_CAP, score_result
from .services import run_job
from .utils import normalize_url

HOSTS = {"www.wikidata.org", "query.wikidata.org"}
API = "https://www.wikidata.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"


class FakeResponse:
    def __init__(self, body=b"{}", status=200, headers=None):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status_code = status
        self.headers = headers or {}

    def iter_content(self, n):
        for i in range(0, len(self.body), n):
            yield self.body[i:i + n]

    def close(self):
        pass


class FakeSession:
    def __init__(self, handler):
        self.handler, self.calls, self.headers = handler, [], {}

    def get(self, url, params=None, **kwargs):
        self.calls.append((url, params))
        return self.handler(url, params)


class FakeTime:
    def __init__(self):
        self.now, self.slept = 1000.0, []

    def clock(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def make_client(handler, **kw):
    t = FakeTime()
    session = FakeSession(handler)
    client = PoliteClient(HOSTS, "test-agent", clock=t.clock, sleep=t.sleep, session=session, **kw)
    return client, session, t


def wikidata_handler(sparql_status=200):
    def handler(url, params):
        if url == API:
            return FakeResponse({"search": [
                {"id": "Q1", "label": "Jane Doe", "description": "Algerian cybersecurity researcher",
                 "match": {"text": "Jane Doe"}},
                {"id": "Q2", "label": "Jane Doe", "description": "2010 film"},
            ]})
        if sparql_status != 200:
            return FakeResponse(b"", status=sparql_status)
        return FakeResponse({"results": {"bindings": [{"item": {"value": "http://www.wikidata.org/entity/Q1"}}]}})
    return handler


FAST = {**settings.OSINT, "WIKIDATA_LANGUAGES": ["en"], "MIN_INTERVAL": 0}


class HttpClientTests(TestCase):
    def test_waits_between_requests_to_same_host(self):
        client, _, t = make_client(lambda u, p: FakeResponse(), min_interval=3)
        client.get(API)
        client.get(API)
        self.assertEqual(t.slept, [3])

    def test_429_pauses_host_without_sending_more_requests(self):
        client, session, _ = make_client(lambda u, p: FakeResponse(status=429, headers={"Retry-After": "30"}))
        with self.assertRaises(RateLimited):
            client.get(API)
        with self.assertRaises(RateLimited):
            client.get(API)
        self.assertEqual(len(session.calls), 1)

    def test_budget_enforced(self):
        client, session, _ = make_client(lambda u, p: FakeResponse(), min_interval=0, budget=RequestBudget(1))
        client.get(API)
        with self.assertRaises(BudgetExceeded):
            client.get(API)
        self.assertEqual(len(session.calls), 1)

    def test_rejects_unlisted_host_and_http(self):
        client, session, _ = make_client(lambda u, p: FakeResponse())
        for url in ("https://evil.example/x", "http://www.wikidata.org/x"):
            with self.assertRaises(HostNotAllowed):
                client.get(url)
        self.assertEqual(session.calls, [])

    def test_response_size_cap(self):
        client, _, _ = make_client(lambda u, p: FakeResponse(b"x" * 5000), max_bytes=1000)
        with self.assertRaises(ResponseTooLarge):
            client.get(API)

    def test_redirects_refused(self):
        client, _, _ = make_client(lambda u, p: FakeResponse(status=302))
        with self.assertRaises(FetchError):
            client.get(API)

    def test_network_errors_wrapped(self):
        def boom(u, p):
            raise requests.ConnectionError("down")
        client, _, _ = make_client(boom)
        with self.assertRaises(FetchError):
            client.get(API)


class CacheTests(TestCase):
    def test_second_call_served_from_cache(self):
        client, session, _ = make_client(lambda u, p: FakeResponse({"ok": 1}), min_interval=0)
        fetcher = Fetcher(client)
        self.assertEqual(fetcher.get_json(API, {"a": 1}), {"ok": 1})
        self.assertEqual(fetcher.get_json(API, {"a": 1}), {"ok": 1})
        self.assertEqual(len(session.calls), 1)
        self.assertEqual((fetcher.network_requests, fetcher.cache_hits), (1, 1))
        self.assertEqual(CacheEntry.objects.count(), 1)

    def test_invalid_json_raises(self):
        client, _, _ = make_client(lambda u, p: FakeResponse(b"<html>"))
        with self.assertRaises(FetchError):
            Fetcher(client).get_json(API)


class ScoringTests(TestCase):
    def result(self, name="Jane Doe", snippet="Algerian researcher", rel=0.9):
        return RawResult("wikidata", "https://x/Q1", name, snippet, names=[name], reliability=rel)

    def test_name_only_is_capped(self):
        conf, sig = score_result(SearchQuery("Jane Doe"), self.result())
        self.assertLessEqual(conf, NAME_ONLY_CAP)
        self.assertTrue(sig["capped_name_only"])

    def test_context_raises_score(self):
        plain, _ = score_result(SearchQuery("Jane Doe"), self.result())
        with_ctx, sig = score_result(SearchQuery("Jane Doe", country="Algerian"), self.result())
        self.assertGreater(with_ctx, plain)
        self.assertEqual(sig["context_hits"], ["Algerian"])

    def test_different_name_scores_low_and_accents_ignored(self):
        low, _ = score_result(SearchQuery("Jane Doe", country="Algerian"), self.result(name="Bob Smith"))
        same, _ = score_result(SearchQuery("Jané Doe", country="Algerian"), self.result())
        self.assertLess(low, 0.5)
        self.assertGreater(same, 0.9)


@override_settings(OSINT=FAST)
class WikidataAdapterTests(TestCase):
    def test_keeps_only_humans(self):
        client, _, _ = make_client(wikidata_handler(), min_interval=0)
        results = WikidataAdapter().search(SearchQuery("Jane Doe"), Fetcher(client))
        self.assertEqual([r.extra["qid"] for r in results], ["Q1"])
        self.assertTrue(results[0].extra["human_verified"])

    def test_sparql_failure_degrades_to_unverified(self):
        client, _, _ = make_client(wikidata_handler(sparql_status=503), min_interval=0)
        results = WikidataAdapter().search(SearchQuery("Jane Doe"), Fetcher(client))
        self.assertEqual(len(results), 2)
        self.assertFalse(any(r.extra["human_verified"] for r in results))
        self.assertTrue(all(r.reliability == 0.6 for r in results))


@override_settings(OSINT=FAST)
class ServiceTests(TestCase):
    def test_run_job_saves_ranked_findings(self):
        job = SearchJob.objects.create(full_name="Jane Doe", country="Algerian", request_budget=5)
        run_job(job, session=FakeSession(wikidata_handler()))
        job.refresh_from_db()
        self.assertEqual(job.status, SearchJob.Status.DONE)
        self.assertEqual(job.requests_used, 2)  # 1 search + 1 SPARQL
        self.assertEqual(job.findings.count(), 1)
        self.assertGreater(job.findings.first().confidence, 0.8)

    def test_second_identical_job_uses_cache_only(self):
        for _ in range(2):
            job = SearchJob.objects.create(full_name="Jane Doe")
            session = FakeSession(wikidata_handler())
            run_job(job, session=session)
        self.assertEqual(session.calls, [])
        self.assertEqual((job.requests_used, job.cache_hits), (0, 2))

    def test_budget_exhaustion_marks_partial_or_failed(self):
        job = SearchJob.objects.create(full_name="Jane Doe", request_budget=1)
        run_job(job, session=FakeSession(wikidata_handler()))
        job.refresh_from_db()
        self.assertIn(job.status, (SearchJob.Status.PARTIAL, SearchJob.Status.FAILED))
        self.assertTrue(job.errors)


class UtilTests(TestCase):
    def test_normalize_url(self):
        self.assertEqual(
            normalize_url("HTTPS://Example.com/a/?utm_source=x&b=2&a=1#frag"),
            "https://example.com/a?a=1&b=2",
        )
