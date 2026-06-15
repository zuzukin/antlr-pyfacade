# API reference

Everything is exported from the top-level `antlr_pyfacade` package.

> **Most users need only [the generated facade](#the-generated-facade):** subclass
> it, override the callbacks you care about, and call `walk()`. If you're just
> getting started, read [Getting started](getting-started.md) first — this page is
> the complete reference. The sections after the facade (`load_specs`,
> `SourceMap`, the raw `parse_events` buffer, and the diagnostics helpers) are for
> power users who want lower-level access.

## The generated facade

`antlr-pyfacade` reads a stock-generated ANTLR Python parser module and emits
a `<Grammar>EventListener` base class. You subclass it and override callbacks.

### Generating

```sh
antlr-pyfacade <parser_module> <Grammar> [-o OUTPUT]
```

- `<parser_module>` — importable dotted path to the generated parser module,
  e.g. `mypkg.generated.MyParser`. It must be importable (the official
  `antlr4-python3-runtime` must be installed, since the generated module
  subclasses it).
- `<Grammar>` — the class-name prefix for the emitted facade
  (`<Grammar>EventListener`).
- `-o OUTPUT` — write to a file instead of stdout.

### The emitted base class

```python
class MyGrammarEventListener(FacadeListener):
    ruleNames = [...]          # rule names, in rule-index order
    START_RULE = 0             # index of the entry rule
    # token-type constants, e.g.  STRING = 10, NUMBER = 11, ...

    def enter<Rule>(self) -> None: ...      # one pair per grammar rule
    def exit<Rule>(self) -> None: ...
    def visitTerminal(self, token_type: int, text: str) -> None: ...
    def visitError(self, token_type: int, text: str) -> None: ...

    def walk(self, text, lexer_cls, parser_cls, *,
             start_rule=None, filtered=True): ...          # returns self
    @classmethod
    def walk_parallel(cls, chunks, lexer_cls, parser_cls, *,
                      start_rule=None, max_workers=None,
                      filtered=True, factory=None) -> list: ...
```

**Contract:**

- Rule callbacks take **no arguments** — there are no node objects. Track state
  yourself (a stack is the usual pattern; see `examples/json/to_python.py`).
- `visitTerminal(token_type, text)` receives the integer token type (compare
  against the generated constants) and the already-sliced token text.
- `visitError(token_type, text)` fires for error nodes the parser produces while
  recovering (an unexpected token, or an inserted/missing one). For a missing
  token `text` is `""`. Error nodes are **always** delivered — they bypass the
  token mask — so you never silently lose a parse failure.
- Override only what you need. The set of overrides determines the native masks,
  so unsubscribed rules/tokens never cross into Python.
- `walk` builds and caches the native specs from `lexer_cls` / `parser_cls`
  (via [`load_specs`](#load_specs)) and runs the event stream. It returns `self`,
  so `result = MyListener().walk(text, L, P).result` works.
- `walk(..., filtered=False)` forces the full unfiltered stream.
- `start_rule` (on both `walk` and `walk_parallel`) chooses which grammar rule to
  parse as — a rule **name** (`"record"`), a rule **index**, or `None` for the
  grammar's start rule. Use it to parse a chunk that is one sub-rule rather than a
  whole document. See [`walk_parallel`](#walk_parallel) for parsing many such
  chunks concurrently.
- After `walk`, `self.syntax_errors` is the list of
  [`ParseError`](#parseerror) diagnostics from that parse (empty if it was
  clean); see [Collected parse errors](#collected-parse-errors).

### Source location in a callback

`<Grammar>EventListener` subclasses `FacadeListener`, which exposes the current
event's position — handy for reporting where an error occurred:

```python
def visitError(self, token_type: int, text: str) -> None:
    pos = self.line_col()        # (line, column) of the offending token, or None
    if pos is not None:
        line, col = pos
        print(f"{line}:{col}: unexpected {text!r}")
```

- `self.line_col()` → `(line, column)` of the current event's start (line
  **1-based**, column **0-based**, matching ANTLR's own `line:column` reports),
  or `None` when the event has no source span (e.g. an inserted/missing token,
  or an empty rule).
- `self.span()` → the raw `(start, stop)` character offsets of the current event.

These are valid for every callback — `enter<Rule>`/`exit<Rule>` report the rule's
extent, terminals and errors report the token. The underlying
[`SourceMap`](#sourcemap) is built once per `walk`, on first use.

### Collected parse errors

ANTLR's default error listener writes `line X:Y ...` to **stderr** during a
parse. The facade replaces it with a collecting listener, so nothing is printed
and you control reporting. After `walk`, `self.syntax_errors` holds the
[`ParseError`](#parseerror) records produced during recovery:

```python
listener.walk(source_text, MyLexer, MyParser)
for err in listener.syntax_errors:
    print(f"{err.line}:{err.column}: {err.message}")
```

`syntax_errors` is reset on every `walk`, so it always reflects the latest parse.

These diagnostics are distinct from the `visitError` callback: `visitError` fires
per error *node* in the tree (giving the offending token's type and text), while
`syntax_errors` carries ANTLR's human-readable message (`extraneous input ...`,
`missing ... at ...`) and position for each recovery action. Use whichever fits —
or both.

### Optional: restrict terminal tokens further

If your subclass overrides `visitTerminal` but only wants *specific* token types,
set a class attribute `TERMINAL_TOKENS` to an iterable of token-type ints; the
driver uses it as the token mask. Omit it to receive every terminal.

## `walk_parallel`

```python
listeners = MyListener.walk_parallel(
    chunks, lexer_cls, parser_cls, *,
    start_rule=None, max_workers=None, filtered=True, factory=None,
)
```

Parse independent `chunks` across a thread pool, yielding **one listener per
chunk, in input order**. Each chunk is a self-contained piece of source (e.g. one
record or top-level definition) that parses as `start_rule`. A fresh listener is
created per chunk — `cls()` by default, or `factory()` if given — walked over its
chunk, and yielded with whatever state it accumulated plus its `syntax_errors`.

`chunks` is any iterable of `str` or `Chunk`. A bare `str` is treated as
contiguous with the previous chunk (its source position is computed); a `Chunk`
bundles text with an explicit `offset` / `line` / `column`, so callbacks'
`span` / `line_col` report positions against the whole source. The result is a
**lazy iterator** — chunks are pulled and parsed on demand with at most
`max_workers` parses in flight, so neither the whole input nor all results are
held at once. Consume it incrementally, or `list(...)` it if you want them all.

- The native parse releases the GIL, so the parses overlap across cores. Each
  worker thread uses its own specs internally, so concurrent parses never contend.
- `start_rule` — rule name, rule index, or `None` for the grammar's start rule.
- `max_workers` — the maximum parses in flight (also the ordering window).
  Defaults to `os.cpu_count()`. With `1` it runs inline, without a pool.
- `factory` — a zero-arg callable returning a fresh listener, for subclasses whose
  constructor needs arguments. Defaults to the class itself.
- Parallel speedup is bounded by how parse-heavy the work is versus per-callback
  Python (the dispatch loop holds the GIL). See
  [Parallel parsing](performance.md#parallel-parsing) for measured numbers and the
  reasoning.

```python
# Split the source into independent pieces and parse them concurrently
# (see Chunking below for the built-in token-based splitters):
chunks = split_on_token(text, MyLexer, MyLexer.RECORD, where="before")
records = [
    ln.to_model()
    for ln in RecordListener.walk_parallel(
        chunks, MyLexer, MyParser, start_rule="record"
    )
]
```

## Chunking

When the input is many independent pieces, the `antlr_pyfacade.chunking` helpers
produce the `Chunk`s for [walk_parallel](#walk_parallel) by **token boundary** — a
single lexer pass (the cheap stage, in C++) rather than a hand-written regex — and
the chunks carry exact source positions automatically.

```python
from antlr_pyfacade import lex, split_on_token, split_between_tokens

tokens = lex(text, MyLexer)            # whole-source token list (parser-free)
# each chunk begins with a delimiter token (one type, or several):
chunks = split_on_token(text, MyLexer, MyLexer.RECORD, where="before")
# or one chunk per open..close region (optionally balanced):
chunks = split_between_tokens(text, MyLexer, (MyLexer.BEGIN, MyLexer.END), nested=True)
# multiple bracket kinds, each matched to its own partner:
chunks = split_between_tokens(text, MyLexer, [(LPAREN, RPAREN), (LBRACK, RBRACK)])
```

- `lex(text, LexerCls, *, keep=None)` → a list of `LexToken(type, channel, start,
  stop)` in source order (EOF omitted; `-> skip` tokens absent). `keep` limits the
  result to specific token types — the lexer drops the rest in C++, so only those
  cross into Python. The cheap, parser-free pass the splitters build on.
- `split_on_token(text, LexerCls, token_types, *, where="before"|"after",
  channel=0)` — split at each delimiter token. `token_types` is one type or several
  (any of them delimits). `before` starts each chunk with the delimiter; `after`
  ends each chunk with it.
- `split_between_tokens(text, LexerCls, pairs, *, nested=False, channel=0)` — one
  chunk per opener/closer region. `pairs` is an `(open, close)` pair or a list of
  them, and each side may be one or several token types. With multiple pairs (e.g.
  `[(LPAREN, RPAREN), (LBRACK, RBRACK)]`) each opener is matched only by a closer of
  its own pair, so distinct bracket kinds nest correctly. `nested=True` matches
  balanced pairs and emits the outermost regions.

The splitters ask `lex` for only their boundary tokens, so little crosses into
Python. Each chunk spans the source between consecutive boundaries, trimmed of
surrounding whitespace, with its start `(offset, line, column)` from a `SourceMap`
over the text; whitespace-only regions are skipped. Pass `channel=None` to split
on all channels. Token types come from the generated lexer's constants
(`MyLexer.RECORD`, `MyLexer.STRING`, …).

## `load_specs`

```python
parser_spec, lexer_spec = antlr_pyfacade.load_specs(lexer_cls, parser_cls)
```

Builds the native `ParserSpec` / `LexerSpec` from the stock-generated
`<Grammar>Lexer` / `<Grammar>Parser` classes by reading their `serializedATN()`,
`literalNames`, `symbolicNames`, `ruleNames`, `channelNames`, and `modeNames`.
Results are cached by the `(lexer_cls, parser_cls)` pair, so the ATN is
deserialized once. The facade's `walk` calls this for you; call it directly only
if you use the low-level `parse_events`.

**Threading.** For parallel parsing, prefer [`walk_parallel`](#walk_parallel),
which manages specs for you. If you drive `parse_events` directly across threads:
the vendored runtime's per-DFA locks mean a shared, cached spec is now both
thread-safe **and** scales (see [Parallel parsing](performance.md#parallel-parsing)).
`cached=False` is still available to force an independent spec per thread (neither
read from nor written to the cache) if you want to avoid any sharing — e.g. a
`threading.local` that builds one the first time each worker parses.

## `ParseError`

A single parse diagnostic, collected in place of ANTLR's stderr console listener.
Returned in the `errors` list of [`parse_events`](#parse_events-raw-buffer) and
exposed as `self.syntax_errors` on the facade. Read-only attributes:

- `line` — 1-based line of the offending token.
- `column` — 0-based column of the offending token.
- `start` / `stop` — codepoint span of the offending token (matching the
  event-stream offsets), or `-1` when there is no token (e.g. a lexer error).
- `message` — ANTLR's human-readable message (`extraneous input '2' expecting
  ...`, `missing ',' at ...`, etc.).

## `SourceMap`

```python
sm = antlr_pyfacade.SourceMap(text)
line, column = sm.line_col(offset)
```

Converts a character `offset` (as reported by the event stream) into a
`(line, column)` position — line **1-based**, column **0-based**. The newline
scan runs once at construction; each `line_col` lookup is an O(log n) bisect.
The facade's `self.line_col()` uses this internally; construct one yourself when
working with the raw [`parse_events`](#parse_events-raw-buffer) buffer. A
negative offset raises `ValueError`.

## `parse_events` (raw buffer)

```python
raw, errors = antlr_pyfacade.parse_events(
    parser_spec, lexer_spec, text, start_rule,
    rule_mask=None, token_mask=None,
)
```

Runs lexer + parser + masked DFS and returns a `(events, errors)` tuple:

- `events` is the event buffer as `bytes` — a flat little-endian `int32` array of
  `4 * N` values (`N` records of `kind, payload, start, stop`).
- `errors` is a list of [`ParseError`](#parseerror) diagnostics collected during
  the parse (empty for a clean parse). The default ANTLR console error listener,
  which writes `line X:Y ...` to **stderr**, is suppressed — these structured
  records are how you observe a parse failure.

Decode the event buffer without a numpy dependency:

```python
import struct
for kind, payload, start, stop in struct.iter_unpack("<4i", raw):
    if kind == 2:                    # TERMINAL
        token_type, token_text = payload, text[start : stop + 1]
    elif kind == 0:                  # ENTER_RULE
        rule_index = payload
    elif kind == 1:                  # EXIT_RULE
        rule_index = payload
    elif kind == 3:                  # ERROR
        ...
```

`rule_mask` / `token_mask` are lists of indices to **keep**; `None` keeps all,
`[]` keeps none. Indices out of range and token type 0 (EOF/unused sentinel) are
handled safely. `ERROR` records are emitted regardless of `token_mask`, so a
filtered stream never drops parse failures.

For every record, `start` / `stop` are the character span of the item: the token
for `TERMINAL`/`ERROR`, and the rule's full extent (first token start … last
token stop) for `ENTER_RULE`/`EXIT_RULE`. An item with no span — an empty rule,
or an inserted/missing error token — reports `-1`. Turn an offset into a
position with [`SourceMap`](#sourcemap).

Kind constants: `ENTER_RULE=0`, `EXIT_RULE=1`, `TERMINAL=2`, `ERROR=3`.

## Diagnostics (secondary)

These are retained for benchmarking and debugging; the facade is the recommended
path.

- `parse_walk(parser_spec, lexer_spec, text, start_rule, listener)` — the classic
  per-node path: walks the tree dispatching into a Python `ParseTreeListener`
  subclass (`visitTerminal` / `visitErrorNode` / `enterEveryRule` /
  `exitEveryRule`, with node arguments). This is the **slow escape hatch** — it
  pays the per-node FFI crossing the event stream exists to avoid. Use it only
  when you genuinely need node objects.
- `parse_count(parser_spec, lexer_spec, text, start_rule)` — parse + walk with a
  native counting listener (no Python crossing); returns a dict of
  `terminals / errors / enters / exits / num_tokens`. Useful as a correctness
  reference for event tallies.
- `parse_stage_times(parser_spec, lexer_spec, text, start_rule)` — dict of
  per-stage seconds (`input_decode`, `lex_fill`, `parse_tree`, `walk`) plus
  token / event / codepoint counts, for decomposing where time goes.
- `atn_shape(serialized)` — deserialize a serialized ATN int list and report its
  shape (`grammar_type`, `num_states`, `num_decisions`, `num_rules`,
  `max_token_type`).

## Character index units

`start` / `stop` are **codepoint** offsets into the decoded source (the C++
runtime decodes input to UTF-32 internally), which line up exactly with Python
`str` indexing. `text[start : stop + 1]` is therefore correct for multibyte
UTF-8 source as long as `text` is the original `str`. (Don't slice a UTF-8
`bytes` view by these indices.)
