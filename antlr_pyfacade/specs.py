"""Build native lexer/parser specs from stock-generated ANTLR Python classes.

``antlr-pyfacade`` consumes the output of the ordinary ANTLR tool run with
``-Dlanguage=Python3``: it reads the serialized ATN and the name/vocabulary
metadata straight off the generated ``<Grammar>Lexer`` / ``<Grammar>Parser``
classes and hands them to the C++ runtime. ``load_specs`` is the bridge that
makes the runtime grammar-agnostic — no codegen step of our own, no annotated
grammar, just the modules the user already generated.
"""

from __future__ import annotations

import sys

from . import _native

# Cache specs by (LexerCls, ParserCls) so repeated walks of the same grammar
# pay the ATN deserialization cost once.
_CACHE: dict[tuple[type, type], tuple[_native.ParserSpec, _native.LexerSpec]] = {}


def load_specs(
    lexer_cls: type, parser_cls: type
) -> tuple[_native.ParserSpec, _native.LexerSpec]:
    """Return ``(parser_spec, lexer_spec)`` for a generated lexer/parser pair.

    ``lexer_cls`` / ``parser_cls`` are the stock ANTLR-generated
    ``<Grammar>Lexer`` / ``<Grammar>Parser`` classes. The Python3 target emits a
    module-level ``serializedATN()`` alongside each class, so we resolve it via
    the class's module. Results are cached by the class pair.
    """
    key = (lexer_cls, parser_cls)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

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
    _CACHE[key] = specs
    return specs
