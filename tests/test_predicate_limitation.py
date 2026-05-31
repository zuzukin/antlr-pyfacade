"""Pin the documented semantic-predicate limitation.

The runtime drives ANTLR's ATN *interpreter*, which cannot evaluate
target-language semantic predicates or embedded actions. The `Pred` grammar
(examples/predicate/Pred.g4) has a `{False}?`-gated alternative:

    s : {False}? A   // never taken by a real generated parser
      | A A          // the only non-predicated way to match `s`

A real generated parser therefore rejects the single-token input "a" as a
syntax error. The interpreter ignores the predicate (treats it as true) and
matches "a" via the first alternative. These tests pin both behaviours so the
divergence is captured and can't regress silently.
"""

from __future__ import annotations

import struct

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from antlr_pyfacade import load_specs, parse_events
from PredLexer import PredLexer
from PredParser import PredParser

ERROR_KIND = 3  # EV_ERROR in the int32 event stream


def _interp_has_error(text: str) -> bool:
    parser_spec, lexer_spec = load_specs(PredLexer, PredParser)
    raw = parse_events(parser_spec, lexer_spec, text, 0)
    return any(rec[0] == ERROR_KIND for rec in struct.iter_unpack("<4i", raw))


class _Collector(ErrorListener):
    def __init__(self) -> None:
        self.count = 0

    def syntaxError(self, *args) -> None:  # noqa: ANN002
        self.count += 1


def _real_parser_error_count(text: str) -> int:
    parser = PredParser(CommonTokenStream(PredLexer(InputStream(text))))
    parser.removeErrorListeners()
    listener = _Collector()
    parser.addErrorListener(listener)
    parser.s()
    return listener.count


def test_real_parser_rejects_single_token():
    """The stock generated parser honours the false predicate: "a" is an error."""
    assert _real_parser_error_count("a") == 1
    assert _real_parser_error_count("a a") == 0


def test_interpreter_ignores_false_predicate():
    """This runtime cannot evaluate the predicate, so it accepts "a" with no error.

    This is the *known limitation*, not a bug: grammars whose parse depends on
    semantic predicates or embedded actions will not match the generated parser.
    """
    assert _interp_has_error("a") is False
    assert _interp_has_error("a a") is False


def test_divergence_is_real():
    """Make the contradiction explicit: same input, opposite verdicts."""
    text = "a"
    assert _real_parser_error_count(text) > 0
    assert _interp_has_error(text) is False
