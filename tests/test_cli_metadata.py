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

"""Origin metadata in generated facades, and the `up-to-date` / `regen` commands."""

from __future__ import annotations

import generated.JSONLexer
import generated.JSONParser

from antlrope import __version__
from antlrope.cli import metadata
from antlrope.cli.main import main

PARSER = "generated.JSONParser"
PARSER_FILE = generated.JSONParser.__file__
LEXER_FILE = generated.JSONLexer.__file__


def test_metadata_render_parse_roundtrip():
    meta = metadata.Metadata(
        version="1.2.3",
        command="antlrope gen pkg.FooParser Foo -o foo.py",
        rundir="..",
        inputs=[("a/Foo.py", "dead" * 16), ("a/Bar.py", "feed" * 16)],
    )
    assert metadata.parse(metadata.render(meta)) == meta
    # rundir is optional and round-trips as None (e.g. generated to stdout).
    no_rundir = meta._replace(rundir=None)
    assert metadata.parse(metadata.render(no_rundir)) == no_rundir
    # A file without the antlrope banner / required lines has no metadata.
    assert metadata.parse("# just a comment\nx = 1\n") is None


def test_gen_embeds_metadata_and_is_reproducible(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["gen", PARSER, "JSON", "-o", "facade.py"]) == 0
    meta = metadata.parse((tmp_path / "facade.py").read_text(encoding="utf-8"))
    assert meta is not None
    assert meta.version == __version__
    assert meta.command == "antlrope gen generated.JSONParser JSON -o facade.py"
    assert meta.rundir == "."
    # The recorded input hashes are those of the real parser/lexer module files.
    recorded = {digest for _, digest in meta.inputs}
    assert metadata.sha256_file(PARSER_FILE) in recorded
    assert metadata.sha256_file(LEXER_FILE) in recorded

    # Deterministic: regenerating to the same path is byte-identical (no timestamp).
    first = (tmp_path / "facade.py").read_bytes()
    assert main(["gen", PARSER, "JSON", "-o", "facade.py"]) == 0
    assert (tmp_path / "facade.py").read_bytes() == first


def test_up_to_date_and_regen(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["gen", PARSER, "JSON", "-o", "facade.py"]) == 0
    facade = tmp_path / "facade.py"
    fresh = facade.read_text(encoding="utf-8")
    assert main(["up-to-date", "facade.py"]) == 0  # a fresh file is current

    # A changed input (simulated by corrupting the recorded hash) reads as stale.
    facade.write_text(
        fresh.replace(metadata.sha256_file(PARSER_FILE), "0" * 64, 1), encoding="utf-8"
    )
    assert main(["up-to-date", "facade.py"]) == 1

    # regen rewrites it byte-for-byte from its own metadata; up-to-date passes again.
    assert main(["regen", "facade.py"]) == 0
    assert facade.read_text(encoding="utf-8") == fresh
    assert main(["up-to-date", "facade.py"]) == 0

    # A version drift is also stale.
    facade.write_text(
        fresh.replace(
            f"# antlrope-version: {__version__}", "# antlrope-version: 0.0.0", 1
        ),
        encoding="utf-8",
    )
    assert main(["up-to-date", "facade.py"]) == 1

    # A file with no antlrope metadata is a usage error (2), not "up to date".
    (tmp_path / "plain.py").write_text("# nothing here\n", encoding="utf-8")
    assert main(["up-to-date", "plain.py"]) == 2
