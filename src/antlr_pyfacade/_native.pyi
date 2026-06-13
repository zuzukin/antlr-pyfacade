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
#
# Type stub for the `_native` nanobind extension (built from cpp/binding.cpp).
#
# The compiled `_native` module is loaded at runtime through scikit-build-core's
# editable redirector, which static analyzers (PyCharm, mypy) cannot follow. This
# checked-in stub gives them the interface so `_native` and the symbols
# re-exported from it in `__init__.py` resolve.
#
# Regenerate with `pixi run stubgen` after changing cpp/binding.cpp, then re-apply
# the two hand edits below that stubgen does not emit:
#   - `__version__`
#   - the `parse_events` return type (`tuple[bytes, list[ParseError]]`, not `object`)
#
"""antlr-pyfacade: Python binding over the official ANTLR4 C++ runtime"""

from collections.abc import Sequence

__version__: str


class AtnShape:
    @property
    def grammar_type(self) -> int: ...

    @property
    def num_states(self) -> int: ...

    @property
    def num_decisions(self) -> int: ...

    @property
    def num_rules(self) -> int: ...

    @property
    def max_token_type(self) -> int: ...

    def __repr__(self) -> str: ...

def atn_shape(serialized: Sequence[int]) -> AtnShape:
    """Deserialize a serialized ATN int list and return its shape."""

class ParseError:
    @property
    def line(self) -> int: ...

    @property
    def column(self) -> int: ...

    @property
    def start(self) -> int: ...

    @property
    def stop(self) -> int: ...

    @property
    def message(self) -> str: ...

    def __repr__(self) -> str: ...

class LexerSpec:
    def __init__(self, grammar_file_name: str, literal_names: Sequence[str], symbolic_names: Sequence[str], rule_names: Sequence[str], channel_names: Sequence[str], mode_names: Sequence[str], serialized: Sequence[int]) -> None: ...

class ParserSpec:
    def __init__(self, grammar_file_name: str, literal_names: Sequence[str], symbolic_names: Sequence[str], rule_names: Sequence[str], serialized: Sequence[int]) -> None: ...

class Token:
    def getType(self) -> int: ...

    def getText(self) -> str: ...

    def getLine(self) -> int: ...

    def getCharPositionInLine(self) -> int: ...

class ParseTree:
    pass

class RuleContext(ParseTree):
    def getRuleIndex(self) -> int: ...

class ParserRuleContext(RuleContext):
    def getStart(self) -> Token: ...

    def getStop(self) -> Token: ...

class TerminalNode(ParseTree):
    def getSymbol(self) -> Token: ...

class ErrorNode(TerminalNode):
    pass

class ParseTreeListener:
    def __init__(self) -> None: ...

    def visitTerminal(self, arg: TerminalNode, /) -> None: ...

    def visitErrorNode(self, arg: ErrorNode, /) -> None: ...

    def enterEveryRule(self, arg: ParserRuleContext, /) -> None: ...

    def exitEveryRule(self, arg: ParserRuleContext, /) -> None: ...

def parse_count(parser_spec: ParserSpec, lexer_spec: LexerSpec, text: str, start_rule: int) -> dict:
    """
    Diagnostic: parse + walk with a native counting listener (no Python crossing).
    """

def parse_walk(parser_spec: ParserSpec, lexer_spec: LexerSpec, text: str, start_rule: int, listener: ParseTreeListener) -> None:
    """
    Diagnostic escape hatch: parse + walk the tree, dispatching to a Python ParseTreeListener (slow per-node FFI path).
    """

def parse_events(parser_spec: ParserSpec, lexer_spec: LexerSpec, text: str, start_rule: int, rule_mask: Sequence[int] | None = None, token_mask: Sequence[int] | None = None) -> tuple[bytes, list[ParseError]]:
    """
    Parse and return (events, errors): a bulk flat int32 event buffer of 4*N values (kind, payload, start, stop) as bytes, and a list of SyntaxError diagnostics collected during the parse. Optional rule_mask/token_mask (lists of indices to keep) filter events natively. The default stderr error listener is suppressed.
    """

def parse_stage_times(parser_spec: ParserSpec, lexer_spec: LexerSpec, text: str, start_rule: int) -> dict:
    """
    Diagnostic: dict of per-stage seconds (input_decode, lex_fill, parse_tree, walk) plus token/event/codepoint counts.
    """
