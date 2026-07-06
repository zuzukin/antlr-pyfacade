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

import sys
import types
from typing import ClassVar

import pytest
from generated import JSONParser as parser_mod
from generated.JSONParser import JSONParser
from json_listener import JsonEventListener

import antlrope as ap
from antlrope.base import _build_parser_spec


def test_specs_build_and_cache():
    assert isinstance(JsonEventListener._parser_spec(), ap._native.ParserSpec)
    assert isinstance(JsonEventListener._lexer_spec(), ap._native.LexerSpec)
    # Cached by class: the same object on repeat calls; cached=False forces a fresh,
    # independent spec (neither read from nor written to the cache).
    assert JsonEventListener._parser_spec() is JsonEventListener._parser_spec()
    assert JsonEventListener._lexer_spec() is JsonEventListener._lexer_spec()
    assert (
        JsonEventListener._parser_spec(cached=False)
        is not JsonEventListener._parser_spec()
    )


def test_atn_shape_matches_generated_metadata():
    shape = ap._native.atn_shape(parser_mod.serializedATN())
    # JSON grammar has 5 rules: json, obj, pair, arr, value.
    assert shape.num_rules == len(JSONParser.ruleNames) == 5
    # maxTokenType corresponds to the last symbolic token (WS=12).
    assert shape.max_token_type == 12


def test_incompatible_antlr_errors_are_actionable():
    """Spec building fails with a cause and a fix, not a raw low-level error.

    Antlrope sets no upper bound on ANTLR versions; if a future ANTLR changes
    the serialized-ATN format or the generated-module surface, these are the
    errors a user sees.
    """
    # An unsupported serialized-ATN format version (the leading int): the C++
    # deserializer rejection is re-raised naming the class and the fix.
    tampered = list(parser_mod.serializedATN())
    tampered[0] = 99
    mod = types.ModuleType("_fake_future_parser")
    mod.serializedATN = lambda: tampered  # type: ignore[attr-defined]
    sys.modules[mod.__name__] = mod
    try:

        class FutureParser:
            literalNames: ClassVar[list[str]] = list(JSONParser.literalNames)
            symbolicNames: ClassVar[list[str]] = list(JSONParser.symbolicNames)
            ruleNames: ClassVar[list[str]] = list(JSONParser.ruleNames)

        FutureParser.__module__ = mod.__name__
        with pytest.raises(RuntimeError, match=r"FutureParser.*Regenerate"):
            _build_parser_spec(FutureParser)  # type: ignore[arg-type]
    finally:
        del sys.modules[mod.__name__]

    # A class missing the generated-module surface antlrope reads.
    class NotAParser:
        literalNames: ClassVar[list[str]] = ["<INVALID>"]
        symbolicNames: ClassVar[list[str]] = ["<INVALID>"]
        # no ruleNames

    with pytest.raises(TypeError, match=r"NotAParser.*`ruleNames`"):
        _build_parser_spec(NotAParser)  # type: ignore[arg-type]
