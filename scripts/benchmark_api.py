"""Benchmark local FastAPI catalog endpoints without a flaky pass/fail gate."""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = min(int((len(ordered) - 1) * quantile), len(ordered) - 1)
    return ordered[index]


def benchmark_endpoint(client: TestClient, path: str, iterations: int) -> dict[str, float]:
    for _ in range(min(10, iterations)):
        response = client.get(path)
        response.raise_for_status()

    durations_ms: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        response = client.get(path)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        response.raise_for_status()
        durations_ms.append(elapsed_ms)

    return {
        "p50_ms": statistics.median(durations_ms),
        "p95_ms": percentile(durations_ms, 0.95),
        "mean_ms": statistics.fmean(durations_ms),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=200)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be at least 1")

    with TestClient(app) as client:
        for path in ("/metrics/catalog", "/metrics/catalog/categories"):
            results = benchmark_endpoint(client, path, args.iterations)
            meets_target = results["p95_ms"] < 10
            print(
                f"{path}: p50={results['p50_ms']:.3f}ms "
                f"p95={results['p95_ms']:.3f}ms "
                f"mean={results['mean_ms']:.3f}ms "
                f"p95_below_10ms={meets_target}"
            )
    print(
        "Measurements use in-process FastAPI TestClient. Warm-up includes the initial "
        "read-only DuckDB query; timed requests use the file-metadata-keyed cache and "
        "exclude external network latency."
    )


if __name__ == "__main__":
    main()
