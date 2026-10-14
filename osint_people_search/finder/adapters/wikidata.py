"""Wikidata adapter: official API + one small SPARQL query to keep only humans.

Requests per investigation: one wbsearchentities call per language, plus one
SPARQL call. If the SPARQL call fails, results are kept but flagged unverified.
"""
import re

from django.conf import settings

from ..httpclient import BudgetExceeded, FetchError
from .base import Adapter, RawResult

API = "https://www.wikidata.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
QID = re.compile(r"^Q[0-9]+$")
MAX_CANDIDATES = 10


class WikidataAdapter(Adapter):
    name = "wikidata"
    allowed_hosts = frozenset({"www.wikidata.org", "query.wikidata.org"})

    def search(self, query, fetcher):
        hits = self._search_entities(query, fetcher)
        if not hits:
            return []

        try:
            humans = self._filter_humans(list(hits), fetcher)
        except BudgetExceeded:
            raise
        except FetchError:
            humans = None  # degrade: keep candidates, mark as unverified

        results = []
        for qid, hit in hits.items():
            if humans is not None and qid not in humans:
                continue
            verified = humans is not None
            label = hit.get("label") or qid
            names = {label}
            matched = (hit.get("match") or {}).get("text")
            if matched:
                names.add(matched)
            results.append(RawResult(
                source=self.name,
                url=f"https://www.wikidata.org/wiki/{qid}",
                title=label,
                snippet=hit.get("description") or "",
                names=sorted(names),
                reliability=0.9 if verified else 0.6,
                extra={"qid": qid, "human_verified": verified},
            ))
        return results

    def _search_entities(self, query, fetcher):
        hits = {}
        search_text = " ".join(query.full_name.split()).lower()  # stable cache key
        for lang in settings.OSINT["WIKIDATA_LANGUAGES"]:
            data = fetcher.get_json(API, {
                "action": "wbsearchentities", "search": search_text, "language": lang,
                "uselang": lang, "type": "item", "limit": MAX_CANDIDATES, "format": "json",
            })
            for item in data.get("search", []):
                if QID.match(item.get("id", "")):
                    hits.setdefault(item["id"], item)
        return dict(list(hits.items())[:MAX_CANDIDATES])

    def _filter_humans(self, qids, fetcher):
        values = " ".join(f"wd:{q}" for q in qids if QID.match(q))
        sparql = f"SELECT ?item WHERE {{ VALUES ?item {{ {values} }} ?item wdt:P31 wd:Q5 . }}"
        data = fetcher.get_json(SPARQL, {"query": sparql, "format": "json"})
        return {b["item"]["value"].rsplit("/", 1)[-1] for b in data["results"]["bindings"]}
