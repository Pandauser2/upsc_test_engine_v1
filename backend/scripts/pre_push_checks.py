#!/usr/bin/env python3
"""
Pre-push / production readiness checks.
Run from backend dir with project venv active: python scripts/pre_push_checks.py
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def check_imports():
    from app.main import app  # noqa: F401
    from app.llm import vision_mcq
    from app.database import init_sqlite_db
    from app.jobs.tasks import clear_stuck_generating_tests
    assert vision_mcq.RATE_LIMIT_MAX_INPUT_TOKENS == 25_000
    assert vision_mcq.RATE_LIMIT_WINDOW_SEC == 60
    assert vision_mcq.RATE_LIMIT_SLEEP_SEC == 20
    return "imports"


def check_rate_limit_prune():
    import time
    from app.llm import vision_mcq
    vision_mcq._ingestion_token_times.clear()
    now = time.time()
    vision_mcq._ingestion_token_times.extend([(now - 70, 1000), (now - 5, 20000)])
    with vision_mcq._ingestion_token_lock:
        now = time.time()
        vision_mcq._ingestion_token_times[:] = [
            (t, n) for t, n in vision_mcq._ingestion_token_times
            if t > now - vision_mcq.RATE_LIMIT_WINDOW_SEC
        ]
        cum = sum(n for _, n in vision_mcq._ingestion_token_times)
    assert len(vision_mcq._ingestion_token_times) == 1 and cum == 20000
    return "rate_limit_prune"


def check_init_db():
    from app.database import init_sqlite_db
    init_sqlite_db()
    return "init_sqlite_db"


def check_clear_stuck():
    from app.jobs.tasks import clear_stuck_generating_tests
    from app.config import settings
    clear_stuck_generating_tests(max_age_seconds=getattr(settings, "max_stale_generation_seconds", 1200))
    return "clear_stuck_generating_tests"


def main():
    checks = [check_imports, check_rate_limit_prune, check_init_db, check_clear_stuck]
    for fn in checks:
        try:
            name = fn()
            print(f"OK {name}")
        except Exception as e:
            print(f"FAIL {fn.__name__}: {e}")
            return 1
    print("All pre-push checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
