"""The bulk event stream must deliver exactly the events a parse-tree walk does.

Two independent references:
  * the official pure-Python ``antlr4`` runtime walked by ``ParseTreeWalker``;
  * the native C++ counting walk (``parse_count``).
Both must agree with the unfiltered ``parse_events`` kind tallies.
"""

from __future__ import annotations

import antlr_pyfacade as ap
import pytest
from generated.JSONLexer import JSONLexer
from generated.JSONParser import JSONParser

antlr4 = pytest.importorskip("antlr4")

EV_ENTER, EV_EXIT, EV_TERMINAL, EV_ERROR = 0, 1, 2, 3
RULE_JSON = JSONParser.RULE_json


def _event_tallies(text: str) -> dict[int, int]:
    pspec, lspec = ap.load_specs(JSONLexer, JSONParser)
    raw, _ = ap.parse_events(pspec, lspec, text, RULE_JSON)
    mv = memoryview(raw).cast("i")
    tally = {EV_ENTER: 0, EV_EXIT: 0, EV_TERMINAL: 0, EV_ERROR: 0}
    for i in range(len(mv) // 4):
        tally[mv[i * 4]] += 1
    return tally


class _Counter(antlr4.ParseTreeListener):
    def __init__(self) -> None:
        self.enters = self.exits = self.terminals = self.errors = 0

    def enterEveryRule(self, ctx):
        self.enters += 1

    def exitEveryRule(self, ctx):
        self.exits += 1

    def visitTerminal(self, node):
        self.terminals += 1

    def visitErrorNode(self, node):
        self.errors += 1


def _pure_python_counts(text: str) -> _Counter:
    stream = antlr4.InputStream(text)
    lexer = JSONLexer(stream)
    tokens = antlr4.CommonTokenStream(lexer)
    parser = JSONParser(tokens)
    tree = parser.json()
    counter = _Counter()
    antlr4.ParseTreeWalker().walk(counter, tree)
    return counter


def test_events_match_pure_python_walker(json_text):
    tally = _event_tallies(json_text)
    ref = _pure_python_counts(json_text)
    assert tally[EV_ENTER] == ref.enters
    assert tally[EV_EXIT] == ref.exits
    assert tally[EV_TERMINAL] == ref.terminals
    assert tally[EV_ERROR] == ref.errors


def test_events_match_native_count(json_text):
    pspec, lspec = ap.load_specs(JSONLexer, JSONParser)
    tally = _event_tallies(json_text)
    cnt = ap.parse_count(pspec, lspec, json_text, RULE_JSON)
    assert tally[EV_ENTER] == cnt["enters"]
    assert tally[EV_EXIT] == cnt["exits"]
    assert tally[EV_TERMINAL] == cnt["terminals"]
    assert tally[EV_ERROR] == cnt["errors"]
