"""Logging: plain text in dev, JSON lines in prod (LOG_FORMAT=json). Never logs utterance text or secrets."""
from __future__ import annotations

import json
import logging
import os
import time


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)), "level": record.levelname,
             "logger": record.name, "msg": record.getMessage()}
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info)[-1500:]
        return json.dumps(d, ensure_ascii=False)


def setup_logging() -> None:
    handler = logging.StreamHandler()
    if os.environ.get("LOG_FORMAT", "text") == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
    for noisy in ("httpx", "httpcore", "openai", "chromadb", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
