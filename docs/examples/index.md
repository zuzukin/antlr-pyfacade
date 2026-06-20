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

## How the examples are published

The examples are **part of the repository, not the installed package**. `pip install
antlrope` gives you the runtime only — it does not ship the example grammars, their
generated parsers, or the sample data. To run an example, browse or clone the
`examples/` directory and run it in place.

This is deliberate: a runtime library's wheel should stay lean, and examples carry
things that don't belong in it — `.g4` grammars, ANTLR-generated parser modules,
sample inputs, and (sometimes) extra dependencies. Keeping them in the source tree
means the docs can link straight to runnable files, and you copy the one you want as
a starting point rather than importing it.

## Running them

Each grammar's parser is generated with the ordinary ANTLR tool and the facade with
`antlrope`; both are checked in, so the examples run as-is. With this repo's
[pixi](https://pixi.sh) tasks:

```sh
pixi run example          # JSON: reconstruct a value from argv
pixi run example-schema   # Schema: index the bundled sample.schema
```

Or directly, from inside an example's directory:

```sh
cd examples/json    && python to_python.py '{"a": [1, true], "b": "hi"}'
cd examples/schema  && python index.py            # the bundled sample
cd examples/schema  && python index.py --benchmark 50000   # time the three modes
```

To regenerate a parser or facade after editing a grammar (needs the `gen`
environment, which provides the JDK + ANTLR tool):

```sh
pixi run gen-schema           # Schema.g4      -> generated/Schema{Lexer,Parser}.py
pixi run gen-schema-facade    # generated parser -> schema_listener.py
pixi run format               # tidy the regenerated facade
```
