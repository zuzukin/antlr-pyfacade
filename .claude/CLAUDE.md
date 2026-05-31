# antlr-pyfacade — project context

A fast, C++-accelerated ANTLR runtime for Python with **no per-grammar C/C++
compilation by the user**. It drives the official ANTLR4 C++ runtime from the
serialized ATN that the stock `-Dlanguage=Python3` ANTLR tool already emits, and
hands Python a single bulk, filtered int32 event stream instead of a per-node
parse-tree walk. Users generate a parser with the normal ANTLR tool, install this
package, generate a small facade, and write a pure-Python event listener.

## Layout

- `src/antlr_pyfacade/` — the Python package (src/ layout).
  - `specs.py` — `load_specs(LexerCls, ParserCls)` reads ATN + metadata off the
    stock-generated Python lexer/parser classes; the grammar-agnostic bridge.
  - `facade_runtime.py` — `drive()`: introspects which callbacks a facade
    subclass overrides, builds native rule/token masks, runs the event loop.
  - `gen_facade.py` — the `antlr-pyfacade` console script; emits a
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
pixi run test           # pytest suite (test env)
pixi run example        # JSON reconstruction example
pixi run docs-build     # build the docs site into site/
pixi run gen-json       # regenerate the JSON example parser (gen env, needs JDK)
pixi run gen-facade     # regenerate the JSON facade
```

Environments: `default`/`test` (Python build + test, no JDK), `gen` (openjdk +
ANTLR tool, isolated), `docs` (Zensical, no default feature). The editable
install uses `no-build-isolation`, so cmake/ninja must be on PATH — they come
from the pixi env. After moving/renaming package files, `pixi reinstall` to
regenerate the editable import redirector.

## Build

scikit-build-core + nanobind + CMake. `editable.rebuild = true` recompiles
`_native` on import. `wheel.packages = ["src/antlr_pyfacade"]`. Extension built
with `STABLE_ABI` (abi3 only materializes on CPython 3.12+; older build
per-version). `MACOSX_DEPLOYMENT_TARGET = 11.0`. Minimum Python is **3.10** —
use modern typing (`list[...]`, `X | None`, `collections.abc` over `typing`).

## Known limitation

The pure-ATN interpreter **cannot evaluate target-language semantic predicates
(`{...}?`) or embedded actions (`{...}`)** — predicates are treated as true.
Grammars depending on them won't parse correctly. This is pinned by
`tests/test_predicate_limitation.py` and documented loudly; keep it that way.

## Conventions

- Default branch is `main`.
- Package license is **Apache-2.0**; the vendored runtime under `vendor/` stays
  **BSD-3-Clause** — never relicense vendored code.
- Public docs (README, `docs/`) compare only against alternatives the reader
  actually has (the official `antlr4-python3-runtime`). No internal research
  context, no testbed names.
- Dev/build details live in `CONTRIBUTING.md`, not the README.
- Never commit `.idea/`. Only commit when explicitly asked; never push without
  asking; never skip git hooks.
