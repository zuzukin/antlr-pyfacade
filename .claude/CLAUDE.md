# antlr-pyfacade — project context

A fast, C++-accelerated ANTLR runtime for Python with **no per-grammar C/C++
compilation by the user**. It drives the official ANTLR4 C++ runtime from the
serialized ATN that the stock `-Dlanguage=Python3` ANTLR tool already emits, and
hands Python a single bulk, filtered int32 event stream instead of a per-node
parse-tree walk. Users generate a parser with the normal ANTLR tool, install this
package, generate a small facade, and write a pure-Python event listener.

## Layout

- `src/antlr_pyfacade/` — the Python package (src/ layout).
  - `specs.py` — `load_specs(LexerCls, ParserCls)` / `load_lexer_spec` read ATN +
    metadata off the stock-generated Python lexer/parser classes; the
    grammar-agnostic bridge.
  - `base.py` — `FacadeListener` (base of every generated facade) and its
    `drive()` method: introspects which callbacks a subclass overrides, builds
    native rule/token masks, runs the event loop. Also `Chunk` and the
    `walk_parallel` thread-pool driver.
  - `chunking.py` — the chunkers that produce `Chunk`s for `walk_parallel`:
    `split_on_token` / `split_between_tokens` (token), `split_on_pattern` /
    `chunk_by_pattern` (regex), `chunk_by_rule` (grammar rule), `stream_on_token` /
    `stream_on_pattern` (bounded-memory streaming), and `lex`.
  - `location.py` — `SourceMap` (char offset ↔ line/column).
  - `generate.py` — the `antlr-pyfacade` console script; emits a
    `<Grammar>EventListener` base class from a generated parser module.
- `cpp/` — the nanobind extension sources (`binding.cpp`, `events.h`); module
  name `_native`.
- `vendor/antlr4-cpp/` — vendored ANTLR4 C++ runtime sources. **BSD-3-Clause**,
  kept separate from the package's own Apache-2.0 license. See its `UPDATING.md`
  before refreshing the snapshot.
- `examples/json/`, `examples/predicate/` — end-to-end examples that double as
  test fixtures.
- `tests/`, `docs/` (Zensical site, config in `zensical.toml`).

## Event stream

Records are `(kind, payload, start, stop)` int32, decoded via
`struct.iter_unpack("<4i", raw)`. `kind`: `0=ENTER_RULE, 1=EXIT_RULE,
2=TERMINAL, 3=ERROR`. `payload` is the rule index or token type. Token text is
recovered Python-side by slicing `text[start:stop + 1]` — no strings cross the
boundary. Only overridden rules/tokens are emitted (native filtering).

## Dev workflow (pixi)

```sh
pixi install            # solve + build the editable extension
pixi run build          # rebuild _native after editing cpp/ or vendor/ (cmake)
pixi run test           # pytest suite
pixi run example        # JSON reconstruction example
pixi run docs-build     # build the docs site into site/
pixi run stubgen        # regenerate _native.pyi after binding API changes
pixi run gen-json       # regenerate the JSON example parser (gen env, needs JDK)
pixi run gen-facade     # regenerate the JSON facade
```

Environments: `default` (Python build + test, no JDK), `gen` (openjdk + ANTLR
tool, isolated), `docs` (Zensical, no default feature), `recipe` (rattler-build).
The editable install uses `no-build-isolation`, so cmake/ninja must be on PATH —
they come from the pixi env.

## Build

scikit-build-core + nanobind + CMake. `editable.rebuild = false` — imports never
invoke the toolchain (so the package imports from any interpreter, even an
unactivated IDE prefix); after editing `cpp/` or `vendor/`, recompile explicitly
with `pixi run build` (a cmake build+install via `scripts/build_native.py`).
`wheel.packages = ["src/antlr_pyfacade"]`. Extension built with `STABLE_ABI` (abi3
only materializes on CPython 3.12+; older build per-version).
`MACOSX_DEPLOYMENT_TARGET = 11.0`. Minimum Python is **3.10** — use modern typing
(`list[...]`, `X | None`, `collections.abc` over `typing`).

Version is single-sourced in `src/antlr_pyfacade/VERSION` (pyproject reads it
dynamically; `antlr_pyfacade.__version__` reads it via `importlib.resources`). The
compiled `_native` module has a checked-in stub `src/antlr_pyfacade/_native.pyi`
(IDEs/type-checkers can't follow the editable redirector) — after changing the
binding's public interface, run `pixi run stubgen` (it re-applies the hand edits
automatically via `scripts/stubgen.py`).

## Known limitation

The pure-ATN interpreter **cannot evaluate target-language semantic predicates
(`{...}?`) or embedded actions (`{...}`)** — predicates are treated as true.
Grammars depending on them won't parse correctly. This is pinned by
`tests/test_predicate_limitation.py` and documented loudly; keep it that way.

## Conventions

- Default branch is `dev`.
- Bump the patch in `src/antlr_pyfacade/VERSION` and add a `CHANGELOG.md` entry on
  every commit that changes runtime behavior or user-facing docs (`README`,
  `docs/`); build/test/tooling-only changes don't bump. See `CONTRIBUTING.md`.
- Hand-authored `.py`/`.cpp` files carry the Apache-2.0 header; docstrings use
  mkdocstrings/Markdown style (single backticks, Google-style sections) — no
  reStructuredText roles or `::` directives. Cross-references are
  `[title][antlr_pyfacade.Symbol]` with a **plain** title — never backtick the
  title. `` [`title`][ref] `` renders the title as inline code, which hides that
  it's a clickable link. (Backticks remain correct for inline code that is *not* a
  cross-reference.)
- Package license is **Apache-2.0**; the vendored runtime under `vendor/` stays
  **BSD-3-Clause** — never relicense vendored code.
- Public docs (README, `docs/`) compare only against alternatives the reader
  actually has (the official `antlr4-python3-runtime`). No internal research
  context, no testbed names.
- Dev/build details live in `CONTRIBUTING.md`, not the README.
- `docs/llms.txt` is a hand-written LLM summary published verbatim at the doc-site
  root (`/llms.txt`) for coding agents. It is not generated and `docs-build` won't
  flag it as stale, so keep it in sync when the public API (`__all__`), the
  generate→facade→`walk` workflow, install steps, or the doc page set / `site_url`
  change. (It lives in `docs/`, so updating it bumps the version.)
- Never commit `.idea/`. Only commit when explicitly asked; never push without
  asking; never skip git hooks.
