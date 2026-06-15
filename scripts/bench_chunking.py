# Copyright 2026 Christopher Barber
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Benchmark: lex-based vs regex-based chunking.

Generates many flat JSON objects (no nested braces, no braces inside strings, so
the lexer and a `\\{` regex split at exactly the same points) and compares the cost
of producing the chunks each way. Run with:

    pixi run python scripts/bench_chunking.py
"""

from __future__ import annotations

import importlib
import re
import sys
import time
from pathlib import Path
from typing import Any

from antlr_pyfacade import lex, split_on_pattern, split_on_token

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "json"))
_mod: Any = importlib.import_module("generated.JSONLexer")
JSONLexer = _mod.JSONLexer
LBRACE = JSONLexer.T__0  # '{'


def make_input(n: int) -> str:
    return "\n".join(
        f'{{"id": {i}, "name": "item-{i}", "value": {i * 1.5}}}' for i in range(n)
    )


def best(fn: Any, repeat: int = 5) -> float:
    """Best (minimum) wall-clock seconds over `repeat` runs of `fn`."""
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return min(times)


def bench_one(n: int) -> None:
    text = make_input(n)
    mb = len(text) / 1e6

    # Both chunkers must agree (flat objects -> identical split points).
    lex_chunks = [
        c.text for c in split_on_token(text, JSONLexer, LBRACE, where="before")
    ]
    rx_chunks = [c.text for c in split_on_pattern(text, r"\{", where="before")]
    assert lex_chunks == rx_chunks, "lex and regex chunkers disagree"

    print(f"\n{n:,} objects, {mb:.1f} MB, {len(lex_chunks):,} chunks")
    rows: list[tuple[str, Any]] = [
        ("lex() keep={LBRACE}", lambda: lex(text, JSONLexer, keep=[LBRACE])),
        ("re.finditer(r'\\{')", lambda: list(re.finditer(r"\{", text))),
        (
            "split_on_token  (full)",
            lambda: list(split_on_token(text, JSONLexer, LBRACE, where="before")),
        ),
        (
            "split_on_pattern(full)",
            lambda: list(split_on_pattern(text, r"\{", where="before")),
        ),
    ]
    for label, fn in rows:
        t = best(fn)
        print(f"  {label:24s} {t * 1e3:8.2f} ms   {mb / t:7.1f} MB/s")


def main() -> int:
    for n in (10_000, 50_000, 200_000):
        bench_one(n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
