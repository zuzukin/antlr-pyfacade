# antlr-pyfacade documentation

A fast, C++-accelerated [ANTLR](https://www.antlr.org/) runtime for Python that
needs **no per-grammar C/C++ compilation by the user**. You generate your parser
with the ordinary ANTLR tool targeting Python, install this package, generate a
small *facade*, and write a pure-Python event listener. Parsing runs inside the
official ANTLR4 **C++** runtime; results cross into Python as a single bulk,
filtered event stream rather than a per-node parse-tree walk.

It **complements** the official `antlr4-python3-runtime`: same generated parser,
a faster way to consume it.

## Contents

- [Quickstart](https://github.com/analog-cbarber/antlr-pyfacade#quickstart) —
  install → generate → facade → walk, in one page.
- [How it works](concepts.md) — the bulk filtered event stream, native masks,
  and why this is faster than a per-node listener.
- [API reference](api.md) — the facade base class, `walk` options, `load_specs`,
  the raw `parse_events` buffer format, and the diagnostic helpers.
- [Migrating from antlr4-python3-runtime](migrating.md) — event listener vs
  `ParseTreeListener`, text-by-slicing, and when to keep the pure-Python runtime.
- [Performance & limitations](performance.md) — the honest ceiling of a
  pure-Python interface, and the semantic-predicate / embedded-action boundary.

## At a glance

```python
from my_listener import MyGrammarEventListener      # antlr-pyfacade-gen output
from generated.MyGrammarLexer import MyGrammarLexer  # stock ANTLR Python output
from generated.MyGrammarParser import MyGrammarParser

class Collector(MyGrammarEventListener):
    def enterPair(self) -> None:
        ...
    def visitTerminal(self, token_type: int, text: str) -> None:
        ...

Collector().walk(source_text, MyGrammarLexer, MyGrammarParser)
```
