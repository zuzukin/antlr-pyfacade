# Examples

Two complete, runnable programs live in the
[`examples/`](https://github.com/zuzukin/antlrope/tree/dev/examples) tree of the
repository. Each pairs a small ANTLR grammar with a generated facade and a Python
consumer, so you can read the whole thing end to end:

- **[JSON: reconstruct a value](json.md)** — the basics. Subclass the generated
  facade, override a handful of callbacks, and rebuild a parsed JSON document into
  native Python objects with a small value stack. Start here.
- **[Schema: parallel & streaming indexing](schema.md)** — scale to large input. A
  tiny interface-definition language whose file is a sequence of independent
  `message` / `enum` definitions, indexed three ways: one whole-file walk, chunk +
  parse across cores, and bounded-memory streaming.

## What you need

The examples are **part of the repository, not the installed package** — installing
**Antlrope** gives you the runtime only, not the example grammars, their generated
parsers, or the sample data. To run one you need just two things:

- **Antlrope installed** in your environment (`pip install antlrope` or
  `conda install -c conda-forge antlrope`). The consumers depend only on Antlrope and
  the Python standard library — no other packages, and no pixi.
- **A copy of the `examples/` files** (see below). Each parser and facade is checked
  in, so the examples run as-is. A JDK and the ANTLR tool are needed only if you want
  to *regenerate* a parser after editing a grammar.

Use example files from the same version as your installed Antlrope. The generated
facades carry a provenance version; if it drifts the code still runs, but
`antlrope up-to-date <facade>` will flag the mismatch.

## Getting the example files

Clone the repository (works everywhere):

```sh
git clone --depth 1 https://github.com/zuzukin/antlrope
cd antlrope
```

Or, without git, pull down just the `examples/` directory (macOS / Linux; on GNU tar
add `--wildcards` before the pattern):

```sh
curl -L https://github.com/zuzukin/antlrope/archive/refs/heads/dev.tar.gz \
  | tar -xz --strip-components=1 '*/examples'
```

## Running them

Run a consumer from **inside its example directory** — the scripts import their facade
and generated parser by directory-relative name, so the working directory matters:

```sh
cd examples/json    && python to_python.py '{"a": [1, true], "b": "hi"}'
cd examples/schema  && python index.py                      # the bundled sample
cd examples/schema  && python index.py --benchmark 50000    # time the three modes
```

That is the whole story in an installed environment: `python`, the example files, and
Antlrope on the path.

### From a source-tree clone (pixi)

If you are working in a clone of the repo with [pixi](https://pixi.sh) set up, the
bundled tasks wrap the same commands:

```sh
pixi run example          # JSON: reconstruct a value from argv
pixi run example-schema   # Schema: index the bundled sample.schema
```

To regenerate a parser or facade after editing a grammar (needs the `gen`
environment, which provides the JDK + ANTLR tool):

```sh
pixi run gen-schema           # Schema.g4      -> generated/Schema{Lexer,Parser}.py
pixi run gen-schema-facade    # generated parser -> schema_listener.py
pixi run format               # tidy the regenerated facade
```
