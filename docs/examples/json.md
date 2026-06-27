# JSON: reconstruct a value

This example rebuilds a parsed JSON document into native Python objects — the
`{...}`/`[...]`/scalars you'd get from `json.loads`, but driven by the event stream
so you can see exactly how a consumer is written. The full program is
[`examples/json/to_python.py`](https://github.com/zuzukin/antlrope/blob/dev/examples/json/to_python.py);
it's the worked-out version of the `StringCollector` from
[Getting started](../getting-started.md).

## The grammar

A standard, target-agnostic JSON grammar
([`examples/json/JSON.g4`](https://github.com/zuzukin/antlrope/blob/dev/examples/json/JSON.g4)) —
no [embedded actions][embedded action] or [semantic predicates][semantic predicate], so the interpreted [ATN] parses it
faithfully. The rules that matter to the consumer are `obj`, `arr`, `pair`, and
`value`:

```antlr
obj   : '{' pair (',' pair)* '}' | '{' '}' ;
pair  : STRING ':' value ;
arr   : '[' value (',' value)* ']' | '[' ']' ;
value : STRING | NUMBER | obj | arr | 'true' | 'false' | 'null' ;
```

Generate the parser and the [facade] (already checked in):

```sh
antlr4 -Dlanguage=Python3 JSON.g4 -o generated
antlrope gen generated.JSONParser JSON -o json_listener.py
```

The facade, `JsonEventListener`, has an `enter`/`exit` pair per rule, a
`visitTerminal`, and token-type constants. The literal tokens `'true'` / `'false'` /
`'null'` are anonymous, so they take ANTLR's positional names `T__6` / `T__7` /
`T__8` (the values are token types 7/8/9 — the name is *not* the value); `STRING`
and `NUMBER` are named.

## The listener

The consumer keeps a **stack of partially-built containers**. There are no node
objects — you reconstruct structure from the order of events. Entering an `obj` or
`arr` pushes a new container; the scalars and nested containers seen until the
matching exit attach to it; exiting pops:

```python
class JsonValueBuilder(JsonEventListener):
    def __init__(self) -> None:
        self._stack: list = []      # open containers, innermost last
        self._keys: list = []       # pending object keys
        self._expect_key = False
        self.result = _MISSING

    def enterObj(self) -> None:  self._push({})
    def exitObj(self) -> None:   self._pop()
    def enterArr(self) -> None:  self._push([])
    def exitArr(self) -> None:   self._pop()
    def enterPair(self) -> None: self._expect_key = True   # next STRING is a key

    def visitTerminal(self, token_type: int, text: str) -> None:
        if token_type == _STRING:
            value = json.loads(text)            # unquote + unescape
            if self._expect_key:
                self._keys.append(value)
                self._expect_key = False
                return
        elif token_type == _NUMBER:  value = json.loads(text)
        elif token_type == _TRUE:    value = True
        elif token_type == _FALSE:   value = False
        elif token_type == _NULL:    value = None
        else:
            return                              # structural punctuation: { } [ ] : ,
        self._attach(value)
```

Two things worth noting:

- **Only the callbacks you define cross into Python.** `JsonValueBuilder` overrides
  `enterObj`/`exitObj`, `enterArr`/`exitArr`, `enterPair`, and `visitTerminal` — so
  the C++ side never sends `enterValue`, `enterJson`, etc. The fewer node kinds you
  subscribe to, the less work crosses the boundary.
- **Token text is recovered by slicing.** `visitTerminal` receives the token's type
  and its exact source text; no node objects or per-node [foreign-function][FFI] calls are
  involved.

`_attach` puts a finished value where it belongs — into the open list, under the
pending object key, or (at the top) as the final `result`. See the
[full file](https://github.com/zuzukin/antlrope/blob/dev/examples/json/to_python.py)
for `_push` / `_pop` / `_attach`.

## Running it

```sh
$ cd examples/json
$ python to_python.py '{"a": [1, true, null], "b": "hi"}'
{'a': [1, True, None], 'b': 'hi'}
```

The whole parse runs in C++; one bulk, filtered event stream drives the callbacks
above. For a single document this is the everyday path — `Collector().walk(text)`.
When you have *many* independent documents or a very large one, the next example
shows how to chunk and parse them in parallel.

[embedded action]: ../glossary.md#embedded-action
[semantic predicate]: ../glossary.md#semantic-predicate
[ATN]: ../glossary.md#atn
[facade]: ../glossary.md#facade
[FFI]: ../glossary.md#ffi
