# Migrating from antlr4-python3-runtime

`antlr-pyfacade` does not replace the official runtime — you still generate your
parser with the stock tool, and the generated modules still import
`antlr4-python3-runtime`. What changes is **how you consume the parse**. This
page maps the official `ParseTreeListener` model onto the facade.

## Callback shape

| official `ParseTreeListener` | facade `<Grammar>EventListener` |
|---|---|
| `enterEveryRule(ctx)` / `enter<Rule>(ctx)` | `enter<Rule>(self)` — no `ctx` |
| `exitEveryRule(ctx)` / `exit<Rule>(ctx)` | `exit<Rule>(self)` — no `ctx` |
| `visitTerminal(node)` | `visitTerminal(self, token_type, text)` |
| `visitErrorNode(node)` | `visitError(self, token_type, text)` |

The big difference: **there are no node/context objects**. Callbacks carry no
parse-tree handles, because no Python parse tree is built. You reconstruct
whatever state you need from the *order* of enter/exit/terminal events — almost
always with an explicit stack.

## Getting token text

Official:

```python
def visitTerminal(self, node):
    text = node.getSymbol().text
```

Facade:

```python
def visitTerminal(self, token_type, text):
    ...  # text is already the sliced source for this token
```

The runtime slices `text[start : stop + 1]` for you, so there is no `Token`
object. You still get the position: inside any callback, `self.line_col()`
returns the current event's `(line, column)` and `self.span()` its raw
`(start, stop)` char offsets — see the
[source-location section](api.md#source-location-in-a-callback).

## Handling errors

Official code overrides `visitErrorNode(node)`; the facade gives you
`visitError(self, token_type, text)`, called for each error node the parser
produces while recovering. Combined with `self.line_col()`, that's enough to
report a parse failure:

```python
def visitError(self, token_type, text):
    pos = self.line_col()
    where = f"{pos[0]}:{pos[1]}" if pos else "?"
    print(f"{where}: unexpected {text!r}")
```

Error nodes always cross into Python even when you filter terminals, so you can
subscribe to errors alone without receiving every token.

The official runtime also installs a `ConsoleErrorListener` that prints
`line X:Y ...` to **stderr** unless you call `removeErrorListeners()`. The facade
does this for you: nothing is printed, and after `walk` the diagnostics are
available as `self.syntax_errors` — a list of `ParseError` records carrying
ANTLR's message plus `line`/`column`/`start`/`stop`:

```python
listener.walk(source_text, MyLexer, MyParser)
for err in listener.syntax_errors:
    print(f"{err.line}:{err.column}: {err.message}")
```

## Identifying rules and tokens

Official code often branches on `ctx.getRuleIndex()` or token types from the
generated parser. The facade gives you **named callbacks per rule**
(`enterObj`, `exitPair`, …) so you usually don't branch at all — you override
the specific rule you care about. For terminals, compare `token_type` against the
generated token-type constants on the facade class (`MyListener.STRING`, etc.).

## A worked example

`examples/json/to_python.py` rebuilds a JSON document as native Python objects
using only `enterObj`/`exitObj`, `enterArr`/`exitArr`, `enterPair`, and
`visitTerminal`, with a small value stack. It is the canonical translation of a
tree-walking listener into the event-stream model.

## When to keep the pure-Python runtime

Prefer the official `antlr4-python3-runtime` (not this package) when:

- Your grammar uses **semantic predicates or embedded target-language actions** —
  the interpreted ATN cannot execute them (see
  [Performance & limitations](performance.md)).
- You need the **retained parse tree** itself (random access, XPath, rewriting,
  re-walking) rather than a single streaming pass.
- You need rich per-node context (`Token` objects, parent/child navigation)
  during the walk and can't reconstruct it from event order.
- The input is small enough that per-node FFI cost is irrelevant — the facade's
  advantage is throughput on large inputs.
