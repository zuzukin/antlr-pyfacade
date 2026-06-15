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

"""
antlr-pyfacade: a fast, C++-accelerated ANTLR Python runtime for target-agnostic grammars.

Generate your parser with the stock ANTLR tool (`-Dlanguage=Python3`), generate a
facade with `antlr-pyfacade`, subclass the `<Grammar>EventListener` it emits, and
call `.walk(text, LexerCls, ParserCls)`. Parsing runs in the official ANTLR4 C++
runtime; a single bulk, filtered event stream crosses into Python instead of a
per-node parse-tree walk.
"""

from __future__ import annotations

# Version is read from the VERSION file (the single source of truth), shipped as
# package data in the wheel/sdist and present in the source tree.
from importlib.resources import files as _files

from . import _native
from ._native import (
    AtnShape,
    ErrorNode,
    LexerSpec,
    ParseError,
    ParserRuleContext,
    ParserSpec,
    ParseTree,
    ParseTreeListener,
    RuleContext,
    TerminalNode,
    Token,
    atn_shape,
    parse_count,
    parse_events,
    parse_stage_times,
    parse_walk,
)
from .chunking import LexToken, lex, split_between_tokens, split_on_token
from .facade_runtime import Chunk, FacadeListener, drive
from .location import SourceMap
from .specs import load_lexer_spec, load_specs

__version__ = _files(__name__).joinpath("VERSION").read_text(encoding="utf-8").strip()

__all__ = [
    "AtnShape",
    "Chunk",
    "ErrorNode",
    "FacadeListener",
    "LexToken",
    "LexerSpec",
    "ParseError",
    "ParseTree",
    "ParseTreeListener",
    "ParserRuleContext",
    "ParserSpec",
    "RuleContext",
    "SourceMap",
    "TerminalNode",
    "Token",
    "__version__",
    "atn_shape",
    "drive",
    "lex",
    "load_lexer_spec",
    "load_specs",
    "parse_count",
    "parse_events",
    "parse_stage_times",
    "parse_walk",
    "split_between_tokens",
    "split_on_token",
]
