"""Prometheus metrics for each app process.

Only bounded labels belong here. Session, course, student, and token IDs must
never become metric labels.
"""

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "headcount_http_requests_total",
    "HTTP requests handled by this app process.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "headcount_http_request_duration_seconds",
    "Time spent handling HTTP requests.",
    ("method", "route"),
)
SCANS = Counter(
    "headcount_scans_total",
    "Scan attempts by outcome.",
    ("result",),
)
SESSION_EVENTS = Counter(
    "headcount_session_events_total",
    "Completed session start and end operations.",
    ("event",),
)
TOKEN_ROTATIONS = Counter(
    "headcount_token_rotations_total",
    "Completed token rotations on this app process.",
)
ROTATION_LOCK_ATTEMPTS = Counter(
    "headcount_rotation_lock_attempts_total",
    "Attempts to acquire a session rotation lock.",
    ("result",),
)
ROTATION_LAG = Histogram(
    "headcount_rotation_lag_seconds",
    "Delay between a scheduled and completed token rotation.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
ROTATOR_ITERATIONS = Counter(
    "headcount_rotator_iterations_total",
    "Completed iterations of the background rotator loop.",
)
ROTATOR_ERRORS = Counter(
    "headcount_rotator_errors_total",
    "Errors in the background rotator loop.",
    ("operation",),
)
ROTATOR_LAST_ITERATION = Gauge(
    "headcount_rotator_last_iteration_timestamp_seconds",
    "Unix time of the most recent rotator loop iteration.",
)
ACTIVE_SESSIONS = Gauge(
    "headcount_active_sessions",
    "Sessions in Redis's active-session set, shared across app replicas.",
)
METRICS_REDIS_QUERY_SUCCESS = Gauge(
    "headcount_metrics_redis_query_success",
    "Whether the most recent metrics scrape could query Redis.",
)

# Export zero-valued series before the first event so dashboards do not start blank.
for result in (
    "accepted", "invalid_token", "duplicate", "invalid_identifier",
    "student_not_found", "error",
):
    SCANS.labels(result)
for event in ("start", "end"):
    SESSION_EVENTS.labels(event)
for result in ("won", "lost"):
    ROTATION_LOCK_ATTEMPTS.labels(result)
for operation in ("schedule", "rotate"):
    ROTATOR_ERRORS.labels(operation)
