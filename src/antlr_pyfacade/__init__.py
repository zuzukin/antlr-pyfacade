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

# The compiled extension stays internal: only the few names users actually need
# are re-exported below. The low-level binding (the diagnostic functions and the
# parse-tree node classes) remains reachable as `antlr_pyfacade._native` for
# power/diagnostic use, but is not part of the public top-level surface.
from . import _native
from ._native import (
    LexerSpec,
    ParseError,
    ParserSpec,
    parse_events,
)
from .base import Chunk, FacadeListener
from .chunking import (
    LexToken,
    chunk_by_pattern,
    chunk_by_rule,
    lex,
    split_between_tokens,
    split_on_pattern,
    split_on_token,
    stream_on_pattern,
    stream_on_token,
)
from .location import SourceMap
from .specs import load_lexer_spec, load_specs

__version__ = _files(__name__).joinpath("VERSION").read_text(encoding="utf-8").strip()

__all__ = [
    "Chunk",
    "FacadeListener",
    "LexToken",
    "LexerSpec",
    "ParseError",
    "ParserSpec",
    "SourceMap",
    "__version__",
    "chunk_by_pattern",
    "chunk_by_rule",
    "lex",
    "load_lexer_spec",
    "load_specs",
    "parse_events",
    "split_between_tokens",
    "split_on_pattern",
    "split_on_token",
    "stream_on_pattern",
    "stream_on_token",
]
