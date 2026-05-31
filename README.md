# antlr-pyfacade

A fast, C++-accelerated [ANTLR](https://www.antlr.org/) runtime for Python — with
**no per-grammar C/C++ compilation by the user**.

> **10–20× faster** than the official pure-Python `antlr4-python3-runtime` on
> workloads that touch most nodes — and more when your listener subscribes to
> only a subset of the grammar.

You generate your parser with the ordinary ANTLR tool targeting Python, install
this package, generate a small *facade*, and write a pure-Python event listener.
Parsing itself runs inside the official ANTLR4 **C++** runtime, driven directly
from the serialized ATN the stock Python target already emits. Instead of a
per-node parse-tree walk (one foreign-function crossing per tree node), the C++
side collects a **single bulk, filtered event stream** and hands it to Python in
one transfer — and it drops the rules/tokens your listener doesn't subscribe to
*before* they ever reach Python.

It complements, rather than replaces, the official `antlr4-python3-runtime`: same
generated parser, a faster way to consume it.

## Install

```sh
pip install antlr-pyfacade
```

## Quickstart

1. **Generate your parser** with the stock ANTLR tool (Python target):

   ```sh
   antlr4 -Dlanguage=Python3 MyGrammar.g4 -o generated
   ```

2. **Generate the facade** from the generated parser module:

   ```sh
   antlr-pyfacade-gen generated.MyGrammarParser MyGrammar -o my_listener.py
   ```

   This emits a `MyGrammarEventListener` base class with `enter<Rule>` /
   `exit<Rule>` / `visitTerminal` stubs and token-type constants.

3. **Subclass it** and override only the callbacks you care about:

   ```python
   from my_listener import MyGrammarEventListener
   from generated.MyGrammarLexer import MyGrammarLexer
   from generated.MyGrammarParser import MyGrammarParser

   class Collector(MyGrammarEventListener):
       def enterPair(self) -> None:
           ...
       def visitTerminal(self, token_type: int, text: str) -> None:
           ...

   Collector().walk(source_text, MyGrammarLexer, MyGrammarParser)
   ```

Only the callbacks you override drive native masks, so the C++ side skips every
other rule/token — the fewer node kinds you subscribe to, the faster the walk.

## How it works

- The C++ extension deserializes the ATN from your generated lexer/parser and
  drives `LexerInterpreter` / `ParserInterpreter` — no generated C++ parser.
- A native iterative DFS over the finished parse tree appends fixed
  `(kind, payload, start, stop)` int32 records to one buffer (`parse_events`).
- `kind`: `0=ENTER_RULE, 1=EXIT_RULE, 2=TERMINAL, 3=ERROR`; `payload` is the rule
  index or token type; `start`/`stop` are char indices into the source (`-1` for
  rule events). Token text is recovered Python-side by slicing
  `text[start:stop + 1]` — no string copies cross the boundary.
- Rule/token masks built from your overrides filter the stream in C++.

## Limitations

This runtime executes the **interpreted ATN**; it cannot run target-language
**semantic predicates or embedded grammar actions**. Grammars that depend on
them will not parse correctly here. See `docs/` for the full discussion and the
performance characteristics of the bulk event-stream approach.

## Development

This project uses [pixi](https://pixi.sh). The toolchain (C++ compiler, CMake,
Ninja, nanobind, scikit-build-core) comes from the pixi environment, so the
editable `editable.rebuild` hook always finds a persistent CMake on `PATH`.

```sh
pixi install            # solve + build the editable extension
pixi run test           # run the pytest suite (test environment)
pixi run example        # run the JSON reconstruction example
pixi run docs-serve     # preview the docs site at http://localhost:8000
pixi run docs-build     # build the static docs site into site/
```

Environments:

- **default / test** — Python build + test toolchain (no JDK).
- **gen** — adds `openjdk` + the ANTLR tool, isolated from the runtime envs.
  Regenerate the example from the grammar with `pixi run gen-json` (re-runs the
  ANTLR Python target on `examples/json/JSON.g4`) and `pixi run gen-facade`.
- **docs** — [Zensical](https://zensical.org) static site generator, isolated
  with no default feature so building the docs pulls neither the JDK nor the C++
  toolchain. Configured by `zensical.toml`; output goes to `site/` (gitignored).

The vendored ANTLR C++ runtime is built from `vendor/antlr4-cpp/`; see
`vendor/antlr4-cpp/UPDATING.md` to refresh the snapshot.

## Documentation

Full docs are in [`docs/`](docs/index.md): [how it works](docs/concepts.md),
[API reference](docs/api.md),
[migrating from antlr4-python3-runtime](docs/migrating.md), and
[performance & limitations](docs/performance.md).

## License

Apache-2.0. Bundles the ANTLR4 C++ runtime (BSD-3-Clause) under
`vendor/antlr4-cpp/`; see `vendor/antlr4-cpp/UPDATING.md` for provenance.
