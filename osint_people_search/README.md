# OSINT people-search - Phase 1

Django backend skeleton: models, polite HTTP client, cache, Wikidata adapter,
explainable scoring, CLI. Free, local, SQLite, no Redis/Celery needed yet.

## Setup
    python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    export OSINT_USER_AGENT="OSINTStudyTool/0.1 (contact: you@university.dz)"   # Windows: set ...
    python manage.py migrate
    python manage.py test

## Use
    python manage.py search_name "Full Name" --country Algeria --field cybersecurity --purpose "M2 project test"
    python manage.py purge_old_jobs --days 30

## Layout
    finder/httpclient.py   allowlist, 3s/host spacing, budget, size cap, 429 pause, no redirects
    finder/fetcher.py      24h DB cache in front of the client (hits cost no budget)
    finder/adapters/       one class per source (Wikidata first)
    finder/scoring.py      name-gated confidence, capped at 0.6 without context
    finder/services.py     run_job: adapters -> score -> dedupe -> save

## Next (Phase 2/3)
Add GitHub + OpenAlex adapters, a job queue (django-q2), then the DRF API and React UI.
Test only on yourself, consenting volunteers, or public-figure test cases.
