"""Synthetic JSON transport benchmark; never invokes an LLM or reads user data."""
import argparse
import json
from pathlib import Path
import statistics
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    import orjson
    payloads = []
    for size in (1, 8, 64):
        payloads += [
            {"id": "synthetic", "choices": [{"delta": {"content": "hello мир " * size}, "index": 0}]},
            {"tools": [{"type": "function", "function": {"name": "search", "arguments": {"query": "test", "limit": 10}}} for _ in range(size)]},
            {"messages": [{"role": "user", "content": "Synthetic public fixture" * size}]},
        ]
    for payload in payloads:
        assert orjson.loads(orjson.dumps(payload)) == payload
        assert json.loads(orjson.dumps(payload)) == payload
    encoded = [orjson.dumps(payload) for payload in payloads]
    repeats, loops = 9, 12000
    measurements = []
    for repeat in range(repeats):
        start = time.perf_counter_ns()
        for i in range(loops):
            orjson.dumps(payloads[i % len(payloads)])
            orjson.loads(encoded[i % len(encoded)])
        elapsed = (time.perf_counter_ns() - start) / loops
        if repeat:
            measurements.append(elapsed)
    result = {"workload": "synthetic-json-roundtrip-v1", "version": orjson.__version__,
              "median_ns": statistics.median(measurements), "samples_ns": measurements,
              "scope": "JSON serialization and parsing only; not LLM tokens/s"}
    if args.output:
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    else:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
