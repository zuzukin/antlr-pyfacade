# Parallel parsing

When your input is many independent pieces that each parse on their own — records,
log entries, top-level definitions —
[`walk_parallel`](reference/api.md#antlr_pyfacade.FacadeListener.walk_parallel)
parses them across a thread pool. The native parse releases the GIL, so the parses
overlap across cores; one listener is produced per chunk, **in input order**.

```python
from my_listener import MyGrammarEventListener
from generated.MyGrammarLexer import MyGrammarLexer
from generated.MyGrammarParser import MyGrammarParser
from antlr_pyfacade import split_on_token

chunks = split_on_token(text, MyGrammarLexer, MyGrammarLexer.RECORD, where="before")

for listener in MyGrammarEventListener.walk_parallel(
    chunks, MyGrammarLexer, MyGrammarParser, start_rule="record"
):
    ...  # one fully-walked listener per chunk, in order
```

## Input: strings or positioned chunks

`walk_parallel` accepts an iterable of `str` **or**
[`Chunk`](reference/api.md#antlr_pyfacade.Chunk):

- a bare `str` is treated as contiguous with the previous item, and its source
  position is computed for you;
- a `Chunk` pins an explicit `offset` / `line` / `column` (and optional
  `sourcename`), so callbacks report
  [`span`](reference/api.md#antlr_pyfacade.FacadeListener.span) /
  [`line_col`](reference/api.md#antlr_pyfacade.FacadeListener.line_col) against the
  whole source rather than the chunk. A `Chunk` also re-anchors the bare strings
  that follow it.

The [chunking helpers](chunking.md) yield positioned `Chunk`s, so they drop straight
in.

## Bounded, lazy, in order

The result is a **lazy iterator**: chunks are pulled and parsed on demand with at
most `max_workers` parses in flight (also the ordering window), so neither the whole
input nor all results need to be held in memory — consume it incrementally, or
`list(...)` it if you want them all. Combined with a streaming chunker
([`stream_on_token`](reference/api.md#antlr_pyfacade.stream_on_token) /
[`stream_on_pattern`](reference/api.md#antlr_pyfacade.stream_on_pattern)), the whole
pipeline — read, chunk, parse — stays bounded in the input size.

`max_workers` defaults to `os.cpu_count()`; pass `1` to run inline without a pool.

## How much speedup?

The per-event Python dispatch still holds the GIL, so the parallel speedup scales
with how parse-heavy the work is relative to per-callback Python work. See the
[Parallel parsing](performance.md#parallel-parsing) section of Performance &
limitations for the scaling details and measured numbers.
