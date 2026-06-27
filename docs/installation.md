# Installation

## Install the package

From PyPI:

```sh
pip install antlrope
```

Or from [conda-forge](https://conda-forge.org/), with conda, mamba, or
[pixi](https://pixi.sh):

```sh
conda install -c conda-forge antlrope
# or:  mamba install -c conda-forge antlrope
# or:  pixi add antlrope
```

Either way pulls in the official `antlr4-python3-runtime` automatically — your
generated parser modules import it.

`antlrope` ships as a pre-compiled binary wheel (the C++ engine is built in),
so there is **nothing to compile** on install. A single CPython Stable ABI
(`abi3`) wheel per platform covers **CPython 3.12 and newer** (3.12, 3.13, 3.14,
…), published on:

- Linux ([manylinux], x86-64 and aarch64)
- macOS 11+ (Apple Silicon and Intel)
- Windows (x86-64)

The minimum supported Python is **3.12**.

## Type checking

`antlrope` ships `py.typed` with full type information, so type checkers resolve its
public API and submodules out of the box — `from antlrope import Chunk,
FacadeListener, SourceMap` and `import antlrope.cli` all check cleanly.

If your checker reports `reportMissingImports` / "could not be resolved", it is
almost always pointed at the wrong interpreter — not the environment where
`antlrope` is installed. Point it at that environment:

- **Pyright**: set `pythonPath` (or `venvPath` + `venv`) in `pyrightconfig.json` /
  `pyproject.toml`, run it from the activated virtualenv, or pass
  `--pythonpath /path/to/venv/bin/python`.
- **mypy**: run it from the same environment, or use `--python-executable`.

Note the command-line interface lives in the `antlrope.cli` *package* (e.g.
`from antlrope.cli.generate import generate`), not as top-level re-exported names.

## Install the ANTLR tool (to generate parsers)

To turn a `.g4` grammar into the Python parser modules `antlrope` drives, you
also need the **ANTLR tool** itself, which is a Java program. The easiest way is the
`antlr4-tools` helper, which fetches the ANTLR jar (and a JDK on first use) for you:

```sh
pip install antlr4-tools     # provides the `antlr4` command
```

You only need this at build time, to (re)generate parsers — not to run them. If you
already have Java and the ANTLR jar, use those instead; nothing here is specific to
`antlrope`.

See [Getting started](getting-started.md) for the full generate → write a listener →
run walkthrough.

## From source

The repository builds with [pixi](https://pixi.sh): `pixi run build` compiles the
C++ extension and `pixi run test` runs the suite. The build needs a C++17 compiler,
CMake ≥ 3.21, and Ninja (all provided by the pixi `dev` environment). See the
[repository](https://github.com/zuzukin/antlrope) for details.

[manylinux]: glossary.md#manylinux
