# Chunking

When your input is many independent pieces — records, log lines, top-level
definitions — you can split it into [`Chunk`](reference/api.md#antlr_pyfacade.Chunk)s
and parse them in parallel with
[`walk_parallel`](parallel-parsing.md). The `antlr_pyfacade.chunking` helpers
produce those chunks, each carrying its exact source position so callbacks still
report positions against the whole source.

There are four families, trading correctness against speed. Pick by constraint,
not just speed — the splitting cost is usually negligible next to the per-chunk
parse it feeds.

## Token-based — split at lexer tokens

A single lexer pass (in C++, no parser) finds the boundaries, so a delimiter that
appears **inside a string or comment never causes a split**. The splitter asks the
lexer for only the boundary tokens, so little crosses into Python.

```python
from antlr_pyfacade import split_on_token, split_between_tokens

# each chunk begins with a delimiter token (one type, or several):
chunks = split_on_token(text, MyLexer, MyLexer.RECORD, where="before")
# or one chunk per open..close region (optionally balanced):
chunks = split_between_tokens(text, MyLexer, (MyLexer.BEGIN, MyLexer.END), nested=True)
```

- [`split_on_token`](reference/api.md#antlr_pyfacade.split_on_token) — split at each
  delimiter token; `where="before"|"after"` puts the delimiter at the start or end
  of each chunk.
- [`split_between_tokens`](reference/api.md#antlr_pyfacade.split_between_tokens) —
  one chunk per opener/closer region; multiple bracket kinds each match their own
  partner, and `nested=True` matches balanced pairs.
- [`lex`](reference/api.md#antlr_pyfacade.lex) — the underlying parser-free token
  pass, exposed directly if you want the token stream.

## Regex-based — split on a pattern

No lexer at all: roughly an order of magnitude faster at finding delimiters, but
**not token-aware** (a match inside a string still splits). Prefer it when the
delimiter can't appear in disguise.

- [`split_on_pattern`](reference/api.md#antlr_pyfacade.split_on_pattern) — the regex
  analogue of `split_on_token`; the pattern matches the delimiter.
- [`chunk_by_pattern`](reference/api.md#antlr_pyfacade.chunk_by_pattern) — the pattern
  matches a whole record, so each match *is* a chunk.

## Rule-based — split on grammar structure

[`chunk_by_rule`](reference/api.md#antlr_pyfacade.chunk_by_rule) parses the input
(entirely in C++) and yields each occurrence of a grammar rule as a chunk — cutting
on real structure rather than a token/regex heuristic. It pays for a structural
parse, but only the spans cross into Python, so it's worth it when the per-chunk
`walk_parallel` callback work dominates, or when no delimiter cleanly marks a record.

```python
from antlr_pyfacade import chunk_by_rule

chunks = chunk_by_rule(text, MyLexer, MyParser, "function")  # one chunk per top-level function
```

See [Performance & limitations](performance.md#chunking-lexer-vs-regex) for measured
token-vs-regex-vs-rule numbers and the speed/correctness trade-off.

## Streaming — bounded memory

For input too large to hold in memory, the streaming chunkers read incrementally
and yield chunks without retaining the whole source, so paired with `walk_parallel`
the pipeline stays bounded.

- [`stream_on_token`](reference/api.md#antlr_pyfacade.stream_on_token) — the streaming
  form of `split_on_token`. The native layer opens the file and lexes it over a
  sliding window (UTF-8).
- [`stream_on_pattern`](reference/api.md#antlr_pyfacade.stream_on_pattern) — the
  streaming form of `split_on_pattern`. The regex runs Python-side, so it reads any
  text source (a path, an open file, or an iterable of `str`) in **any** encoding.

## Source positions and names

Every chunk is trimmed of surrounding whitespace and carries its start
`(offset, line, column)`; whitespace-only regions are skipped. Each chunker also
takes a `sourcename=` (a filename for diagnostics) recorded on every chunk — the
streaming chunkers default it to their file path. During the parse it surfaces as
[`FacadeListener.sourcename()`](reference/api.md#antlr_pyfacade.FacadeListener.sourcename),
so a callback can report a position as `sourcename:line:column`.
