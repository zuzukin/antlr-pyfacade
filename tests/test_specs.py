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

"""FacadeListener.parser_spec / lexer_spec and ATN-shape sanity."""

from __future__ import annotations

from generated import JSONParser as parser_mod
from generated.JSONParser import JSONParser
from json_listener import JsonEventListener

import antlrope as ap


def test_specs_build_and_cache():
    assert isinstance(JsonEventListener.parser_spec(), ap.ParserSpec)
    assert isinstance(JsonEventListener.lexer_spec(), ap.LexerSpec)
    # Cached by class: the same object on repeat calls; cached=False forces a fresh,
    # independent spec (neither read from nor written to the cache).
    assert JsonEventListener.parser_spec() is JsonEventListener.parser_spec()
    assert JsonEventListener.lexer_spec() is JsonEventListener.lexer_spec()
    assert (
        JsonEventListener.parser_spec(cached=False)
        is not JsonEventListener.parser_spec()
    )


def test_atn_shape_matches_generated_metadata():
    shape = ap._native.atn_shape(parser_mod.serializedATN())
    # JSON grammar has 5 rules: json, obj, pair, arr, value.
    assert shape.num_rules == len(JSONParser.ruleNames) == 5
    # maxTokenType corresponds to the last symbolic token (WS=12).
    assert shape.max_token_type == 12
