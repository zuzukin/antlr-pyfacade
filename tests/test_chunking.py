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

"""Token-based chunking: the C++ lexer pass (`lex`) and the `split_*` chunkers
that turn a whole source into positioned `Chunk`s for `walk_parallel`."""

from __future__ import annotations

import io
import re

import pytest
from generated.JSONLexer import JSONLexer
from generated.JSONParser import JSONParser
from to_python import JsonValueBuilder

from antlrope import (
    Chunk,
    LexToken,
    SourceMap,
    _native,
)

# Token types from the generated lexer's class constants (the reliable source —
# the literals are T__n in vocabulary order: '{' '}' '[' ']' ':').
LBRACE = JSONLexer.T__0  # '{'
RBRACE = JSONLexer.T__2  # '}'
LBRACK = JSONLexer.T__4  # '['
RBRACK = JSONLexer.T__5  # ']'
COLON = JSONLexer.T__3  # ':'
STRING = JSONLexer.STRING
NUMBER = JSONLexer.NUMBER


def test_lex():
    text = '{"a": 1}\n[2]'
    toks = list(
        JsonValueBuilder.lex(text)
    )  # lex is lazy; materialize to index/reiterate

    # Tokens in source order, EOF omitted; whitespace is `-> skip` so absent.
    assert [t.type for t in toks] == [
        LBRACE,
        STRING,
        COLON,
        NUMBER,
        RBRACE,
        LBRACK,
        NUMBER,
        RBRACK,
    ]
    assert isinstance(toks[0], LexToken)
    # Offsets slice back to the token text; all on the default channel.
    assert text[toks[1].start : toks[1].stop + 1] == '"a"'
    assert next(t for t in toks if t.type == LBRACK).start == 9  # '[' starts line 2
    assert all(t.channel == 0 for t in toks)

    # keep= filters to the requested types in C++ (only those cross into Python).
    assert [t.type for t in JsonValueBuilder.lex(text, keep=(NUMBER,))] == [
        NUMBER,
        NUMBER,
    ]


def test_split_on_token():
    text = '{"a": 1}\n{"b": 22}\n{"c": 3}'

    # `before`: each '{' starts a chunk; positions track the whole source.
    chunks = list(JsonValueBuilder.split_on_token(text, LBRACE, where="before"))
    assert [c.text for c in chunks] == ['{"a": 1}', '{"b": 22}', '{"c": 3}']
    assert [(c.offset, c.line, c.column) for c in chunks] == [
        (0, 1, 0),
        (9, 2, 0),
        (19, 3, 0),
    ]

    # The chunks drop straight into walk_parallel and reconstruct each value.
    results = [
        b.result for b in JsonValueBuilder.walk_parallel(chunks, start_rule="value")
    ]
    assert results == [{"a": 1}, {"b": 22}, {"c": 3}]

    # `after`: each chunk ends with the delimiter (here the '}').
    after = list(JsonValueBuilder.split_on_token(text, RBRACE, where="after"))
    assert [c.text for c in after] == ['{"a": 1}', '{"b": 22}', '{"c": 3}']

    # Content before the first delimiter becomes a leading chunk (`before`).
    lead = list(JsonValueBuilder.split_on_token('1 {"x": 2}', LBRACE, where="before"))
    assert [c.text for c in lead] == ["1", '{"x": 2}']

    # Multiple delimiter types: split before either '{' or '['.
    mixed = '{"a": 1} [2, 3] {"b": 4}'
    multi = list(
        JsonValueBuilder.split_on_token(mixed, [LBRACE, LBRACK], where="before")
    )
    assert [c.text for c in multi] == ['{"a": 1}', "[2, 3]", '{"b": 4}']

    with pytest.raises(ValueError, match="where"):
        list(JsonValueBuilder.split_on_token(text, LBRACE, where="sideways"))


# (text, delimiter, where) cases exercising the streaming chunker against the
# in-memory split_on_token oracle: leading/trailing regions, whitespace trimming
# and whitespace-only skips, adjacent delimiters, a single chunk, zero
# delimiters, multibyte UTF-8, and several delimiter types.
_STREAM_CASES = [
    ('{"a": 1}\n{"b": 22}\n{"c": 3}', LBRACE, "before"),
    ('{"a": 1}\n{"b": 22}\n{"c": 3}', RBRACE, "after"),
    ('1 {"x": 2}', LBRACE, "before"),
    ('{"x": 2} trailing', RBRACE, "after"),
    ('   \n {"a":1}  \n  {"b":2}  \n ', LBRACE, "before"),
    ('{"a":1}{"b":2}', LBRACE, "before"),
    ('{"a":1}', LBRACE, "before"),
    ("no delimiters here", LBRACE, "before"),
    ('{"café": 1}\n{"日本語": 2}\n{"emoji": "😀🚀"}', LBRACE, "before"),
    ('{"a": 1} [2, 3] {"b": 4}', [LBRACE, LBRACK], "before"),
]


def test_stream_on_token(tmp_path):
    # stream_on_token reads the file incrementally but must reproduce
    # split_on_token's output exactly — across block sizes, so multi-byte
    # sequences and chunk boundaries straddle the read window (_block_bytes forces
    # tiny reads; 0 is the production 64 KiB block).
    for i, (text, delim, where) in enumerate(_STREAM_CASES):
        path = tmp_path / f"case{i}.json"
        path.write_text(text, encoding="utf-8")
        want = [
            (c.text, c.offset, c.line, c.column)
            for c in JsonValueBuilder.split_on_token(text, delim, where=where)
        ]
        for block in (0, 1, 2, 3, 4, 7):
            got = [
                (c.text, c.offset, c.line, c.column)
                for c in JsonValueBuilder.stream_on_token(
                    path, delim, where=where, _block_bytes=block
                )
            ]
            assert got == want, (text, where, block)

    path = tmp_path / "values.json"
    path.write_text('{"a": 1}\n{"b": 2}', encoding="utf-8")

    # channel=None considers all channels (here all default-channel, so unchanged).
    assert [
        c.text for c in JsonValueBuilder.stream_on_token(path, LBRACE, channel=None)
    ] == [
        '{"a": 1}',
        '{"b": 2}',
    ]

    # The streamed chunks drop straight into walk_parallel and reconstruct values.
    chunks = list(JsonValueBuilder.stream_on_token(path, LBRACE, where="before"))
    results = [
        b.result for b in JsonValueBuilder.walk_parallel(chunks, start_rule="value")
    ]
    assert results == [{"a": 1}, {"b": 2}]

    with pytest.raises(ValueError, match="where"):
        list(JsonValueBuilder.stream_on_token(path, LBRACE, where="sideways"))


def test_stream_on_token_encoding_and_errors(tmp_path):
    path = tmp_path / "ok.json"
    path.write_text('{"a": 1}\n{"b": 2}', encoding="utf-8")

    # Python codec aliases for UTF-8 are accepted; any other encoding is rejected
    # (decode in Python and use split_on_token for those).
    for enc in ("utf-8", "utf8", "UTF-8", "U8"):
        assert [
            c.text for c in JsonValueBuilder.stream_on_token(path, LBRACE, encoding=enc)
        ] == ['{"a": 1}', '{"b": 2}']
    with pytest.raises(ValueError, match="UTF-8"):
        list(JsonValueBuilder.stream_on_token(path, LBRACE, encoding="latin-1"))

    # A missing file surfaces as an error from the native layer.
    with pytest.raises(RuntimeError):
        list(JsonValueBuilder.stream_on_token(tmp_path / "nope.json", LBRACE))

    # Invalid UTF-8: lenient (stream_on_token's default) substitutes U+FFFD and
    # keeps going; strict (via the native chunker directly) raises.
    bad = tmp_path / "bad.json"
    bad.write_bytes(b'{"a": "\xff\xfe"}\n{"b": 2}')
    lenient = [
        c.text for c in JsonValueBuilder.stream_on_token(bad, LBRACE, where="before")
    ]
    assert "�" in lenient[0]
    assert lenient[1] == '{"b": 2}'

    spec = JsonValueBuilder.lexer_spec()
    strict = _native.StreamChunker(spec, str(bad), [LBRACE], 0, 0, False, True, 0)
    with pytest.raises(RuntimeError):
        strict.next_batch(10)


# (text, pattern, flags, where) cases for the streaming regex chunker, checked
# against split_on_pattern: leading/trailing/whitespace regions, multi-character
# and line-anchored (MULTILINE) delimiters, multibyte, and no delimiter.
_PATTERN_CASES = [
    ('{"a": 1}\n{"b": 22}\n{"c": 3}', r"\{", 0, "before"),
    ('{"a": 1}\n{"b": 22}\n{"c": 3}', r"\}", 0, "after"),
    ("1 {2} {3}", r"\{", 0, "before"),
    ("a;; b;; c", r";;", 0, "after"),
    ("--\nrec1\n--\nrec2\n--\nrec3\n", r"^--$", re.MULTILINE, "before"),
    ('{"café": 1}\n{"日本語": 2}\n{"emoji": "😀🚀"}', r"\{", 0, "before"),
    ("   \n {a}  \n  {b}  \n ", r"\{", 0, "before"),
    ("no delimiters here", r"\{", 0, "before"),
    ("", r"\{", 0, "before"),
]


def test_stream_on_pattern(tmp_path):
    # stream_on_pattern reads incrementally but must reproduce split_on_pattern
    # over the same text — from a path, an open stream, or an iterable, and across
    # window sizes small enough that multi-character delimiters straddle reads.
    for i, (text, pat, flags, where) in enumerate(_PATTERN_CASES):
        path = tmp_path / f"p{i}.txt"
        path.write_text(text, encoding="utf-8")
        want = [
            (c.text, c.offset, c.line, c.column)
            for c in JsonValueBuilder.split_on_pattern(
                text, pat, where=where, flags=flags
            )
        ]

        def run(source, pat=pat, where=where, flags=flags, **kw):
            return [
                (c.text, c.offset, c.line, c.column)
                for c in JsonValueBuilder.stream_on_pattern(
                    source, pat, where=where, flags=flags, **kw
                )
            ]

        for wc in (1, 2, 3, 65536):
            assert run(path, window_chars=wc) == want, (text, where, wc)
        assert run(io.StringIO(text), window_chars=2) == want  # open stream
        assert run(text.splitlines(keepends=True)) == want  # iterable of lines
        assert run(path, window_lines=1) == want  # line windows

    # The streamed chunks feed walk_parallel like any other chunker.
    path = tmp_path / "values.txt"
    path.write_text('{"a": 1}\n{"b": 2}', encoding="utf-8")
    results = [
        b.result
        for b in JsonValueBuilder.walk_parallel(
            JsonValueBuilder.stream_on_pattern(path, r"\{", where="before"),
            start_rule="value",
        )
    ]
    assert results == [{"a": 1}, {"b": 2}]

    with pytest.raises(ValueError, match="where"):
        list(
            JsonValueBuilder.stream_on_pattern(io.StringIO("x"), r"a", where="sideways")
        )


def test_stream_on_pattern_encoding(tmp_path):
    # The regex runs on Python's side, so any encoding a text file supports works
    # (Python decodes); offsets match split_on_pattern over the decoded text.
    text = '{"café": 1}\n{"naïve": 2}\n{"x": 3}'
    for enc in ("latin-1", "utf-16", "cp1252"):
        path = tmp_path / f"{enc}.txt"
        path.write_text(text, encoding=enc)
        want = [
            (c.text, c.offset, c.line, c.column)
            for c in JsonValueBuilder.split_on_pattern(text, r"\{", where="before")
        ]
        got = [
            (c.text, c.offset, c.line, c.column)
            for c in JsonValueBuilder.stream_on_pattern(
                path, r"\{", where="before", encoding=enc, window_chars=3
            )
        ]
        assert got == want, enc


def test_trim(tmp_path):
    # trim=False keeps each region verbatim (only zero-length regions are dropped),
    # so a record's mandatory whitespace terminator survives the split; trim=True
    # (the default) strips surrounding whitespace and drops whitespace-only regions.
    # The native streamers must honor trim= identically to their in-memory oracles.
    text = '{"a":1}  \n  {"b":2}  \n '  # '}' at offsets 6 and 18
    path = tmp_path / "v.json"
    path.write_text(text, encoding="utf-8")

    # token-based, where="after": each chunk ends just past a '}'.
    assert [
        c.text for c in JsonValueBuilder.split_on_token(text, RBRACE, where="after")
    ] == ['{"a":1}', '{"b":2}']
    raw = list(JsonValueBuilder.split_on_token(text, RBRACE, where="after", trim=False))
    assert [c.text for c in raw] == ['{"a":1}', '  \n  {"b":2}', "  \n "]
    # offsets/lines still index the original source — no shift from a skipped strip.
    assert [(c.offset, c.line, c.column) for c in raw] == [
        (0, 1, 0),
        (7, 1, 7),
        (19, 2, 9),
    ]
    assert raw[-1].text.endswith("\n ")  # trailing whitespace-only region preserved

    # the native stream_on_token reproduces that trim=False output exactly, across
    # block sizes that straddle the trailing-whitespace regions.
    want = [(c.text, c.offset, c.line, c.column) for c in raw]
    for block in (0, 1, 2, 3, 7):
        got = [
            (c.text, c.offset, c.line, c.column)
            for c in JsonValueBuilder.stream_on_token(
                path, RBRACE, where="after", trim=False, _block_bytes=block
            )
        ]
        assert got == want, block

    # pattern-based: split_on_pattern and its native streamer agree with trim=False.
    pat = [
        c.text
        for c in JsonValueBuilder.split_on_pattern(
            text, r"\}", where="after", trim=False
        )
    ]
    assert pat == ['{"a":1}', '  \n  {"b":2}', "  \n "]
    for wc in (1, 2, 3, 65536):
        got = [
            c.text
            for c in JsonValueBuilder.stream_on_pattern(
                path, r"\}", where="after", trim=False, window_chars=wc
            )
        ]
        assert got == pat, wc

    # chunk_by_pattern: a record pattern that also captures the trailing whitespace
    # keeps it only with trim=False.
    rec = r"\{[^}]*\}\s*"
    assert [c.text for c in JsonValueBuilder.chunk_by_pattern(text, rec)] == [
        '{"a":1}',
        '{"b":2}',
    ]
    assert [
        c.text for c in JsonValueBuilder.chunk_by_pattern(text, rec, trim=False)
    ] == ['{"a":1}  \n  ', '{"b":2}  \n ']


def test_sourcename(tmp_path):
    # Every chunker can record a source name on each Chunk. The streaming chunkers
    # default it to the file path; an explicit `sourcename` overrides (and is the
    # only way to name a path-less stream).
    path = tmp_path / "data.json"
    path.write_text('{"a": 1}\n{"b": 2}', encoding="utf-8")
    text = path.read_text(encoding="utf-8")

    assert next(JsonValueBuilder.stream_on_pattern(path, r"\{")).sourcename == str(path)
    assert not next(
        JsonValueBuilder.stream_on_pattern(io.StringIO(text), r"\{")
    ).sourcename
    assert (
        next(
            JsonValueBuilder.stream_on_pattern(io.StringIO(text), r"\{", sourcename="m")
        ).sourcename
        == "m"
    )
    assert (
        next(
            JsonValueBuilder.stream_on_pattern(path, r"\{", sourcename="alias")
        ).sourcename
        == "alias"
    )
    assert next(JsonValueBuilder.stream_on_token(path, LBRACE)).sourcename == str(path)
    assert (
        next(
            JsonValueBuilder.stream_on_token(path, LBRACE, sourcename="alias")
        ).sourcename
        == "alias"
    )

    # The in-memory chunkers take it too (None by default).
    assert not next(JsonValueBuilder.split_on_token(text, LBRACE)).sourcename
    assert (
        next(JsonValueBuilder.split_on_token(text, LBRACE, sourcename="s")).sourcename
        == "s"
    )
    assert (
        next(JsonValueBuilder.split_on_pattern(text, r"\{", sourcename="s")).sourcename
        == "s"
    )
    assert (
        next(
            JsonValueBuilder.chunk_by_pattern(text, r"\{[^{}]*\}", sourcename="s")
        ).sourcename
        == "s"
    )
    assert (
        next(
            JsonValueBuilder.split_between_tokens(
                text, (LBRACE, RBRACE), sourcename="s"
            )
        ).sourcename
        == "s"
    )
    assert (
        next(
            JsonValueBuilder.chunk_by_rule('[{"a": 1}]', "obj", sourcename="s")
        ).sourcename
        == "s"
    )

    # A bare str chunk inherits the source name of the chunk it follows.
    assert Chunk("x", 0, 1, 0, "src").after("yy").sourcename == "src"

    # The name surfaces as FacadeListener.sourcename() during the walk, for
    # reporting positions as sourcename:line:column.
    listeners = list(
        JsonValueBuilder.walk_parallel(
            JsonValueBuilder.stream_on_pattern(
                io.StringIO(text), r"\{", sourcename="mem.json"
            ),
            start_rule="value",
        )
    )
    assert [b.result for b in listeners] == [{"a": 1}, {"b": 2}]
    assert [b.sourcename() for b in listeners] == ["mem.json", "mem.json"]


def test_split_between_tokens():
    # One chunk per '{'..'}' region; the pair is a tuple of token types (each side
    # may also be a set of equivalent types).
    text = '{"a": 1} {"b": 2}'
    assert [
        c.text for c in JsonValueBuilder.split_between_tokens(text, (LBRACE, RBRACE))
    ] == [
        '{"a": 1}',
        '{"b": 2}',
    ]
    assert [
        c.text
        for c in JsonValueBuilder.split_between_tokens(text, ({LBRACE}, {RBRACE}))
    ] == ['{"a": 1}', '{"b": 2}']

    # Nested vs non-nested: non-nested pairs each opener with the next closer;
    # nested matches balanced pairs and emits the outermost regions.
    src = "[1,[2,3]] [4,[5,[6]]]"
    assert [
        c.text for c in JsonValueBuilder.split_between_tokens(src, (LBRACK, RBRACK))
    ] == [
        "[1,[2,3]",
        "[4,[5,[6]",
    ]
    assert [
        c.text
        for c in JsonValueBuilder.split_between_tokens(
            src, (LBRACK, RBRACK), nested=True
        )
    ] == ["[1,[2,3]]", "[4,[5,[6]]]"]

    # An unmatched trailing opener yields nothing extra.
    assert [
        c.text
        for c in JsonValueBuilder.split_between_tokens("[1] [2", (LBRACK, RBRACK))
    ] == ["[1]"]

    # Multiple distinct pairs: '{}' and '[]' each match only their own partner, so
    # mixed/nested brackets match correctly.
    mixed = '{"a": [1, 2]} [3, {"b": 4}]'
    pairs = [(LBRACE, RBRACE), (LBRACK, RBRACK)]
    assert [
        c.text for c in JsonValueBuilder.split_between_tokens(mixed, pairs, nested=True)
    ] == ['{"a": [1, 2]}', '[3, {"b": 4}]']


def test_pattern_chunkers():
    # Regex chunkers need no grammar/lexer — they work on the raw text.
    text = '{"a": 1}\n{"b": 22}\n{"c": 3}'

    # split_on_pattern mirrors split_on_token: split before each '{', positions
    # tracked against the whole source.
    before = list(JsonValueBuilder.split_on_pattern(text, r"\{", where="before"))
    assert [c.text for c in before] == ['{"a": 1}', '{"b": 22}', '{"c": 3}']
    assert [(c.offset, c.line, c.column) for c in before] == [
        (0, 1, 0),
        (9, 2, 0),
        (19, 3, 0),
    ]
    after = list(JsonValueBuilder.split_on_pattern(text, r"\}", where="after"))
    assert [c.text for c in after] == ['{"a": 1}', '{"b": 22}', '{"c": 3}']

    # chunk_by_pattern: each match is one chunk (the pattern matches a record).
    objs = list(JsonValueBuilder.chunk_by_pattern(text, r"\{[^{}]*\}"))
    assert [c.text for c in objs] == ['{"a": 1}', '{"b": 22}', '{"c": 3}']

    with pytest.raises(ValueError, match="where"):
        list(JsonValueBuilder.split_on_pattern(text, r"\{", where="sideways"))


def test_chunk_by_rule():
    text = '[{"a": 1},\n {"b": [2, 3]},\n {"c": 4}]'

    # Each top-level 'obj' rule occurrence is a chunk, positioned in the source.
    chunks = list(JsonValueBuilder.chunk_by_rule(text, "obj"))
    assert [c.text for c in chunks] == ['{"a": 1}', '{"b": [2, 3]}', '{"c": 4}']
    assert all(text[c.offset : c.offset + len(c.text)] == c.text for c in chunks)
    assert chunks[1].line == 2  # the second object begins on line 2

    # The chunks drop straight into walk_parallel and reconstruct each value.
    results = [
        b.result for b in JsonValueBuilder.walk_parallel(chunks, start_rule="value")
    ]
    assert results == [{"a": 1}, {"b": [2, 3]}, {"c": 4}]

    # outermost (default) keeps only top-level matches; outermost=False includes
    # nested ones (which overlap).
    nested = '{"x": {"y": 1}}'
    assert [c.text for c in JsonValueBuilder.chunk_by_rule(nested, "obj")] == [
        '{"x": {"y": 1}}'
    ]
    assert [
        c.text for c in JsonValueBuilder.chunk_by_rule(nested, "obj", outermost=False)
    ] == ['{"x": {"y": 1}}', '{"y": 1}']

    # A rule index and an explicit start_rule agree with the name form.
    obj_idx = list(JSONParser.ruleNames).index("obj")
    assert [
        c.text for c in JsonValueBuilder.chunk_by_rule(text, obj_idx, start_rule="json")
    ] == ['{"a": 1}', '{"b": [2, 3]}', '{"c": 4}']

    with pytest.raises(ValueError, match="unknown rule"):
        list(JsonValueBuilder.chunk_by_rule(text, "nonesuch"))


def _positions_ok(text, chunks):
    """Each chunk's text sits at its offset, and (line, column) matches a SourceMap
    over the whole text — an authoritative position oracle."""
    sm = SourceMap(text)
    for c in chunks:
        assert text[c.offset : c.offset + len(c.text)] == c.text
        assert (c.line, c.column) == sm.line_col(c.offset)


def test_stream_by_rule(tmp_path):
    # The JSON lexer `-> skip`s whitespace, so a file of whitespace-separated values
    # is a valid sequence of `value` records.
    text = '{"a": 1}\n{"b": 2}\n[1, 2, 3]'
    path = tmp_path / "seq.json"
    path.write_text(text, encoding="utf-8")

    expect = ['{"a": 1}', '{"b": 2}', "[1, 2, 3]"]
    # Parse one record at a time; identical across read-block sizes (the streaming
    # window straddles records/codepoints), and positions match the whole-text map.
    for block in (0, 1, 2, 3, 7):
        chunks = list(
            JsonValueBuilder.stream_by_rule(path, "value", _block_bytes=block)
        )
        assert [c.text for c in chunks] == expect, block
        _positions_ok(text, chunks)

    # A set of candidate rules: the next token picks which to parse ('{' -> obj,
    # '[' -> arr), so disjoint leading tokens dispatch unambiguously.
    objarr = list(JsonValueBuilder.stream_by_rule(path, ["obj", "arr"]))
    assert [c.text for c in objarr] == expect
    _positions_ok(text, objarr)

    # Multibyte records: offsets are codepoints, positions stay exact.
    mb = '{"café": 1}\n{"emoji": "😀🚀"}'
    mbpath = tmp_path / "mb.json"
    mbpath.write_text(mb, encoding="utf-8")
    mbchunks = list(JsonValueBuilder.stream_by_rule(mbpath, "value", _block_bytes=2))
    assert [c.text for c in mbchunks] == ['{"café": 1}', '{"emoji": "😀🚀"}']
    _positions_ok(mb, mbchunks)

    # The records drop straight into walk_parallel and reconstruct each value.
    results = [
        b.result
        for b in JsonValueBuilder.walk_parallel(
            JsonValueBuilder.stream_by_rule(path, "value"),
            start_rule="value",
        )
    ]
    assert results == [{"a": 1}, {"b": 2}, [1, 2, 3]]

    with pytest.raises(ValueError, match="unknown rule"):
        list(JsonValueBuilder.stream_by_rule(path, "nonesuch"))


def test_stream_by_rule_stop_and_errors(tmp_path):
    # The stream stops at the first token that begins no candidate rule: here a bare
    # STRING is neither obj nor arr, so only the leading object is yielded.
    path = tmp_path / "loose.json"
    path.write_text('{"a": 1} "loose" {"b": 2}', encoding="utf-8")
    assert [c.text for c in JsonValueBuilder.stream_by_rule(path, ["obj", "arr"])] == [
        '{"a": 1}'
    ]

    # sourcename defaults to the path and is overridable.
    seq = tmp_path / "s.json"
    seq.write_text('{"a": 1} {"b": 2}', encoding="utf-8")
    assert next(JsonValueBuilder.stream_by_rule(seq, "value")).sourcename == str(seq)
    assert (
        next(JsonValueBuilder.stream_by_rule(seq, "value", sourcename="x")).sourcename
        == "x"
    )

    # A missing file surfaces as an error from the native layer; non-UTF-8 rejected.
    with pytest.raises(RuntimeError):
        list(JsonValueBuilder.stream_by_rule(tmp_path / "nope.json", "value"))
    with pytest.raises(ValueError, match="UTF-8"):
        list(JsonValueBuilder.stream_by_rule(seq, "value", encoding="latin-1"))
