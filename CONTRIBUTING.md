# Contributing

Thanks for your interest in improving `antlr-pyfacade`. This page covers the
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

The C++ engine is the nanobind module `antlr_pyfacade._native`, built from
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
`src/antlr_pyfacade/_native.pyi`, gives them the interface (and the `py.typed`
marker advertises the package as typed). If you change the **public interface** of
`cpp/binding.cpp` — add or rename a class, method, or function, or change a
signature — rebuild, then regenerate the stub:

```sh
pixi run build
pixi run stubgen
```

`stubgen` imports the freshly built module and overwrites the stub, so re-apply
the two hand edits its header comment documents (the module `__version__` and the
`parse_events` return type), which nanobind cannot infer.

## Vendored runtime

The vendored ANTLR C++ runtime is built from `vendor/antlr4-cpp/`; see
`vendor/antlr4-cpp/UPDATING.md` to refresh the snapshot.

## Before submitting

- If you changed C++ (`cpp/` or `vendor/antlr4-cpp/`), run `pixi run build` first.
- Run `pixi run test` and make sure the suite is green.
- If you changed `cpp/binding.cpp`'s public interface, run `pixi run stubgen` and
  re-apply the two hand edits documented in `_native.pyi`.
- If you changed the docs, confirm `pixi run docs-build` succeeds.
