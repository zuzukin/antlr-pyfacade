"""load_specs and ATN-shape sanity."""

from __future__ import annotations

import antlr_pyfacade as ap
from generated import JSONParser as parser_mod
from generated.JSONLexer import JSONLexer
from generated.JSONParser import JSONParser


def test_load_specs_returns_specs():
    pspec, lspec = ap.load_specs(JSONLexer, JSONParser)
    assert isinstance(pspec, ap.ParserSpec)
    assert isinstance(lspec, ap.LexerSpec)


def test_load_specs_is_cached():
    a = ap.load_specs(JSONLexer, JSONParser)
    b = ap.load_specs(JSONLexer, JSONParser)
    assert a[0] is b[0] and a[1] is b[1]


def test_atn_shape_matches_generated_metadata():
    shape = ap.atn_shape(parser_mod.serializedATN())
    # JSON grammar has 5 rules: json, obj, pair, arr, value.
    assert shape.num_rules == len(JSONParser.ruleNames) == 5
    # maxTokenType corresponds to the last symbolic token (WS=12).
    assert shape.max_token_type == 12
