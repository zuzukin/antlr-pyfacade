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

"""load_specs and ATN-shape sanity."""

from __future__ import annotations

from generated import JSONParser as parser_mod
from generated.JSONLexer import JSONLexer
from generated.JSONParser import JSONParser

import antlrope as ap


def test_load_specs_returns_specs():
    pspec, lspec = ap.load_specs(JSONLexer, JSONParser)
    assert isinstance(pspec, ap.ParserSpec)
    assert isinstance(lspec, ap.LexerSpec)


def test_load_specs_is_cached():
    a = ap.load_specs(JSONLexer, JSONParser)
    b = ap.load_specs(JSONLexer, JSONParser)
    assert a[0] is b[0] and a[1] is b[1]


def test_atn_shape_matches_generated_metadata():
    shape = ap._native.atn_shape(parser_mod.serializedATN())
    # JSON grammar has 5 rules: json, obj, pair, arr, value.
    assert shape.num_rules == len(JSONParser.ruleNames) == 5
    # maxTokenType corresponds to the last symbolic token (WS=12).
    assert shape.max_token_type == 12
