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

from . import _native
from ._native import (
    AtnShape,
    ErrorNode,
    LexerSpec,
    ParseError,
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
from .facade_runtime import FacadeListener, drive
from .location import SourceMap
from .specs import load_specs

__version__ = _native.__version__

__all__ = [
    "AtnShape",
    "ErrorNode",
    "FacadeListener",
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
    "atn_shape",
    "drive",
    "load_specs",
    "parse_count",
    "parse_events",
    "parse_stage_times",
    "parse_walk",
    "__version__",
]
