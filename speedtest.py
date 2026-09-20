from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterator

__version__ = "1.0.0"

DEFAULT_REQUESTS = 10
DEFAULT_TIMEOUT = 60.0
DEFAULT_RETRIES = 3
DEFAULT_CHUNK_SIZE = 64 * 1024
USER_AGENT = f"speedtest/{__version__}"

log = logging.getLogger("speedtest")

MB = 1024 * 1024


@dataclass(frozen=True)
class Sample:
    size_bytes: int
    ttfb_seconds: float
    total_seconds: float

    @property
    def speed_mb_per_sec(self) -> float:
        if self.total_seconds <= 0:
            return 0.0
        return self.size_bytes / MB / self.total_seconds


@dataclass(frozen=True)
class Report:
    url: str
    samples: list[Sample]
    failures: int

    @property
    def total_bytes(self) -> int:
        return sum(s.size_bytes for s in self.samples)

    @property
    def total_seconds(self) -> float:
        return sum(s.total_seconds for s in self.samples)

    @property
    def avg_time_seconds(self) -> float:
        return self.total_seconds / len(self.samples) if self.samples else 0.0

    @property
    def avg_speed_mb_per_sec(self) -> float:
        return self.total_bytes / MB / self.total_seconds if self.total_seconds else 0.0

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "requests": len(self.samples),
            "failures": self.failures,
            "avg_time_seconds": round(self.avg_time_seconds, 3),
            "total_bytes": self.total_bytes,
            "total_mb": round(self.total_bytes / MB, 2),
            "avg_speed_mb_per_sec": round(self.avg_speed_mb_per_sec, 2),
            "avg_ttfb_seconds": round(
                statistics.fmean(s.ttfb_seconds for s in self.samples), 3
            ) if self.samples else 0.0,
        }


def fetch(url: str, timeout: float, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Sample:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        size = 0
        ttfb = None
        while chunk := response.read(chunk_size):
            if ttfb is None:
                ttfb = time.perf_counter() - start
            size += len(chunk)
    total = time.perf_counter() - start
    return Sample(size_bytes=size, ttfb_seconds=ttfb or total, total_seconds=total)


def iter_samples(
    url: str,
    count: int,
    timeout: float,
    retries: int = DEFAULT_RETRIES,
) -> Iterator[Sample]:
    failures = 0
    done = 0
    while done < count:
        try:
            sample = fetch(url, timeout)
        except (urllib.error.URLError, TimeoutError) as exc:
            failures += 1
            log.warning("request %d failed: %s", done + failures, exc)
            if failures >= retries:
                raise RuntimeError(
                    f"giving up after {failures} failed request(s): {exc}"
                ) from exc
            time.sleep(min(2 ** failures, 10) / 2)
            continue
        failures = 0
        done += 1
        yield sample


def run(url: str, count: int, timeout: float) -> Report:
    samples: list[Sample] = []
    failures = 0
    for i, sample in enumerate(iter_samples(url, count, timeout), start=1):
        samples.append(sample)
        log.info(
            "request %2d/%d: %8.2f MB in %6.2f s -> %8.2f MB/s",
            i, count, sample.size_bytes / MB,
            sample.total_seconds, sample.speed_mb_per_sec,
        )
    return Report(url=url, samples=samples, failures=failures)


def format_report(report: Report) -> str:
    lines = [
        f"URL                   : {report.url}",
        f"Successful requests   : {len(report.samples)}",
        f"Average request time  : {report.avg_time_seconds:.2f} s",
        f"Total downloaded      : {report.total_bytes / MB:.2f} MB",
        f"Average speed         : {report.avg_speed_mb_per_sec:.2f} MB/s "
        f"({report.avg_speed_mb_per_sec * 8:.1f} Mbit/s)",
    ]
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure download speed by fetching a URL several times.",
    )
    parser.add_argument("url", help="URL of a (large) file to download")
    parser.add_argument(
        "-n", "--requests", type=int, default=DEFAULT_REQUESTS,
        help=f"number of sequential requests (default: {DEFAULT_REQUESTS})",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT,
        help=f"per-request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument("--json", action="store_true", help="print JSON report")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="log every request",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )
    args = parser.parse_args(argv)
    if args.requests < 1:
        parser.error("--requests must be >= 1")
    if args.timeout <= 0:
        parser.error("--timeout must be > 0")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
    )
    try:
        report = run(args.url, args.requests, args.timeout)
    except (RuntimeError, urllib.error.URLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(format_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
