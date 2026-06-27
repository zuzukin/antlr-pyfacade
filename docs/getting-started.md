# Getting started

This walks you from a grammar to a working parser in three steps: **generate a
parser** from your grammar, **generate a [facade]**, and **write a listener**. The
whole thing is plain Python — no C/C++ to write or compile.

First, [install `antlrope` and the ANTLR tool](installation.md).

The examples below use a JSON grammar, which lives in the repository under
[`examples/json/`](https://github.com/zuzukin/antlrope/tree/dev/examples/json)
(see [Examples](examples/index.md) for the full programs). Swap in your own `.g4`
grammar and the steps are identical.

!!! note "Before you start: will this work with your grammar?"

    `antlrope` parses grammars that describe *structure* — data formats,
    config languages, most DSLs and programming languages. It does **not** run
    **[semantic predicates][semantic predicate]** (`{...}?`) or **[embedded actions][embedded action]** (`{...}` code)
    that some grammars use, because those are target-language code this runtime
    doesn't execute. If your grammar depends on them, use the official
    `antlr4-python3-runtime`. See
    [Performance & limitations](performance.md#limitation-semantic-predicates-and-embedded-actions).

## 1. Generate a parser from your grammar

Run the stock ANTLR tool with the **Python3** target. Nothing here is specific to
`antlrope` — this is the ordinary ANTLR workflow:

```sh
antlr4 -Dlanguage=Python3 JSON.g4 -o generated
```

This writes `generated/JSONLexer.py` and `generated/JSONParser.py` (plus a couple
of support files). These are the same files you'd use with the pure-Python
runtime.

## 2. Generate a facade

The *facade* is a small Python base class with one named callback per grammar
rule. Point `antlrope` at your generated **parser module** (an importable
dotted path) and give it a name prefix:

```sh
antlrope gen generated.JSONParser JSON -o json_listener.py
```

That emits `json_listener.py` containing a `JsonEventListener` class with:

- `enterJson` / `exitJson`, `enterObj` / `exitObj`, `enterPair` / … — a pair of
  callbacks for every rule in the grammar,
- `visitTerminal(self, token_type, text)` and `visitError(self, token_type, text)`,
- token-type constants like `STRING = 10`, `NUMBER = 11`, and
- a `walk(text)` method that runs everything.

The facade imports your lexer and parser and bakes them in, so `walk` needs no
class arguments. It finds the lexer by ANTLR's `<Grammar>Lexer` / `<Grammar>Parser`
naming (here `generated.JSONLexer` next to `generated.JSONParser`); pass `--lexer`
to `antlrope` if your lexer module is named differently.

You don't edit this file — you subclass it.

## 3. Write a listener

Subclass the generated facade and override only the callbacks you need. Here is a
complete program that collects every string token in a JSON document:

```python
from json_listener import JsonEventListener        # from step 3

class StringCollector(JsonEventListener):
    def __init__(self):
        self.strings = []

    def visitTerminal(self, token_type, text):
        if token_type == self.STRING:        # STRING is a generated constant
            self.strings.append(text)

c = StringCollector()
c.walk('{"name": "ada", "tags": ["x", "y"]}')
print(c.strings)
```

Running it prints every string literal, quotes included (the callback receives the
raw source slice for the token):

```text
['"name"', '"ada"', '"tags"', '"x"', '"y"']
```

That's the whole model:

- **Rule callbacks take no arguments.** There are no node objects — you keep your
  own state. The common pattern is a small stack: push on `enter`, pop on `exit`.
  See [`examples/json/to_python.py`](https://github.com/zuzukin/antlrope/blob/dev/examples/json/to_python.py),
  which rebuilds a JSON document into Python objects using `enterObj`/`exitObj`,
  `enterArr`/`exitArr`, `enterPair`, and `visitTerminal`.
- **`visitTerminal(token_type, text)`** gives you the token's type (compare against
  the generated constants) and its text, already sliced from the source.
- **Override only what you need.** The callbacks you define are the only events
  the C++ side bothers to send to Python — fewer overrides, faster walk.

## Scope and source helpers

You don't have to track nesting by hand. While a callback runs, the listener knows
where it is:

- **`self.depth()`** — current nesting depth; **`self.rule_stack()`** — the open
  rule names, outermost first; **`self.current_rule()`** — the innermost open rule
  (e.g. inside `visitTerminal`, the rule the token belongs to). These count the
  rules you actually subscribe to — the constructs *you* track. Override
  `enterEveryRule`/`exitEveryRule` (no-op hooks called on every rule) to track the
  full parse tree instead.
- **`self.text()`** — the source slice of the current event. For a token it's the
  token text; for a rule it's the rule's whole extent (e.g. the full `{...}` in
  `exitObj`), so you don't have to keep the source around and slice `span()`.
- **`self.token_name(t)` / `self.rule_name(i)`** — names for a token type or rule
  index, handy for logging or a generic `visitTerminal`.

So the JSON-style "push on enter, pop on exit" stack is only needed when you're
*building a result*; for "how deep am I / what am I inside / what's the text here"
the helpers above already answer it.

## Handling parse errors

By default ANTLR prints `line X:Y ...` messages to stderr. The facade captures
them instead, so nothing is printed and you decide what to do. After `walk`, the
errors from that parse are on `self.syntax_errors`:

```python
c = StringCollector()
c.walk('{"a": 1 2}')     # the stray 2 is a syntax error
for err in c.syntax_errors:
    print(f"{err.line}:{err.column}: {err.message}")
```

```text
1:8: extraneous input '2' expecting {',', '}'}
```

`syntax_errors` is reset on every `walk`, and is an empty list after a clean
parse.

## Where to go next

- [Migrating from antlr4-python3-runtime](migrating.md) — if you already have a
  `ParseTreeListener`, this maps each piece onto the facade.
- [Parallel parsing](performance.md#parallel-parsing) — if your input is many
  independent pieces (records, definitions, sections), parse them
  concurrently with [`walk_parallel`](parallel-parsing.md).
- [API reference](reference/api.md) — every callback, `walk` option, source-position
  helpers, and the raw event buffer for power users.
- [How it works](concepts.md) — optional background on why batching the events
  makes it fast.

[facade]: glossary.md#facade
[semantic predicate]: glossary.md#semantic-predicate
[embedded action]: glossary.md#embedded-action
