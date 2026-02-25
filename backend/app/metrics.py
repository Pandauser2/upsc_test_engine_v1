"""
In-process counters for observability. Process-local; for multi-worker use external metrics (e.g. Prometheus).
"""
import threading

# On-demand PDF extraction: number of timeouts (GET /documents/{id}/extract hit timeout).
extraction_timeouts_total: int = 0
_extraction_timeouts_lock = threading.Lock()


def increment_extraction_timeouts_total() -> int:
    """Increment extraction_timeouts_total; return new value. Thread-safe."""
    global extraction_timeouts_total
    with _extraction_timeouts_lock:
        extraction_timeouts_total += 1
        return extraction_timeouts_total
