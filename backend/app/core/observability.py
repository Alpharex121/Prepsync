import logging
import time
from collections import defaultdict

logger = logging.getLogger("prepsync")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

metrics = defaultdict(int)


def record_metric(name: str, value: int = 1) -> None:
    metrics[name] += value


def log_request(method: str, path: str, status_code: int, duration_ms: float) -> None:
    record_metric("http_requests_total")
    logger.info(
        "request method=%s path=%s status=%s duration_ms=%.2f",
        method,
        path,
        status_code,
        duration_ms,
    )


def log_error(context: str, error: Exception) -> None:
    record_metric("errors_total")
    logger.exception("error context=%s detail=%s", context, str(error))


def timed() -> float:
    return time.perf_counter()


def elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0
