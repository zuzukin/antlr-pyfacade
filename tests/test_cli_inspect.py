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

"""The `check`, `rules`, and `tokens` introspection subcommands, run in-process
against the bundled JSON example (clean) and the predicate fixture (which the
ATN interpreter cannot run faithfully)."""

from __future__ import annotations

import json

import pytest
from generated.JSONParser import JSONParser

from antlrope.cli.main import main


def test_check_reports_interpreter_compatibility(capsys: pytest.CaptureFixture[str]):
    # The JSON grammar is purely structural: no predicates, no actions (its
    # `-> skip` lexer commands are built-ins the interpreter executes).
    assert main(["check", "generated.JSONParser"]) == 0
    assert "OK" in capsys.readouterr().out

    # The predicate fixture's parser rule `s` carries `{...}?`: flagged, named,
    # non-zero exit, with a pointer at the docs.
    assert main(["check", "PredParser"]) == 1
    out = capsys.readouterr().out
    assert "INCOMPATIBLE" in out
    assert "semantic predicate in parser rule 's'" in out
    assert "performance" in out

    # An explicit --lexer path is honored.
    assert (
        main(["check", "generated.JSONParser", "--lexer", "generated.JSONLexer"]) == 0
    )
    capsys.readouterr()


def test_bad_input_prints_clean_error(capsys: pytest.CaptureFixture[str]):
    """A missing/bad module gives one clean stderr line and exit 2 — no traceback."""
    for argv in (
        ["rules", "no.such.module"],
        ["tokens", "no.such.module"],
        ["check", "no.such.module.Parser"],
        ["gen", "no.such.module.Parser", "Nope"],
    ):
        assert main(argv) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.startswith(f"antlrope {argv[0]}: ")
        assert "Traceback" not in captured.err


def test_rules_and_tokens_list_grammar_names(capsys: pytest.CaptureFixture[str]):
    assert main(["rules", "generated.JSONParser"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines() == [
        f"{i}\t{name}" for i, name in enumerate(JSONParser.ruleNames)
    ]

    assert main(["rules", "generated.JSONParser", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == list(JSONParser.ruleNames)

    # tokens: symbolic names plus the parser's positional T__n literal names,
    # matching the generated facade's constants (STRING=10 etc. for JSON).
    assert main(["tokens", "generated.JSONParser"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "10\tSTRING" in lines
    assert "1\tT__0" in lines

    assert main(["tokens", "generated.JSONParser", "--json"]) == 0
    mapping = json.loads(capsys.readouterr().out)
    assert mapping["STRING"] == 10
    assert mapping["T__0"] == 1
    assert len(mapping) == 12  # every JSON token type 1..12 has a name
