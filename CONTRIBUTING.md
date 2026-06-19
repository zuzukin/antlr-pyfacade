# Contributing

Thanks for your interest in improving `antlrope`. This page covers the
local development setup; for what the package does and how to use it, see the
[README](README.md) and the [docs](docs/index.md).

## Development environment

This project uses [pixi](https://pixi.sh). The toolchain (C++ compiler, CMake,
Ninja, nanobind, scikit-build-core) comes from the pixi environment, so the
editable `editable.rebuild` hook always finds a persistent CMake on `PATH`.

```sh
pixi install            # solve + build the editable extension
pixi run build          # rebuild the _native C++ extension after editing C++
pixi run test           # run the pytest suite
pixi run example        # run the JSON reconstruction example
pixi run docs-serve     # preview the docs site at http://localhost:8000
pixi run docs-build     # build the static docs site into site/
```

## Environments

- **default** — Python build + test toolchain (no JDK); `pixi run test` lives here.
- **gen** — adds `openjdk` + the ANTLR tool, isolated from the runtime envs.
  Regenerate the example from the grammar with `pixi run gen-json` (re-runs the
  ANTLR Python target on `examples/json/JSON.g4`) and `pixi run gen-facade`.
- **docs** — [Zensical](https://zensical.org) static site generator, isolated
  with no default feature so building the docs pulls neither the JDK nor the C++
  toolchain. Configured by `zensical.toml`; output goes to `site/` (gitignored).

## The native extension and its type stub

The C++ engine is the nanobind module `antlrope._native`, built from
`cpp/binding.cpp` against the vendored runtime. The C++ rarely changes, so it is
**not** rebuilt on import (`editable.rebuild = false`). After editing anything
under `cpp/` or `vendor/antlr4-cpp/`, recompile explicitly:

```sh
pixi run build      # incremental cmake build + install (scripts/build_native.py)
```

Then `pixi run test` runs against the fresh build. Because import never invokes
the build toolchain, the package imports fine from any interpreter — including an
IDE that points at `.pixi/envs/default` without activating it (e.g. PyCharm using
the env prefix as a plain interpreter); no `cmake` on `PATH` is required.

`_native` is a compiled module loaded through scikit-build-core's editable
redirector, which IDEs and type checkers cannot follow. A checked-in stub,
`src/antlrope/_native.pyi`, gives them the interface (and the `py.typed`
marker advertises the package as typed). If you change the **public interface** of
`cpp/binding.cpp` — add or rename a class, method, or function, or change a
signature — rebuild, then regenerate the stub:

```sh
pixi run build
pixi run stubgen
```

`pixi run stubgen` runs `scripts/stubgen.py`, which invokes nanobind's stubgen and
then re-applies the edits nanobind cannot infer — the license header and the
`parse_events` / `lex` return types — so the committed stub is produced directly.
To change those edits, edit `scripts/stubgen.py`, not the `.pyi`.

## Docstrings

Docstrings are rendered into the API docs by mkdocstrings, which resolves
cross-references written as `[title][path.to.symbol]` (e.g.
`[walk_parallel][antlrope.FacadeListener.walk_parallel]`).

**Do not wrap the cross-reference title in backticks.** Write `[title][ref]`, not
`` [`title`][ref] ``. Backticks render the title as inline code, which visually
hides that the text is a clickable link — the reference still resolves, but
readers can't tell it's a link. Plain `[title][ref]` renders as a normal styled
link. Backticks are still correct for inline code that is *not* a cross-reference
(a parameter or type name with no `][ref]` after it).

## `llms.txt`

`docs/llms.txt` is a hand-written, LLM-oriented summary of the library (install, the
generate → facade → `walk` workflow, the listener model, the public API, and doc
links), published verbatim at the doc-site root (`/llms.txt`) for coding agents — see
[llmstxt.org](https://llmstxt.org/). It is **not generated**, so keep it in sync when
any of these change: the public API (`__all__`), the workflow or listener model,
install instructions, the supported Python/platform versions, or the doc page set and
`site_url` (its doc links are absolute). It is excluded from the rendered docs — no
nav, search, or sitemap — so `pixi run docs-build` will **not** flag it as stale.

## Version

The version lives in one place: `src/antlrope/VERSION`. The build reads it
(scikit-build-core's regex metadata provider) so the wheel and its
`importlib.metadata` follow it, and `antlrope.__version__` reads the same
file via `importlib.resources`. The conda recipe is the exception: it tracks the
*published* release it packages, not the dev version, so it pins its own value
(bumped per release).

**Policy: bump the patch on every commit that changes runtime behavior or
user-facing docs.** Edit `VERSION` in the same commit that touches the runtime
(`src/`, `cpp/`, `vendor/antlr4-cpp/`) or the external docs (`README.md`,
`docs/`). Build-only, test-only, or dev-tooling changes (pixi/CMake config,
`scripts/`, `CONTRIBUTING.md`, CI) don't need a bump. When you bump, add a matching
entry to [CHANGELOG.md](CHANGELOG.md). Bumping the file is enough for the version
itself — `__version__` reflects it immediately; run `pixi install` to refresh the
installed package metadata too.

## Vendored runtime

The vendored ANTLR C++ runtime is built from `vendor/antlr4-cpp/`; see
`vendor/antlr4-cpp/UPDATING.md` to refresh the snapshot.

## Before submitting

- If you changed C++ (`cpp/` or `vendor/antlr4-cpp/`), run `pixi run build` first.
- Run `pixi run test` and make sure the suite is green.
- If you changed `cpp/binding.cpp`'s public interface, run `pixi run stubgen` (it
  re-applies the hand edits automatically).
- If you changed the docs, confirm `pixi run docs-build` succeeds.
- If you changed the public API, the workflow, or the doc page set, update
  `docs/llms.txt` to match (it's hand-maintained and not flagged by `docs-build`).
