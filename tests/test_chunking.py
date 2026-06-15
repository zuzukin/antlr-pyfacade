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
    chunk_by_pattern,
    chunk_by_rule,
    lex,
    split_between_tokens,
    split_on_pattern,
    split_on_token,
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
    toks = lex(text, JSONLexer)

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
