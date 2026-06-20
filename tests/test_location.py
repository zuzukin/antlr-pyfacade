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
from json_listener import JsonEventListener

from antlrope import SourceMap

MULTILINE = '{\n  "a": 1\n}'
#            0 1 23 456789 10  (offsets; '\n' at 1 and 10)


# --- SourceMap unit tests ---------------------------------------------------


def test_sourcemap():
    # Multi-line: 1-based line, 0-based column (offsets annotated by MULTILINE).
    sm = SourceMap(MULTILINE)
    assert sm.line_col(0) == (1, 0)  # '{'
    assert sm.line_col(4) == (2, 2)  # '"a"' start
    assert sm.line_col(9) == (2, 7)  # '1'
    assert sm.line_col(11) == (3, 0)  # '}'

    # offset() is the inverse of line_col(): it undoes each mapping above,
    # defaults column to the line start, and round-trips for every offset.
    assert sm.offset(1, 0) == 0
    assert sm.offset(2, 2) == 4
    assert sm.offset(2, 7) == 9
    assert sm.offset(3, 0) == 11
    assert sm.offset(2) == 2  # column defaults to 0 (start of line 2)
    for off in range(len(MULTILINE)):
        assert sm.offset(*sm.line_col(off)) == off

    # Single line: every offset is on line 1.
    sm = SourceMap("abc")
    assert sm.line_col(0) == (1, 0)
    assert sm.line_col(2) == (1, 2)
    assert sm.offset(1, 2) == 2

    # Offsets are codepoints, not bytes: 'é' (2 UTF-8 bytes) counts as one.
    sm = SourceMap('"café"')
    assert sm.line_col(4) == (1, 4)  # 'é'
    assert sm.line_col(5) == (1, 5)  # closing quote
    assert sm.offset(1, 4) == 4

    # Out-of-range inputs raise ValueError.
    sm = SourceMap("x")  # one line, so the only valid line number is 1
    with pytest.raises(ValueError):
        sm.line_col(-1)
    with pytest.raises(ValueError):
        sm.offset(0)  # line is 1-based
    with pytest.raises(ValueError):
        sm.offset(2)  # past the last line


# --- Facade location exposure -----------------------------------------------


class _Recorder(JsonEventListener):
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
    rec.walk(text)
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
