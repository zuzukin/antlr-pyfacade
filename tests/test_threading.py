"""The native parse releases the GIL, so parses on separate threads run in
parallel instead of serializing.

Two checks:

* **Correctness under concurrency** — many ``walk`` calls across a thread pool,
  all sharing one cached spec, each rebuild the document correctly. (The shared
  ATN is thread-*safe*; see the note below about thread-*scaling*.)
* **Actual parallelism** — the pure-native ``parse_events`` region (the part that
  drops the GIL) runs measurably faster across threads than serially, when each
  thread uses its **own** spec. This is a timing assertion with a deliberately
  loose margin; it is skipped on a single-core host, where there is nothing to
  overlap.

Why per-thread specs for the timing check: the spec owns the deserialized ATN,
whose parser-prediction state is shared mutable data. Concurrent parses that
share one spec are *correct* but contend on it (the bundled lock-free patch only
covers the lexer's DFA edge reads, not the parser prediction path), so they do
not scale. ``load_specs(..., cached=False)`` gives each thread its own spec,
removing the shared state so the parses run in parallel — which is what proves
the GIL was released.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from antlr_pyfacade import load_specs, parse_events

from generated.JSONLexer import JSONLexer
from generated.JSONParser import JSONParser
from to_python import JsonValueBuilder

# Big enough that the native parse dominates per-call Python overhead.
_N_OBJECTS = 20_000
_BIG = (
    "["
    + ",".join(
        '{"id": %d, "name": "item-%d", "vals": [1, 2.5, true, null], "s": "abc"}'
        % (i, i)
        for i in range(_N_OBJECTS)
    )
    + "]"
)

_N_THREADS = 4
_N_TASKS = 2 * _N_THREADS


def _walk_once(_=None) -> int:
    builder = JsonValueBuilder()
    builder.walk(_BIG, JSONLexer, JSONParser)
    return len(builder.result)


_thread_local = threading.local()


def _native_parse_own_specs(_=None) -> int:
    # cached=False gives this worker its own ATN; threading.local builds it once.
    specs = getattr(_thread_local, "specs", None)
    if specs is None:
        specs = _thread_local.specs = load_specs(
            JSONLexer, JSONParser, cached=False
        )
    parser_spec, lexer_spec = specs
    raw, errors = parse_events(parser_spec, lexer_spec, _BIG, 0, None, None)
    assert not errors
    return len(raw)


def _best_of(fn, trials: int = 3) -> float:
    best = float("inf")
    for _ in range(trials):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


def test_concurrent_walks_are_correct():
    """Parses run on a thread pool (sharing one cached spec) stay correct."""
    # load_specs is cached, so every walk here shares one ATN — exercising the
    # thread-safety of concurrent access to it.
    load_specs(JSONLexer, JSONParser)
    with ThreadPoolExecutor(max_workers=_N_THREADS) as pool:
        sizes = list(pool.map(_walk_once, range(_N_TASKS)))
    assert sizes == [_N_OBJECTS] * _N_TASKS


@pytest.mark.skipif(
    (os.cpu_count() or 1) < 2, reason="needs >= 2 cores to overlap parses"
)
def test_native_parse_parallelizes_with_independent_specs():
    """With per-thread specs, the GIL-released native parse overlaps across cores.

    If the GIL were held for the whole parse, the threaded run would be no faster
    than serial (speedup ~ 1.0, in fact worse from overhead). With it released
    and independent specs on >= 2 cores the parses run in parallel; require a
    conservative 1.3x so this is a robust signal, not a flaky micro-benchmark.
    """

    def serial() -> None:
        for _ in range(_N_TASKS):
            _native_parse_own_specs()

    def threaded() -> None:
        with ThreadPoolExecutor(max_workers=_N_THREADS) as pool:
            list(pool.map(_native_parse_own_specs, range(_N_TASKS)))

    serial_s = _best_of(serial)
    threaded_s = _best_of(threaded)
    speedup = serial_s / threaded_s
    assert speedup > 1.3, (
        f"native parse did not run in parallel: speedup={speedup:.2f}x "
        f"(serial={serial_s * 1e3:.0f}ms, threaded={threaded_s * 1e3:.0f}ms)"
    )
