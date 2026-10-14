from django.db import models


class SearchJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        RUNNING = "running"
        DONE = "done"
        PARTIAL = "partial"  # some adapter failed or the budget ran out
        FAILED = "failed"

    full_name = models.CharField(max_length=200)
    country = models.CharField(max_length=100, blank=True)
    organization = models.CharField(max_length=200, blank=True)
    field = models.CharField(max_length=200, blank=True)
    purpose = models.CharField(max_length=255, default="unspecified")  # audit trail
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    request_budget = models.PositiveIntegerField(default=5)
    requests_used = models.PositiveIntegerField(default=0)
    cache_hits = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Job {self.pk}: {self.full_name} [{self.status}]"


class Finding(models.Model):
    job = models.ForeignKey(SearchJob, on_delete=models.CASCADE, related_name="findings")
    source = models.CharField(max_length=50)
    url = models.URLField(max_length=500)
    title = models.CharField(max_length=300)
    snippet = models.TextField(blank=True)
    collected_at = models.DateTimeField(auto_now_add=True)  # provenance
    confidence = models.FloatField()
    signals = models.JSONField(default=dict)  # why it scored what it did

    class Meta:
        ordering = ["-confidence"]
        constraints = [models.UniqueConstraint(fields=["job", "url"], name="uniq_job_url")]


class CacheEntry(models.Model):
    key = models.CharField(max_length=64, unique=True)  # sha256 of url + params
    payload = models.JSONField()
    expires_at = models.DateTimeField(db_index=True)
