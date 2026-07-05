# Installation

## Install the package

=== "pip"

    ```sh
    pip install antlrope
    ```
  
=== "conda"

    ```sh
    conda install -c conda-forge antlrope
    ```

=== "mamba"

    ```sh
    mamba install -c conda-forge antlrope
    ```

=== "pixi"

    ```sh
    pixi workspace channel add conda-forge
    pixi add antlrope
    ```

**Antlrope** depends on the official `antlr4-python3-runtime`, so it will be pulled in
automatically — your generated parser modules import it.

Antlrope ships as a pre-compiled binary wheel (the C++ engine is built in),
so there is nothing to compile on install. A single CPython Stable ABI
(`abi3`) wheel per platform covers CPython 3.12 and newer (3.12, 3.13, 3.14,
…), published on:

- Linux ([manylinux], x86-64 and aarch64)
- macOS 11+ (Apple Silicon and Intel)
- Windows (x86-64)

The minimum supported Python is **3.12**.

## Install the ANTLR tool (to generate parsers)

To turn a `.g4` grammar into the Python parser modules Antlrope drives, you
also need the **ANTLR tool** itself, which is a Java program. The easiest way is the
`antlr4-tools` helper, which fetches the ANTLR jar (and a JDK on first use) for you
and provides the `antlr4` command:

=== "pip"

    ```sh
    pip install antlr4-tools
    ```

=== "conda"

    ```sh
    conda install -c conda-forge antlr4-tools
    ```

=== "mamba"

    ```sh
    conda install -c conda-forge antlr4-tools
    ```

=== "pixi"

    ```sh
    pixi workspace channel add conda-forge
    pixi add antlr4-tools
    ```

You only need this at build time, to (re)generate parsers — not to run them. If you
already have Java and the ANTLR jar, use those instead; nothing here is specific to
Antlrope.

See [Getting started](getting-started.md) for the full generate → write a listener →
run walkthrough.

## From source

Clone the repo from https://github.com/zuzukin/antlrope:

=== "HTTPS"

    ```sh
    git clone https://github.com/zuzukin/antlrope.git
    ```
    
=== "SSH"

    ```sh
    git clone git@github.com:zuzukin/antlrope.git
    ```

=== "GitHub CLI"

    ```sh
    gh repo clone zuzukin/antlrope
    ```

The repository builds with [pixi](https://pixi.sh): `pixi run build` compiles the
C++ extension and `pixi run test` runs the suite. The build needs a C++17 compiler,
CMake ≥ 3.21, and Ninja (all provided by the pixi `dev` environment). See
[CONTRIBUTING.md](https://github.com/zuzukin/antlrope/blob/dev/CONTRIBUTING.md) for details.

[manylinux]: glossary.md#manylinux
