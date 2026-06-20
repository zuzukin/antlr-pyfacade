# Schema: parallel & streaming indexing

This example indexes a **schema file** — a flat sequence of independent type
definitions, the shape of a protobuf / Thrift / Cap'n Proto IDL — and shows how to
scale the same listener from one document to a huge file. The full program is
[`examples/schema/index.py`](https://github.com/zuzukin/antlrope/blob/dev/examples/schema/index.py).

It's the natural counterpart to the [JSON example](json.md): there, one document
drives one walk; here, *many independent records* drive a chunk-and-parse pipeline.

## The grammar

[`Schema.g4`](https://github.com/zuzukin/antlrope/blob/dev/examples/schema/Schema.g4)
defines a file as a sequence of `message` (struct) and `enum` definitions:

```antlr
schema      : definition* EOF ;
definition  : messageDef | enumDef ;

messageDef  : MESSAGE ID LBRACE field* RBRACE ;   // message Point { int x; int y; }
field       : fieldType ID SEMI ;
fieldType   : INT | STRING | BOOL | ID ;

enumDef     : ENUM ID LBRACE (ID (COMMA ID)*)? RBRACE ;   // enum Color { RED, GREEN }
```

Two properties make this a good fit for structural chunking:

- Each definition is **self-contained** — it parses on its own, independent of the
  others.
- A definition may **span many lines**, so a newline- or regex-split would cut it in
  the wrong place. But it is exactly one `messageDef` or one `enumDef`, which
  [`chunk_by_rule`](../chunking.md#rule-based-split-on-grammar-structure) and
  `stream_by_rule` cut on precisely.

The keywords and punctuation get named lexer rules (`MESSAGE`, `LBRACE`, …), so the
facade exposes readable constants (`self.MESSAGE`, `self.ID`) instead of positional
`T__n`.

## The listener

`SchemaIndexer` collects one `TypeDef` (kind, name, member names) per definition.
As in the JSON example there are no node objects — state is reconstructed from event
order. A definition is bracketed by `enter`/`exit{Message,Enum}Def`; inside it, the
first `ID` (before the `{`) is the type's name and the later `ID`s name its members:

```python
class SchemaIndexer(SchemaEventListener):
    def __init__(self) -> None:
        self.types: list[TypeDef] = []
        self._cur: TypeDef | None = None
        self._in_body = False
        self._last_id = ""

    def enterMessageDef(self) -> None: self._begin("message")
    def enterEnumDef(self) -> None:    self._begin("enum")
    def exitMessageDef(self) -> None:  self._commit()
    def exitEnumDef(self) -> None:     self._commit()

    def visitTerminal(self, token_type: int, text: str) -> None:
        cur = self._cur
        if cur is None:
            return
        if token_type == self.LBRACE:
            self._in_body = True                 # past the name, into the body
        elif token_type == self.ID:
            if not self._in_body:    cur.name = text          # the type's own name
            elif cur.kind == "enum": cur.members.append(text) # enum constants
            else:                    self._last_id = text     # message field name
        elif token_type == self.SEMI and cur.kind == "message":
            cur.members.append(self._last_id)    # the ID right before `;`
```

The same listener works whether it walks the whole file (accumulating every
definition into `self.types`) or a single definition (one entry) — which is what
lets all three modes below share it.

## Three ways to run it

### 1. One whole-file walk — the everyday path

```python
def index_whole(text: str) -> list[TypeDef]:
    return SchemaIndexer().walk(text, start_rule="schema").types
```

One C++ parse of the entire file. For input you can hold in memory with light
per-record work, this is the simplest and usually the fastest — there is no chunking
overhead, and one parse beats many.

### 2. Chunk by rule, parse across cores

```python
def index_parallel(text: str) -> list[TypeDef]:
    chunks = SchemaIndexer.chunk_by_rule(text, {"messageDef", "enumDef"})
    out: list[TypeDef] = []
    for listener in SchemaIndexer.walk_parallel(chunks, start_rule="definition"):
        out.extend(listener.types)
    return out
```

[`chunk_by_rule`](../chunking.md) parses the file once (in C++) to find each
top-level `messageDef` / `enumDef` span; passing a **set** of rules indexes both
kinds. [`walk_parallel`](../parallel-parsing.md) then re-parses each span as a
`definition` on a worker pool, yielding one listener per definition. The native
parses release the GIL and overlap across cores.

### 3. Stream by rule — bounded memory

```python
def index_streaming(path: str | Path) -> list[TypeDef]:
    chunks = SchemaIndexer.stream_by_rule(path, {"messageDef", "enumDef"})
    out: list[TypeDef] = []
    for listener in SchemaIndexer.walk_parallel(chunks, start_rule="definition"):
        out.extend(listener.types)
    return out
```

`stream_by_rule` opens the file in C++ and yields **one definition at a time**
without ever holding the whole source or token stream in memory. The candidate rules
have disjoint leading tokens (`message` vs `enum`), so the next token selects which
to parse. Paired with `walk_parallel` (which pulls chunks lazily), the whole
pipeline — read, chunk, parse — stays bounded in the file size. This is how you index
a schema far larger than RAM.

## Which one to use

Run the bundled sample to see the index:

```sh
$ cd examples/schema && python index.py
  enum    Color          { RED, GREEN, BLUE }
  message Point          { x, y }
  message Pixel          { at, color, alpha }
  ...
5 types  (3 message, 2 enum)
```

`python index.py --benchmark 50000` generates 50k definitions and times all three.
You'll find the **single whole-file walk wins** here — and that's the honest lesson:

- **Reach for chunking + `walk_parallel` when the per-record *parse* is the expensive
  part.** The speedup comes from overlapping the native parses (GIL released), so it
  scales with how parse-heavy the grammar is. This schema is trivial to parse, so the
  chunking overhead dominates and the single walk wins. For a parse-heavy grammar the
  result flips — see the [SystemRDL benchmark](../benchmarks/systemrdl.md), where the
  same pattern is ~20× faster than the pure-Python runtime.
- **Reach for streaming when the file doesn't fit in memory.** `stream_by_rule`'s
  value is *bounded memory*, independent of whether it's faster — it lets you index a
  10 GB schema on a laptop.
- **Otherwise, walk the whole file.** Don't chunk for its own sake.

See [Performance & limitations](../performance.md) for the measured trade-offs and
the rule of thumb on when each pays off.
