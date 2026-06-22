# Chunking

When your input is many independent pieces — records, log lines, top-level
definitions — you can split it into [`Chunk`](reference/api.md#antlrope.Chunk)s
and parse them in parallel with
[`walk_parallel`](parallel-parsing.md). The generated `<Grammar>EventListener`
provides chunking **classmethods** that produce those chunks, each carrying its
exact source position so callbacks still report positions against the whole source.
The token- and rule-based ones use the [facade]'s baked-in lexer/parser and its
token-type constants, so you call them on the class and pass no lexer/parser.

There are four families, trading correctness against speed. Pick by constraint,
not just speed — the splitting cost is usually negligible next to the per-chunk
parse it feeds.

## Token-based — split at lexer tokens

A single lexer pass (in C++, no parser) finds the boundaries, so a delimiter that
appears **inside a string or comment never causes a split**. The splitter asks the
lexer for only the boundary tokens, so little crosses into Python.

```python
# each chunk begins with a delimiter token (one type, or several):
chunks = MyGrammarEventListener.split_on_token(
    text, MyGrammarEventListener.RECORD, where="before"
)
# or one chunk per open..close region (optionally balanced):
chunks = MyGrammarEventListener.split_between_tokens(
    text, (MyGrammarEventListener.BEGIN, MyGrammarEventListener.END), nested=True
)
```

- [`split_on_token`](reference/api.md#antlrope.FacadeListener.split_on_token) —
  split at each delimiter token; `where="before"|"after"` puts the delimiter at the
  start or end of each chunk.
- [`split_between_tokens`](reference/api.md#antlrope.FacadeListener.split_between_tokens) —
  one chunk per opener/closer region; multiple bracket kinds each match their own
  partner, and `nested=True` matches balanced pairs.
- [`lex`](reference/api.md#antlrope.FacadeListener.lex) — the underlying
  parser-free token pass, exposed directly if you want the token stream.

## Regex-based — split on a pattern

No lexer at all: roughly an order of magnitude faster at finding delimiters, but
**not token-aware** (a match inside a string still splits). Prefer it when the
delimiter can't appear in disguise.

- [`split_on_pattern`](reference/api.md#antlrope.FacadeListener.split_on_pattern) —
  the regex analogue of `split_on_token`; the pattern matches the delimiter.
- [`chunk_by_pattern`](reference/api.md#antlrope.FacadeListener.chunk_by_pattern) —
  the pattern matches a whole record, so each match *is* a chunk.

## Rule-based — split on grammar structure

[`chunk_by_rule`](reference/api.md#antlrope.FacadeListener.chunk_by_rule) parses the
input (entirely in C++) and yields each occurrence of a grammar rule as a chunk —
cutting on real structure rather than a token/regex heuristic. It pays for a
structural parse, but only the spans cross into Python, so it's worth it when the
per-chunk `walk_parallel` callback work dominates, or when no delimiter cleanly marks
a record.

```python
# one chunk per top-level function:
chunks = MyGrammarEventListener.chunk_by_rule(text, "function")
```

See [Performance & limitations](performance.md#chunking-lexer-vs-regex) for measured
token-vs-regex-vs-rule numbers and the speed/correctness trade-off.

## Streaming — bounded memory

For input too large to hold in memory, the streaming chunkers read incrementally
and yield chunks without retaining the whole source, so paired with `walk_parallel`
the pipeline stays bounded.

- [`stream_on_token`](reference/api.md#antlrope.FacadeListener.stream_on_token) —
  the streaming form of `split_on_token`. The native layer opens the file and lexes
  it over a sliding window (UTF-8).
- [`stream_on_pattern`](reference/api.md#antlrope.FacadeListener.stream_on_pattern) —
  the streaming form of `split_on_pattern`. The regex runs Python-side, so it reads
  any text source (a path, an open file, or an iterable of `str`) in **any** encoding.
- [`stream_by_rule`](reference/api.md#antlrope.FacadeListener.stream_by_rule) — the
  streaming form of `chunk_by_rule`, for input that is a top-level **sequence of
  records**, each an occurrence of a grammar `rule` (or one of several). It parses one
  record at a time over a bounded-memory lexer→parser pipeline. Records must be
  **directly adjacent** (only lexer-skipped whitespace/comments between them); with
  several candidate rules the next token chooses which to parse, so they should have
  disjoint leading tokens (e.g. `class` vs `def`). If an on-channel token begins no
  candidate rule (an unsupported header or separator), it **raises** a clear error
  naming the token and candidates rather than silently truncating. Unlike
  `chunk_by_rule` it does not find a rule *anywhere* in a full parse — for arbitrary
  nesting or comma-separated records, use `chunk_by_rule` or `stream_on_token`.

## Source positions and names

Every chunk carries its start `(offset, line, column)` against the whole source, so
callbacks still report positions against the original after splitting. Each chunker
also takes a `sourcename=` (a filename for diagnostics) recorded on every chunk — the
streaming chunkers default it to their file path. During the parse it surfaces as
[`FacadeListener.sourcename()`](reference/api.md#antlrope.FacadeListener.sourcename),
so a callback can report a position as `sourcename:line:column`.

By default each chunk is **trimmed** of surrounding whitespace and whitespace-only
regions are dropped. Pass `trim=False` (on the delimiter chunkers) to keep every
region verbatim — preserving a leading or trailing whitespace terminator such as a
record's mandatory newline — dropping only truly empty, zero-length regions.

## Leading and trailing regions (the preamble)

With `where="before"`, content *before the first delimiter* becomes its own leading
chunk — often a file's header or preamble; with `where="after"`, content *after the
last delimiter* is a trailing chunk. Neither is special — each is just the first or
last chunk — so skip or handle it explicitly. The
[streaming-records recipe](streaming-records.md) walks through preamble handling,
`trim=False` terminators, absolute positions, and recovering off-channel metadata end
to end.

[facade]: glossary.md#facade
