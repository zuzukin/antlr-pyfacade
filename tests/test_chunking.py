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

import pytest
from generated.JSONLexer import JSONLexer
from generated.JSONParser import JSONParser
from to_python import JsonValueBuilder

from antlr_pyfacade import (
    LexToken,
    _native,
    chunk_by_pattern,
    chunk_by_rule,
    lex,
    load_lexer_spec,
    split_between_tokens,
    split_on_pattern,
    split_on_token,
    stream_on_token,
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
    toks = list(lex(text, JSONLexer))  # lex is lazy; materialize to index/reiterate

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
    assert [t.type for t in lex(text, JSONLexer, keep=(NUMBER,))] == [NUMBER, NUMBER]


def test_split_on_token():
    text = '{"a": 1}\n{"b": 22}\n{"c": 3}'

    # `before`: each '{' starts a chunk; positions track the whole source.
    chunks = list(split_on_token(text, JSONLexer, LBRACE, where="before"))
    assert [c.text for c in chunks] == ['{"a": 1}', '{"b": 22}', '{"c": 3}']
    assert [(c.offset, c.line, c.column) for c in chunks] == [
        (0, 1, 0),
        (9, 2, 0),
        (19, 3, 0),
    ]

    # The chunks drop straight into walk_parallel and reconstruct each value.
    results = [
        b.result
        for b in JsonValueBuilder.walk_parallel(
            chunks, JSONLexer, JSONParser, start_rule="value"
        )
    ]
    assert results == [{"a": 1}, {"b": 22}, {"c": 3}]

    # `after`: each chunk ends with the delimiter (here the '}').
    after = list(split_on_token(text, JSONLexer, RBRACE, where="after"))
    assert [c.text for c in after] == ['{"a": 1}', '{"b": 22}', '{"c": 3}']

    # Content before the first delimiter becomes a leading chunk (`before`).
    lead = list(split_on_token('1 {"x": 2}', JSONLexer, LBRACE, where="before"))
    assert [c.text for c in lead] == ["1", '{"x": 2}']

    # Multiple delimiter types: split before either '{' or '['.
    mixed = '{"a": 1} [2, 3] {"b": 4}'
    multi = list(split_on_token(mixed, JSONLexer, [LBRACE, LBRACK], where="before"))
    assert [c.text for c in multi] == ['{"a": 1}', "[2, 3]", '{"b": 4}']

    with pytest.raises(ValueError, match="where"):
        list(split_on_token(text, JSONLexer, LBRACE, where="sideways"))


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
            for c in split_on_token(text, JSONLexer, delim, where=where)
        ]
        for block in (0, 1, 2, 3, 4, 7):
            got = [
                (c.text, c.offset, c.line, c.column)
                for c in stream_on_token(
                    path, JSONLexer, delim, where=where, _block_bytes=block
                )
            ]
            assert got == want, (text, where, block)

    path = tmp_path / "values.json"
    path.write_text('{"a": 1}\n{"b": 2}', encoding="utf-8")

    # channel=None considers all channels (here all default-channel, so unchanged).
    assert [
        c.text for c in stream_on_token(path, JSONLexer, LBRACE, channel=None)
    ] == ['{"a": 1}', '{"b": 2}']

    # The streamed chunks drop straight into walk_parallel and reconstruct values.
    chunks = list(stream_on_token(path, JSONLexer, LBRACE, where="before"))
    results = [
        b.result
        for b in JsonValueBuilder.walk_parallel(
            chunks, JSONLexer, JSONParser, start_rule="value"
        )
    ]
    assert results == [{"a": 1}, {"b": 2}]

    with pytest.raises(ValueError, match="where"):
        list(stream_on_token(path, JSONLexer, LBRACE, where="sideways"))


def test_stream_on_token_encoding_and_errors(tmp_path):
    path = tmp_path / "ok.json"
    path.write_text('{"a": 1}\n{"b": 2}', encoding="utf-8")

    # Python codec aliases for UTF-8 are accepted; any other encoding is rejected
    # (decode in Python and use split_on_token for those).
    for enc in ("utf-8", "utf8", "UTF-8", "U8"):
        assert [
            c.text for c in stream_on_token(path, JSONLexer, LBRACE, encoding=enc)
        ] == ['{"a": 1}', '{"b": 2}']
    with pytest.raises(ValueError, match="UTF-8"):
        list(stream_on_token(path, JSONLexer, LBRACE, encoding="latin-1"))

    # A missing file surfaces as an error from the native layer.
    with pytest.raises(RuntimeError):
        list(stream_on_token(tmp_path / "nope.json", JSONLexer, LBRACE))

    # Invalid UTF-8: lenient (stream_on_token's default) substitutes U+FFFD and
    # keeps going; strict (via the native chunker directly) raises.
    bad = tmp_path / "bad.json"
    bad.write_bytes(b'{"a": "\xff\xfe"}\n{"b": 2}')
    lenient = [c.text for c in stream_on_token(bad, JSONLexer, LBRACE, where="before")]
    assert "�" in lenient[0]
    assert lenient[1] == '{"b": 2}'

    spec = load_lexer_spec(JSONLexer)
    strict = _native.StreamChunker(spec, str(bad), [LBRACE], 0, 0, False, 0)
    with pytest.raises(RuntimeError):
        strict.next_batch(10)


def test_split_between_tokens():
    # One chunk per '{'..'}' region; the pair is a tuple of token types (each side
    # may also be a set of equivalent types).
    text = '{"a": 1} {"b": 2}'
    assert [
        c.text for c in split_between_tokens(text, JSONLexer, (LBRACE, RBRACE))
    ] == [
        '{"a": 1}',
        '{"b": 2}',
    ]
    assert [
        c.text for c in split_between_tokens(text, JSONLexer, ({LBRACE}, {RBRACE}))
    ] == ['{"a": 1}', '{"b": 2}']

    # Nested vs non-nested: non-nested pairs each opener with the next closer;
    # nested matches balanced pairs and emits the outermost regions.
    src = "[1,[2,3]] [4,[5,[6]]]"
    assert [c.text for c in split_between_tokens(src, JSONLexer, (LBRACK, RBRACK))] == [
        "[1,[2,3]",
        "[4,[5,[6]",
    ]
    assert [
        c.text
        for c in split_between_tokens(src, JSONLexer, (LBRACK, RBRACK), nested=True)
    ] == ["[1,[2,3]]", "[4,[5,[6]]]"]

    # An unmatched trailing opener yields nothing extra.
    assert [
        c.text for c in split_between_tokens("[1] [2", JSONLexer, (LBRACK, RBRACK))
    ] == ["[1]"]

    # Multiple distinct pairs: '{}' and '[]' each match only their own partner, so
    # mixed/nested brackets match correctly.
    mixed = '{"a": [1, 2]} [3, {"b": 4}]'
    pairs = [(LBRACE, RBRACE), (LBRACK, RBRACK)]
    assert [
        c.text for c in split_between_tokens(mixed, JSONLexer, pairs, nested=True)
    ] == ['{"a": [1, 2]}', '[3, {"b": 4}]']


def test_pattern_chunkers():
    # Regex chunkers need no grammar/lexer — they work on the raw text.
    text = '{"a": 1}\n{"b": 22}\n{"c": 3}'

    # split_on_pattern mirrors split_on_token: split before each '{', positions
    # tracked against the whole source.
    before = list(split_on_pattern(text, r"\{", where="before"))
    assert [c.text for c in before] == ['{"a": 1}', '{"b": 22}', '{"c": 3}']
    assert [(c.offset, c.line, c.column) for c in before] == [
        (0, 1, 0),
        (9, 2, 0),
        (19, 3, 0),
    ]
    after = list(split_on_pattern(text, r"\}", where="after"))
    assert [c.text for c in after] == ['{"a": 1}', '{"b": 22}', '{"c": 3}']

    # chunk_by_pattern: each match is one chunk (the pattern matches a record).
    objs = list(chunk_by_pattern(text, r"\{[^{}]*\}"))
    assert [c.text for c in objs] == ['{"a": 1}', '{"b": 22}', '{"c": 3}']

    with pytest.raises(ValueError, match="where"):
        list(split_on_pattern(text, r"\{", where="sideways"))


def test_chunk_by_rule():
    text = '[{"a": 1},\n {"b": [2, 3]},\n {"c": 4}]'

    # Each top-level 'obj' rule occurrence is a chunk, positioned in the source.
    chunks = list(chunk_by_rule(text, JSONLexer, JSONParser, "obj"))
    assert [c.text for c in chunks] == ['{"a": 1}', '{"b": [2, 3]}', '{"c": 4}']
    assert all(text[c.offset : c.offset + len(c.text)] == c.text for c in chunks)
    assert chunks[1].line == 2  # the second object begins on line 2

    # The chunks drop straight into walk_parallel and reconstruct each value.
    results = [
        b.result
        for b in JsonValueBuilder.walk_parallel(
            chunks, JSONLexer, JSONParser, start_rule="value"
        )
    ]
    assert results == [{"a": 1}, {"b": [2, 3]}, {"c": 4}]

    # outermost (default) keeps only top-level matches; outermost=False includes
    # nested ones (which overlap).
    nested = '{"x": {"y": 1}}'
    assert [c.text for c in chunk_by_rule(nested, JSONLexer, JSONParser, "obj")] == [
        '{"x": {"y": 1}}'
    ]
    assert [
        c.text
        for c in chunk_by_rule(nested, JSONLexer, JSONParser, "obj", outermost=False)
    ] == ['{"x": {"y": 1}}', '{"y": 1}']

    # A rule index and an explicit start_rule agree with the name form.
    obj_idx = list(JSONParser.ruleNames).index("obj")
    assert [
        c.text
        for c in chunk_by_rule(text, JSONLexer, JSONParser, obj_idx, start_rule="json")
    ] == ['{"a": 1}', '{"b": [2, 3]}', '{"c": 4}']

    with pytest.raises(ValueError, match="unknown rule"):
        list(chunk_by_rule(text, JSONLexer, JSONParser, "nonesuch"))
