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

"""Build native lexer/parser specs from stock-generated ANTLR Python classes.

`antlr-pyfacade` consumes the output of the ordinary ANTLR tool run with
`-Dlanguage=Python3`: it reads the serialized ATN and the name/vocabulary metadata
straight off the generated `<Grammar>Lexer` / `<Grammar>Parser` classes and hands
them to the C++ runtime. [load_specs][antlr_pyfacade.load_specs] is the bridge
that makes the runtime grammar-agnostic — no codegen step of our own, no annotated
grammar, just the modules the user already generated.
"""

from __future__ import annotations

import sys

from . import _native

# Cache specs by (LexerCls, ParserCls) so repeated walks of the same grammar
# pay the ATN deserialization cost once.
_CACHE: dict[tuple[type, type], tuple[_native.ParserSpec, _native.LexerSpec]] = {}

# Lexer-only spec cache (for chunking, which needs no parser), keyed by lexer class.
_LEXER_CACHE: dict[type, _native.LexerSpec] = {}


def load_lexer_spec(lexer_cls: type, *, cached: bool = True) -> _native.LexerSpec:
    """Return the `lexer_spec` for a generated `<Grammar>Lexer` class.

    The lexer-only counterpart of [load_specs][antlr_pyfacade.load_specs], for
    code that lexes without parsing (e.g. the chunkers in
    [antlr_pyfacade.chunking][]). Reads the serialized ATN + vocabulary off the
    class and its module, and caches by class.

    Args:
        lexer_cls: The stock ANTLR-generated `<Grammar>Lexer` class.
        cached: When `True` (default), reuse/store the result in the per-lexer
            cache; `False` forces a fresh, uncached spec.

    Returns:
        The `lexer_spec` for the grammar.
    """
    if cached:
        hit = _LEXER_CACHE.get(lexer_cls)
        if hit is not None:
            return hit

    lexer_mod = sys.modules[lexer_cls.__module__]
    grammar_file = getattr(lexer_cls, "grammarFileName", "<grammar>.g4")
    spec = _native.LexerSpec(
        grammar_file,
        list(lexer_cls.literalNames),
        list(lexer_cls.symbolicNames),
        list(lexer_cls.ruleNames),
        list(lexer_cls.channelNames),
        list(lexer_cls.modeNames),
        lexer_mod.serializedATN(),
    )
    if cached:
        _LEXER_CACHE[lexer_cls] = spec
    return spec


def load_specs(
    lexer_cls: type, parser_cls: type, *, cached: bool = True
) -> tuple[_native.ParserSpec, _native.LexerSpec]:
    """Return `(parser_spec, lexer_spec)` for a generated lexer/parser pair.

    The Python3 target emits a module-level `serializedATN()` alongside each
    class, so it is resolved via the class's module. Results are cached by the
    class pair.

    A spec owns a mutable ATN. With the vendored runtime's per-DFA locks, sharing
    one spec across threads is both correct and scales, so most parallel code can
    just share a cached spec (or use
    [FacadeListener.walk_parallel][antlr_pyfacade.FacadeListener.walk_parallel]).

    Args:
        lexer_cls: The stock ANTLR-generated `<Grammar>Lexer` class.
        parser_cls: The stock ANTLR-generated `<Grammar>Parser` class.
        cached: When `True` (default), reuse/store the result in the per-grammar
            cache. Pass `False` to force a fresh, independent spec — neither read
            from nor written to the cache — to avoid sharing entirely (e.g. one
            spec per worker via `threading.local`).

    Returns:
        The `(parser_spec, lexer_spec)` pair for the grammar.
    """
    key = (lexer_cls, parser_cls)
    if cached:
        hit = _CACHE.get(key)
        if hit is not None:
            return hit

    lexer_mod = sys.modules[lexer_cls.__module__]
    parser_mod = sys.modules[parser_cls.__module__]
    grammar_file = getattr(parser_cls, "grammarFileName", "<grammar>.g4")

    lexer_spec = _native.LexerSpec(
        grammar_file,
        list(lexer_cls.literalNames),
        list(lexer_cls.symbolicNames),
        list(lexer_cls.ruleNames),
        list(lexer_cls.channelNames),
        list(lexer_cls.modeNames),
        lexer_mod.serializedATN(),
    )
    parser_spec = _native.ParserSpec(
        grammar_file,
        list(parser_cls.literalNames),
        list(parser_cls.symbolicNames),
        list(parser_cls.ruleNames),
        parser_mod.serializedATN(),
    )

    specs = (parser_spec, lexer_spec)
    if cached:
        _CACHE[key] = specs
    return specs
