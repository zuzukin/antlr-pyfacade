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

"""Parse-error collection: the default ANTLR console error listener is replaced
by a collecting one, so parse diagnostics surface as structured `ParseError`
records (on the raw `parse_events` tuple and as `listener.syntax_errors`)
instead of being written to stderr."""

from __future__ import annotations

from generated.JSONLexer import JSONLexer
from generated.JSONParser import JSONParser
from json_listener import JsonEventListener

import antlrope as ap

RULE_JSON = JSONParser.RULE_json


# --- raw parse_events tuple --------------------------------------------------


def test_parse_events_returns_events_and_errors():
    pspec, lspec = ap.load_specs(JSONLexer, JSONParser)
    events, errors = ap.parse_events(pspec, lspec, "[1 2]", RULE_JSON)
    assert isinstance(events, bytes)
    assert len(errors) == 1
    err = errors[0]
    assert isinstance(err, ap.ParseError)
    assert (err.line, err.column) == (1, 3)
    assert (err.start, err.stop) == (3, 3)
    assert "extraneous input '2'" in err.message


def test_parse_events_no_errors_on_valid_input():
    pspec, lspec = ap.load_specs(JSONLexer, JSONParser)
    _events, errors = ap.parse_events(pspec, lspec, '{"a": 1}', RULE_JSON)
    assert errors == []


# --- facade exposure ---------------------------------------------------------


def test_facade_collects_syntax_errors():
    listener = JsonEventListener()
    listener.walk("[1 2]", JSONLexer, JSONParser)
    assert len(listener.syntax_errors) == 1
    err = listener.syntax_errors[0]
    assert (err.line, err.column) == (1, 3)
    assert "extraneous input '2'" in err.message


def test_facade_syntax_errors_empty_on_valid_input():
    listener = JsonEventListener()
    listener.walk('{"a": 1}', JSONLexer, JSONParser)
    assert listener.syntax_errors == []


def test_facade_syntax_errors_reset_between_walks():
    listener = JsonEventListener()
    listener.walk("[1 2]", JSONLexer, JSONParser)
    assert listener.syntax_errors
    listener.walk('{"a": 1}', JSONLexer, JSONParser)
    assert listener.syntax_errors == []
