# Recipe: stream a file of records

When a file is a long sequence of independent records — log lines, NDJSON,
sensor readings, the top-level definitions of a source file — and is too large to
hold in memory, you can read, cut, and parse it as one bounded-memory pipeline: peak
memory is about one record plus the parses in flight, flat in the file size. This
recipe wires a streaming chunker to [`walk_parallel`](parallel-parsing.md) and walks
through the details that bite — the preamble, a whitespace terminator, absolute
positions, and metadata the parse tree can't see.

The running example: a file whose records are one per line, each parsed by a grammar
rule `record` (which ends in a mandatory `EOL`), generated as `RecordEventListener`.

## The pipeline

Split on the newline with `where="after"` so each chunk *ends* with its terminator,
and feed the lazy stream straight to `walk_parallel`:

```python
from record_listener import RecordEventListener as R

chunks = R.stream_on_pattern("big.log", r"\n", where="after", trim=False)
for listener in R.walk_parallel(chunks, start_rule="record"):
    ...  # one fully-walked listener per record, in input order
```

Both ends pull lazily: `stream_on_pattern` reads the file over a sliding window and
materializes one chunk at a time;
[`walk_parallel`](reference/api.md#antlrope.FacadeListener.walk_parallel) keeps a
bounded number of parses in flight. Nothing holds the whole file.

## Keep the terminator: `trim=False`

By default every chunker trims surrounding whitespace from each chunk and drops
whitespace-only regions. That is not what we want in this case: a `record` rule that ends in `EOL`
needs the trailing newline, and the default would strip it, so the parse fails on a
missing `EOL`. Pass `trim=False` to keep each region verbatim (only truly empty,
zero-length regions are dropped):

```python
# trim=True (default):  '{"a": 1}'      -> EOL gone, record won't match
# trim=False:           '{"a": 1}\n'    -> terminator preserved
```

`trim=False` is available on every delimiter chunker
([`split_on_token`](reference/api.md#antlrope.FacadeListener.split_on_token),
[`stream_on_token`](reference/api.md#antlrope.FacadeListener.stream_on_token),
[`split_on_pattern`](reference/api.md#antlrope.FacadeListener.split_on_pattern),
`stream_on_pattern`, …).

## The preamble (content before the first delimiter)

With `where="before"`, the region *before the first delimiter* becomes its own
leading chunk — a header or preamble; with `where="after"`, the region *after the
last delimiter* is a trailing chunk. So a file that opens with a header line and then
records, cut on a record marker, yields the header as the first chunk:

```python
stream = R.stream_on_pattern("big.log", r"^record\b", flags=re.MULTILINE, where="before")
header = next(stream)                                   # the pre-first-record preamble
for listener in R.walk_parallel(stream, start_rule="record"):
    ...                                                 # stream now yields only records
```

If the file may or may not have a preamble, don't assume the first chunk is one —
recognize it (a real record chunk starts with the marker; the preamble does not), or
choose a `where`/pattern that excludes it. The same leading/trailing region appears
with the in-memory `split_*` chunkers; see [Chunking](chunking.md#source-positions-and-names).

## Absolute positions

Each [`Chunk`](reference/api.md#antlrope.Chunk) pins its `offset` / `line` / `column`
against the whole file, not the chunk, and `walk_parallel` carries that through.
So inside a callback,
[`span`](reference/api.md#antlrope.FacadeListener.span) and
[`line_col`](reference/api.md#antlrope.FacadeListener.line_col) report whole-file
positions, and [`sourcename`](reference/api.md#antlrope.FacadeListener.sourcename)
(defaulting to the file path) lets you log `sourcename:line:column` — exactly as if
you had parsed the file in one piece.

## Recover off-channel metadata

The walk is channel-blind: `walk_parallel` walks the *parse tree*, which contains
only the tokens the parser consumed — the default channel. Tokens the lexer routed to
a hidden [channel][token channel] (comments, directives, alignment metadata) are never
in the tree, so they never reach `visitTerminal`. To recover them, lex the chunk text
yourself — [`lex`](reference/api.md#antlrope.FacadeListener.lex) returns *every* token
with its `channel` — and keep the off-channel ones. Because the chunk text is in hand
only while you hold the chunk, do it in an inline loop rather than the pure
`walk_parallel` form:

```python
for chunk in R.stream_on_pattern("big.log", r"\n", where="after", trim=False):
    listener = R().walk(chunk.text, start_rule="record")        # on-channel structure
    comments = [t for t in R.lex(chunk.text) if t.channel != 0]  # 0 = default channel
    # a LexToken's start/stop are offsets *within the chunk*; add chunk.offset
    # for whole-file positions:
    spans = [(chunk.offset + t.start, chunk.offset + t.stop) for t in comments]
```

This trades the thread pool for the chunk text; to keep both, lex inside a wrapper
generator that yields `(chunk, comments)` and parse the chunks in parallel separately.[^1]

## When records are not delimiter-marked

If records are defined by grammar structure rather than a delimiter — and the file is
a directly-adjacent top-level sequence of them — use
[`stream_by_rule`](reference/api.md#antlrope.FacadeListener.stream_by_rule), which
parses one record at a time and needs no delimiter. It requires the *whole* input to
be that sequence (only lexer-skipped whitespace/comments may separate records) and
raises a clear error if an on-channel token begins no candidate rule — an
unsupported header or separator results in an error, not a silently truncated
stream. For comma-separated or otherwise on-channel-delimited records, stay with
`stream_on_token` / `stream_on_pattern`.

## Cost of a full per-record listener

A full Python listener pays one loop iteration per kept event, so a record walked
with everything subscribed costs roughly its native parse again on the Python side.
Two levers claw it back, both covered in
[Performance](performance.md#where-the-speed-comes-from-and-its-ceiling): subscribe to
only the rules/tokens you need (the facade emits just those from C++), or aggregate in
a rule so fewer events cross into Python at all.

[token channel]: glossary.md#token-channel

[^1]: The need for a first-class channel-aware callback during the walk is
[tracked in issue #2](https://github.com/zuzukin/antlrope/issues/2).)
