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

"""The `antlr-pyfacade` facade generator — `generate()` and the `main()` CLI,
driven directly (no subprocess) against the bundled JSON example's parser."""

from __future__ import annotations

import pytest
from generated.JSONLexer import JSONLexer
from generated.JSONParser import JSONParser

from antlr_pyfacade import FacadeListener, __version__
from antlr_pyfacade.generate import generate, main

PARSER_MODULE = "generated.JSONParser"


def test_generate_facade_source():
    src = generate(PARSER_MODULE, "JSON")

    # The class is named <Grammar.capitalize()>EventListener and subclasses the base.
    assert "class JsonEventListener(FacadeListener):" in src
    # One enter/exit stub per parser rule, plus the terminal/error/walk surface.
    for rule in JSONParser.ruleNames:
        cap = rule[0].upper() + rule[1:]
        assert f"def enter{cap}(self)" in src
        assert f"def exit{cap}(self)" in src
    assert "def visitTerminal(" in src
    assert "def visitError(" in src
    assert "def walk(" in src
    # Token-type constants cover both branches: symbolic names (STRING/NUMBER) and
    # literal-only tokens, which the facade emits as T__<type> (= its value).
    assert "STRING = " in src
    assert "NUMBER = " in src
    assert "T__1 = 1" in src

    # The emitted source is valid Python and defines a working FacadeListener
    # subclass whose generated walk() actually drives a parse.
    namespace: dict = {}
    exec(compile(src, "<generated>", "exec"), namespace)
    cls = namespace["JsonEventListener"]
    assert issubclass(cls, FacadeListener)
    assert list(cls.ruleNames) == list(JSONParser.ruleNames)
    listener = cls().walk('{"a": 1}', JSONLexer, JSONParser, start_rule="value")
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
