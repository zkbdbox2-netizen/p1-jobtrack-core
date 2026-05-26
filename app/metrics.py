"""
Prometheus metric definitions for the JobTrack Core API.

Kept in a separate module so:
- main.py stays focused on app wiring
- metrics can be imported anywhere (e.g. a background task that emits a gauge)
- tests can import metrics directly to assert on label values

Three metrics are exposed:

    http_requests_total (Counter)
        Incremented once per completed request.
        Labels: method, path, status_code
        Use case: request rate, error rate (filter status_code>=500), per-endpoint traffic.

    http_request_duration_seconds (Histogram)
        Records latency of every request in seconds.
        Labels: method, path
        Buckets: tuned for a typical API — fast at 10ms, outliers at 5s.
        Use case: p50/p95/p99 latency via histogram_quantile() in PromQL.

    http_requests_inprogress (Gauge)
        Incremented at request start, decremented at request end.
        Labels: method, path
        Use case: detect traffic spikes, slow-draining requests, connection storms.

Why not use a library like starlette-prometheus?
    We wire it manually so the middleware logic is visible and
    interviewers can see we understand what's happening rather than
    adding a black-box dependency.
"""

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Metric definitions — module-level singletons
# ---------------------------------------------------------------------------

REQUEST_COUNT = Counter(
    name="http_requests_total",
    documentation="Total HTTP requests received, by method, path, and status code.",
    labelnames=["method", "path", "status_code"],
)

REQUEST_LATENCY = Histogram(
    name="http_request_duration_seconds",
    documentation="HTTP request latency in seconds, by method and path.",
    labelnames=["method", "path"],
    # Buckets cover: fast API responses (10–100ms), acceptable (500ms),
    # slow (1–2s), and outliers (5s+). Values above the last bucket
    # land in the +Inf bucket automatically.
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

REQUESTS_INPROGRESS = Gauge(
    name="http_requests_inprogress",
    documentation="Number of HTTP requests currently being processed.",
    labelnames=["method", "path"],
)
