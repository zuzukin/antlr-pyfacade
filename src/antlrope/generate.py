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

"""Generate a grammar-specific event-listener facade from ANTLR parser metadata.

Reads `ruleNames` + token name lists from an already-generated ANTLR Python parser
module (no annotated grammar, no extra inputs) and emits a `<Grammar>EventListener`
base class: named `enter<Rule>` / `exit<Rule>` no-op stubs, `visitTerminal` /
`visitError` stubs, token-type constants, and a `walk` method that runs the bulk
native event stream. The base subclasses
[FacadeListener][antlrope.FacadeListener], so callbacks can call
`self.line_col()` for the current event's source position.

The generated surface mirrors the stock ANTLR listener so consumers write the same
code; the difference is that callbacks are driven by a flat event buffer rather
than a Python parse-tree walk. Usage (console script or module):

    antlrope mypkg.generated.MyParser My -o my_listener.py
"""

from __future__ import annotations

import argparse
import importlib
import sys
from textwrap import dedent

from antlrope import __version__

# TODO - add doc strings


def _ident(name: str) -> str:
    return name[0].upper() + name[1:]


def _derive_lexer(parser_qualname: str) -> str:
    """Derive the lexer module path from the parser's, by ANTLR convention.

    ANTLR names a combined grammar's classes `<Grammar>Lexer` / `<Grammar>Parser`
    in same-named modules, so the lexer path is the parser path with the trailing
    `Parser` replaced by `Lexer` (e.g. `pkg.JSONParser` -> `pkg.JSONLexer`).

    Raises:
        ValueError: If the parser module path's final component does not end in
            `Parser`, so the lexer cannot be derived — pass `--lexer` explicitly.
    """
    if not parser_qualname.rsplit(".", 1)[-1].endswith("Parser"):
        raise ValueError(
            f"cannot derive the lexer from parser module {parser_qualname!r} "
            "(its name does not end in 'Parser'); pass --lexer with the lexer's "
            "dotted module path."
        )
    return parser_qualname[: -len("Parser")] + "Lexer"


def _import_class(qualname: str) -> type:
    """Import the dotted module path and return its same-named class."""
    mod = importlib.import_module(qualname)
    return getattr(mod, qualname.rsplit(".", 1)[-1])


def generate(
    parser_qualname: str, grammar: str, lexer_qualname: str | None = None
) -> str:
    parser_cls = _import_class(parser_qualname)
    rule_names: list[str] = list(parser_cls.ruleNames)
    symbolic: list[str] = list(parser_cls.symbolicNames)

    if lexer_qualname is None:
        lexer_qualname = _derive_lexer(parser_qualname)
    # Import the lexer too so a wrong/missing path fails here, at generation time,
    # with a clear error rather than as an ImportError in the user's generated file.
    _import_class(lexer_qualname)
    parser_clsname = parser_qualname.rsplit(".", 1)[-1]
    lexer_clsname = lexer_qualname.rsplit(".", 1)[-1]

    listener_cls = f"{grammar.capitalize()}EventListener"

    # ANTLR names anonymous string-literal tokens positionally — `T__0` is the
    # first such token (token type 1), `T__1` the second (type 2), and so on — so
    # the name does NOT equal the token-type value. Read those names straight off
    # the generated parser, which already declares them, so the facade's constants
    # line up with the lexer/parser the user has rather than a synthesized name.
    literal_consts = {
        value: name
        for name, value in vars(parser_cls).items()
        if name.startswith("T__") and isinstance(value, int)
    }

    # token-type constants: the symbolic name when ANTLR gave one, else the
    # parser's own positional `T__n` name for the anonymous literal.
    tok_consts: list[tuple[str, int]] = []
    for ttype, sym in enumerate(symbolic):
        if ttype == 0:
            continue  # type 0 is unused / EOF sentinel
        if sym and sym != "<INVALID>":
            tok_consts.append((sym, ttype))
        elif ttype in literal_consts:
            tok_consts.append((literal_consts[ttype], ttype))

    # token_lines / rule_methods carry their own class-body indentation; the
    # template's placeholders sit at the base column so the content lands right.
    token_lines = "\n".join(f"    {name} = {ttype}" for name, ttype in tok_consts)
    rule_methods = "".join(
        f"""    def enter{cap}(self) -> None:
        pass

    def exit{cap}(self) -> None:
        pass

"""
        for cap in map(_ident, rule_names)
    )

    # Emit the rule-name list as a double-quoted literal (rule names are ANTLR
    # identifiers, so no escaping is needed) so the generated file is
    # ruff-format-clean as written — repr() would use single quotes.
    rule_names_src = "[" + ", ".join(f'"{name}"' for name in rule_names) + "]"

    # dedent() must run before .format(): an f-string would interpolate the
    # multi-line token_lines/rule_methods first, and their lower indentation would
    # then throw off dedent's common-prefix calculation.
    return dedent(
        '''\
        # GENERATED by antlrope — do not edit by hand.
        """
        Event-listener facade for the {grammar} grammar. Subclass {cls},
        override the callbacks you care about, then call .walk(text).
        """

        from __future__ import annotations

        from typing import ClassVar

        from {lexer_qualname} import {lexer_clsname}
        from {parser_qualname} import {parser_clsname}

        from antlrope import FacadeListener


        class {cls}(FacadeListener):
            ruleNames: ClassVar[list[str]] = {rule_names_src}
            START_RULE = 0  # {rule0}
            LEXER: ClassVar[type] = {lexer_clsname}
            PARSER: ClassVar[type] = {parser_clsname}

            # token-type constants
        {token_lines}

        {rule_methods}    def visitTerminal(self, token_type: int, text: str) -> None:
                pass

            def visitError(self, token_type: int, text: str) -> None:
                pass
        '''
    ).format(
        grammar=grammar,
        cls=listener_cls,
        lexer_qualname=lexer_qualname,
        lexer_clsname=lexer_clsname,
        parser_qualname=parser_qualname,
        parser_clsname=parser_clsname,
        rule_names_src=rule_names_src,
        rule0=rule_names[0],
        token_lines=token_lines,
        rule_methods=rule_methods,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="antlrope",
        description="Generate a <Grammar>EventListener facade from a "
        "stock-generated ANTLR Python parser module.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "parser_module",
        help="Importable dotted path to the generated parser module "
        "(e.g. mypkg.generated.MyParser).",
    )
    parser.add_argument("grammar", help="Grammar name prefix for the facade class.")
    parser.add_argument(
        "--lexer",
        help="Importable dotted path to the generated lexer module. Defaults to the "
        "parser path with a trailing 'Parser' replaced by 'Lexer' "
        "(e.g. mypkg.generated.MyLexer); pass this when the lexer is named "
        "differently.",
    )
    parser.add_argument("-o", "--output", help="Write to this file instead of stdout.")
    args = parser.parse_args(argv)

    source = generate(args.parser_module, args.grammar, args.lexer)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(source)
    else:
        sys.stdout.write(source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
