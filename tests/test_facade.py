"""Facade dispatch correctness: the generated JSONEventListener subclass driven
by the bulk event stream must rebuild the document, filtered and unfiltered, with
correct token text (including multibyte UTF-8, which exercises codepoint-indexed
slicing)."""

from __future__ import annotations

import json

from generated.JSONLexer import JSONLexer
from generated.JSONParser import JSONParser
from to_python import JsonValueBuilder


def _parse(text: str, *, filtered: bool):
    builder = JsonValueBuilder()
    builder.walk(text, JSONLexer, JSONParser, filtered=filtered)
    return builder.result


def test_facade_roundtrips_filtered(json_text):
    assert _parse(json_text, filtered=True) == json.loads(json_text)


def test_facade_roundtrips_unfiltered(json_text):
    assert _parse(json_text, filtered=False) == json.loads(json_text)


def test_filtered_and_unfiltered_agree(json_text):
    assert _parse(json_text, filtered=True) == _parse(json_text, filtered=False)
