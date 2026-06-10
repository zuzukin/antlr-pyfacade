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

"""Source-location reporting: SourceMap offset->(line, col) conversion, and the
facade exposing the current event's span / line_col to callbacks (terminals,
rule enter, and parse errors)."""

from __future__ import annotations

import pytest
from generated.JSONLexer import JSONLexer
from generated.JSONParser import JSONParser
from json_listener import JSONEventListener

from antlr_pyfacade import SourceMap

MULTILINE = '{\n  "a": 1\n}'
#            0 1 23 456789 10  (offsets; '\n' at 1 and 10)


# --- SourceMap unit tests ---------------------------------------------------


def test_sourcemap_multiline():
    sm = SourceMap(MULTILINE)
    assert sm.line_col(0) == (1, 0)  # '{'
    assert sm.line_col(4) == (2, 2)  # '"a"' start
    assert sm.line_col(9) == (2, 7)  # '1'
    assert sm.line_col(11) == (3, 0)  # '}'


def test_sourcemap_single_line():
    sm = SourceMap("abc")
    assert sm.line_col(0) == (1, 0)
    assert sm.line_col(2) == (1, 2)


def test_sourcemap_codepoint_offsets():
    # Offsets are codepoints, not bytes: 'é' (2 UTF-8 bytes) counts as one.
    sm = SourceMap('"café"')
    assert sm.line_col(4) == (1, 4)  # 'é'
    assert sm.line_col(5) == (1, 5)  # closing quote


def test_sourcemap_negative_offset_raises():
    with pytest.raises(ValueError):
        SourceMap("x").line_col(-1)


# --- Facade location exposure -----------------------------------------------


class _Recorder(JSONEventListener):
    def __init__(self) -> None:
        self.terminals: dict[str, tuple] = {}
        self.objs: list = []
        self.errors: list = []

    def visitTerminal(self, token_type: int, text: str) -> None:
        self.terminals[text] = (self.line_col(), self.span())

    def enterObj(self) -> None:
        self.objs.append(self.line_col())

    def visitError(self, token_type: int, text: str) -> None:
        self.errors.append((text, self.line_col(), self.span()))


def _run(text: str) -> _Recorder:
    rec = _Recorder()
    rec.walk(text, JSONLexer, JSONParser)
    return rec


def test_terminal_position_multiline():
    rec = _run(MULTILINE)
    line_col, span = rec.terminals['"a"']
    assert line_col == (2, 2)
    assert span == (4, 6)  # '"a"' spans offsets 4..6 inclusive


def test_terminal_position_codepoint_indexed():
    rec = _run('{"café": 1}')
    line_col, span = rec.terminals['"café"']
    assert line_col == (1, 1)
    assert span == (1, 6)  # codepoint span, not byte span


def test_rule_enter_position():
    rec = _run(MULTILINE)
    assert rec.objs == [(1, 0)]  # the obj rule begins at '{'


def test_error_extraneous_token_has_position():
    rec = _run("[1 2]")  # the '2' is extraneous
    assert len(rec.errors) == 1
    text, line_col, span = rec.errors[0]
    assert text == "2"
    assert span == (3, 3)
    assert line_col == (1, 3)


def test_error_missing_token_has_no_span():
    rec = _run("[1,]")  # a value is missing before ']'
    assert rec.errors
    text, line_col, span = rec.errors[0]
    assert span == (-1, -1)
    assert line_col is None
    assert text == ""


def test_no_errors_on_valid_input():
    assert _run(MULTILINE).errors == []
