"""antlr-pyfacade: a fast, C++-accelerated ANTLR runtime for Python.

Generate your parser with the stock ANTLR tool (``-Dlanguage=Python3``),
generate a facade with ``antlr-pyfacade-gen``, subclass the
``<Grammar>EventListener`` it emits, and call ``.walk(text, LexerCls,
ParserCls)``. Parsing runs in the official ANTLR4 C++ runtime; a single bulk,
filtered event stream crosses into Python instead of a per-node parse-tree walk.
"""

from __future__ import annotations

from . import _native
from ._native import (
    AtnShape,
    ErrorNode,
    LexerSpec,
    ParseTree,
    ParseTreeListener,
    ParserRuleContext,
    ParserSpec,
    RuleContext,
    TerminalNode,
    Token,
    atn_shape,
    parse_count,
    parse_events,
    parse_stage_times,
    parse_walk,
)
from .facade_runtime import drive
from .specs import load_specs

__version__ = _native.__version__

__all__ = [
    "AtnShape",
    "ErrorNode",
    "LexerSpec",
    "ParseTree",
    "ParseTreeListener",
    "ParserRuleContext",
    "ParserSpec",
    "RuleContext",
    "TerminalNode",
    "Token",
    "atn_shape",
    "drive",
    "load_specs",
    "parse_count",
    "parse_events",
    "parse_stage_times",
    "parse_walk",
    "__version__",
]
