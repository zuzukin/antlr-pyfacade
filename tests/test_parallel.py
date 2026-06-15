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

"""`walk_parallel` parses independent chunks across a thread pool, one listener
per chunk, in input order — the building block for parsing many independent
pieces (e.g. the top-level records or definitions of a document) concurrently.

These check correctness and ordering; the GIL-release parallelism itself is
covered by `test_threading.py`.
"""

from __future__ import annotations

import json

import pytest
from generated.JSONLexer import JSONLexer
from generated.JSONParser import JSONParser
from json_listener import JsonEventListener
from to_python import JsonValueBuilder

from antlr_pyfacade import Chunk

# A spread of independent JSON values, each parsed as the `value` sub-rule.
_CHUNKS = [
    '{"id": 1, "tags": ["a", "b"], "ok": true}',
    '{"id": 2, "nested": {"x": [1, 2, 3]}}',
    "[1, 2.5, -3, null, false]",
    '"a lone string"',
    "42",
    "{}",
    "[]",
    '{"unicode": "café 😀", "n": 7}',
]
_EXPECTED = [json.loads(c) for c in _CHUNKS]


def _serial(chunks, **kw):
    return [
        JsonValueBuilder().walk(c, JSONLexer, JSONParser, start_rule="value").result
        for c in chunks
    ]


def test_results_match_and_preserve_order():
    listeners = JsonValueBuilder.walk_parallel(
        _CHUNKS, JSONLexer, JSONParser, start_rule="value"
    )
    assert [ln.result for ln in listeners] == _EXPECTED


def test_parallel_matches_serial():
    listeners = JsonValueBuilder.walk_parallel(
        _CHUNKS, JSONLexer, JSONParser, start_rule="value"
    )
    assert [ln.result for ln in listeners] == _serial(_CHUNKS)


def test_start_rule_name_and_index_agree():
    value_idx = list(JsonValueBuilder.ruleNames).index("value")
    by_name = JsonValueBuilder.walk_parallel(
        _CHUNKS, JSONLexer, JSONParser, start_rule="value"
    )
    by_index = JsonValueBuilder.walk_parallel(
        _CHUNKS, JSONLexer, JSONParser, start_rule=value_idx
    )
    assert [ln.result for ln in by_name] == [ln.result for ln in by_index]


def test_single_worker_inline_path_matches_pool():
    pooled = JsonValueBuilder.walk_parallel(
        _CHUNKS, JSONLexer, JSONParser, start_rule="value", max_workers=4
    )
    inline = JsonValueBuilder.walk_parallel(
        _CHUNKS, JSONLexer, JSONParser, start_rule="value", max_workers=1
    )
    assert [ln.result for ln in pooled] == [ln.result for ln in inline]


def test_empty_chunks():
    assert list(JsonValueBuilder.walk_parallel([], JSONLexer, JSONParser)) == []


def test_factory_is_used_per_chunk():
    seen = []

    def factory():
        builder = JsonValueBuilder()
        seen.append(builder)
        return builder

    listeners = list(
        JsonValueBuilder.walk_parallel(
            _CHUNKS, JSONLexer, JSONParser, start_rule="value", factory=factory
        )
    )
    # One fresh listener per chunk, and the returned ones are exactly those made.
    assert len(seen) == len(_CHUNKS)
    assert set(map(id, seen)) == set(map(id, listeners))


def test_unknown_start_rule_raises():
    with pytest.raises(ValueError, match="unknown start rule"):
        JsonValueBuilder.walk_parallel(
            _CHUNKS, JSONLexer, JSONParser, start_rule="nonesuch"
        )


def test_syntax_errors_collected_per_chunk():
    chunks = ['{"good": 1}', "{bad", '{"also_good": 2}']
    listeners = list(
        JsonValueBuilder.walk_parallel(
            chunks, JSONLexer, JSONParser, start_rule="value"
        )
    )
    assert not listeners[0].syntax_errors
    assert listeners[1].syntax_errors  # malformed chunk reports its own errors
    assert not listeners[2].syntax_errors


class _PosRecorder(JsonEventListener):
    """Records each terminal's reported (line_col, span), keyed by token text."""

    def __init__(self) -> None:
        self.by_text: dict[str, tuple] = {}

    def visitTerminal(self, token_type: int, text: str) -> None:
        self.by_text[text] = (self.line_col(), self.span())


def test_source_positions_across_chunks():
    # walk_parallel yields lazily; list() materializes so the results can be indexed.
    # Bare strings are contiguous, so each chunk's start is computed from the
    # previous one. chunk 0 spans two lines; '22' begins chunk 0's second line and
    # '99' begins right after chunk 0.
    recs = list(
        _PosRecorder.walk_parallel(
            ["[1,\n22]", "99"], JSONLexer, JSONParser, start_rule="value"
        )
    )
    assert recs[0].by_text["22"] == ((2, 0), (4, 5))
    assert recs[1].by_text["99"] == ((2, 3), (7, 8))

    # A Chunk pins an explicit (offset, line, column), overriding the computed one.
    recs = list(
        _PosRecorder.walk_parallel(
            [Chunk("[1,\n22]"), Chunk("99", 100, 10, 5)],
            JSONLexer,
            JSONParser,
            start_rule="value",
        )
    )
    assert recs[1].by_text["99"] == ((10, 5), (100, 101))

    # A Chunk re-anchors the running position for the bare strings that follow it.
    recs = list(
        _PosRecorder.walk_parallel(
            [Chunk("99", 100, 10, 5), " 7"],
            JSONLexer,
            JSONParser,
            start_rule="value",
        )
    )
    assert recs[1].by_text["7"] == ((10, 8), (103, 103))

    # Unsupported chunk types are rejected (when the lazy stream is consumed).
    with pytest.raises(TypeError, match="str or Chunk"):
        list(
            _PosRecorder.walk_parallel([123], JSONLexer, JSONParser, start_rule="value")
        )
