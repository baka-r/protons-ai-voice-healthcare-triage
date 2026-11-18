"""Tiny dependency-free Prometheus-text metrics."""
from __future__ import annotations

import threading
from collections import defaultdict

_BUCKETS = (100, 250, 500, 1000, 2000, 4000, 8000, 16000)


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: dict[tuple[str, tuple], float] = defaultdict(float)
        self.gauges: dict[str, float] = {}
        self.hist: dict[str, dict] = {}

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        with self._lock:
            self.counters[(name, tuple(sorted(labels.items())))] += value

    def gauge(self, name: str, value: float) -> None:
        self.gauges[name] = value

    def observe(self, name: str, ms: float | None) -> None:
        if ms is None:
            return
        with self._lock:
            h = self.hist.setdefault(name, {"count": 0, "sum": 0.0, "b": [0] * len(_BUCKETS)})
            h["count"] += 1
            h["sum"] += ms
            for i, b in enumerate(_BUCKETS):
                if ms <= b:
                    h["b"][i] += 1

    def summary(self) -> dict:
        """Plain numbers for the owner dashboard: counters and, per histogram, count / average / approximate p50 and p95 (ms)."""
        with self._lock:
            counters: dict[str, float] = defaultdict(float)
            for (name, _labels), v in self.counters.items():
                counters[name] += v
            lat = {}
            for name, h in self.hist.items():
                n = h["count"]
                if not n:
                    continue

                def q(p: float) -> int:
                    for b, c in zip(_BUCKETS, h["b"]):
                        if c >= p * n:
                            return b
                    return _BUCKETS[-1] * 2

                lat[name] = {"count": n, "avg_ms": round(h["sum"] / n), "p50_ms": q(0.5), "p95_ms": q(0.95)}
            return {"counters": dict(counters), "latency": lat}

    def render(self) -> str:
        out: list[str] = []
        with self._lock:
            for (name, labels), v in sorted(self.counters.items()):
                lab = ",".join(f'{k}="{val}"' for k, val in labels)
                out.append(f"triage_{name}{{{lab}}} {v}" if lab else f"triage_{name} {v}")
            for name, v in sorted(self.gauges.items()):
                out.append(f"triage_{name} {v}")
            for name, h in sorted(self.hist.items()):
                for b, c in zip(_BUCKETS, h["b"]):
                    out.append(f'triage_{name}_ms_bucket{{le="{b}"}} {c}')
                out.append(f'triage_{name}_ms_bucket{{le="+Inf"}} {h["count"]}')
                out.append(f"triage_{name}_ms_sum {h['sum']}")
                out.append(f"triage_{name}_ms_count {h['count']}")
        return "\n".join(out) + "\n"


metrics = Metrics()
