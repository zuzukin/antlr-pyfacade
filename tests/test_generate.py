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

"""The `antlrope` facade generator — `generate()` and the `main()` CLI,
driven directly (no subprocess) against the bundled JSON example's parser."""

from __future__ import annotations

import pytest
from generated.JSONLexer import JSONLexer
from generated.JSONParser import JSONParser

from antlrope import FacadeListener, __version__
from antlrope.generate import _derive_lexer, _rule_names_block, generate, main

PARSER_MODULE = "generated.JSONParser"


def test_generate_facade_source():
    src = generate(PARSER_MODULE, "JSON")

    # The class is named <Grammar.capitalize()>EventListener and subclasses the base.
    assert "class JsonEventListener(FacadeListener):" in src
    # One enter/exit stub per parser rule, plus the terminal/error stubs.
    for rule in JSONParser.ruleNames:
        cap = rule[0].upper() + rule[1:]
        assert f"def enter{cap}(self)" in src
        assert f"def exit{cap}(self)" in src
    assert "def visitTerminal(" in src
    assert "def visitError(" in src
    # walk is inherited from FacadeListener (Template Method), not generated, so the
    # facade neither defines it nor needs load_specs.
    assert "def walk(" not in src
    assert "load_specs" not in src
    # The facade imports the stock lexer/parser and bakes them in as LEXER/PARSER,
    # so the inherited .walk() / .walk_parallel() need no class arguments.
    assert "from generated.JSONLexer import JSONLexer" in src
    assert "from generated.JSONParser import JSONParser" in src
    assert "LEXER: ClassVar[type] = JSONLexer" in src
    assert "PARSER: ClassVar[type] = JSONParser" in src
    # Token-type constants cover both branches: symbolic names (STRING/NUMBER) and
    # anonymous literals, which the facade emits with ANTLR's positional name
    # (T__0 is the first literal — token type 1 — not T__1).
    assert "STRING = " in src
    assert "NUMBER = " in src
    assert "T__0 = 1" in src

    # The emitted source is valid Python and defines a working FacadeListener
    # subclass whose inherited walk() actually drives a parse.
    namespace: dict = {}
    exec(compile(src, "<generated>", "exec"), namespace)
    cls = namespace["JsonEventListener"]
    assert issubclass(cls, FacadeListener)
    assert list(cls.ruleNames) == list(JSONParser.ruleNames)
    # The baked-in classes are the stock lexer/parser themselves.
    assert cls.LEXER is JSONLexer
    assert cls.PARSER is JSONParser

    # Every token constant matches the stock lexer the user has — both the
    # symbolic names and the positional T__n names for anonymous literals.
    token_names = [n for n in vars(JSONLexer) if n == "STRING" or n.startswith("T__")]
    assert "T__0" in token_names and "STRING" in token_names  # sanity
    for name in token_names:
        assert getattr(cls, name) == getattr(JSONLexer, name), name

    # No lexer/parser arguments — the facade walks with its baked-in classes.
    listener = cls().walk('{"a": 1}', start_rule="value")
    assert listener.syntax_errors == []


def test_cli_main(tmp_path, capsys):
    # No -o: the facade is written to stdout; rc 0.
    rc = main([PARSER_MODULE, "JSON"])
    assert rc == 0
    stdout = capsys.readouterr().out
    assert "class JsonEventListener(FacadeListener):" in stdout

    # -o writes the same source to a file instead.
    out = tmp_path / "json_facade.py"
    rc = main([PARSER_MODULE, "JSON", "-o", str(out)])
    assert rc == 0
    assert "class JsonEventListener(FacadeListener):" in out.read_text(encoding="utf-8")

    # --version prints the package version and exits 0 (argparse raises SystemExit).
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_lexer_resolution_and_override(capsys):
    # The lexer path is derived from the parser by ANTLR's <Grammar>Lexer /
    # <Grammar>Parser convention; an explicit override naming the same lexer
    # produces byte-identical source.
    assert _derive_lexer("generated.JSONParser") == "generated.JSONLexer"
    assert _derive_lexer("JSONParser") == "JSONLexer"
    assert generate(PARSER_MODULE, "JSON") == generate(
        PARSER_MODULE, "JSON", "generated.JSONLexer"
    )

    # The --lexer CLI flag takes the same override.
    rc = main([PARSER_MODULE, "JSON", "--lexer", "generated.JSONLexer"])
    assert rc == 0
    assert "class JsonEventListener(FacadeListener):" in capsys.readouterr().out

    # A parser name that doesn't end in 'Parser' can't be derived from — the error
    # points at --lexer. A wrong lexer path fails at generation time, not later in
    # the user's generated module.
    with pytest.raises(ValueError, match="--lexer"):
        _derive_lexer("generated.JSONGrammar")
    with pytest.raises(ModuleNotFoundError):
        generate(PARSER_MODULE, "JSON", "generated.NoSuchLexer")


def test_rule_names_block_is_ruff_formatted():
    # The generated ruleNames list follows ruff/black formatting, so the facade is
    # format-clean as written with no post-generation `ruff format` pass: short
    # lists stay on one line, long ones explode one-per-line with a trailing comma.
    short = _rule_names_block(["json", "obj", "value"])
    assert short == '    ruleNames: ClassVar[list[str]] = ["json", "obj", "value"]'
    assert "\n" not in short

    block = _rule_names_block([f"rule{i}" for i in range(20)])
    lines = block.split("\n")
    assert lines[0] == "    ruleNames: ClassVar[list[str]] = ["  # opener at line end
    assert lines[1] == '        "rule0",'  # 8-space indent, trailing comma
    assert lines[-1] == "    ]"  # 4-space closing bracket
    assert all(ln.startswith('        "') and ln.endswith('",') for ln in lines[1:-1])

    # Boundary at the 88-column budget: the prefix is 37 chars, so a single 47-char
    # name lands the one-line form at exactly 88 (stays single); 48 tips it to 89
    # and it explodes.
    assert "\n" not in _rule_names_block(["x" * 47])
    assert "\n" in _rule_names_block(["x" * 48])
