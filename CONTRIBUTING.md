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
pixi run test           # run the pytest suite (test environment)
pixi run example        # run the JSON reconstruction example
pixi run docs-serve     # preview the docs site at http://localhost:8000
pixi run docs-build     # build the static docs site into site/
```

## Environments

- **default / test** — Python build + test toolchain (no JDK).
- **gen** — adds `openjdk` + the ANTLR tool, isolated from the runtime envs.
  Regenerate the example from the grammar with `pixi run gen-json` (re-runs the
  ANTLR Python target on `examples/json/JSON.g4`) and `pixi run gen-facade`.
- **docs** — [Zensical](https://zensical.org) static site generator, isolated
  with no default feature so building the docs pulls neither the JDK nor the C++
  toolchain. Configured by `zensical.toml`; output goes to `site/` (gitignored).

## Vendored runtime

The vendored ANTLR C++ runtime is built from `vendor/antlr4-cpp/`; see
`vendor/antlr4-cpp/UPDATING.md` to refresh the snapshot.

## Before submitting

- Run `pixi run test` and make sure the suite is green.
- If you changed the docs, confirm `pixi run docs-build` succeeds.
