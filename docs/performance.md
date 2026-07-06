# Performance & limitations

## Where the speed comes from — and its ceiling

Two costs dominate consuming a large parse from Python:

1. **Per-node [FFI] crossings.** A Python `ParseTreeListener` over a C++ parse is
   called once per tree node. The bulk event stream removes this entirely: one
   transfer instead of millions of calls.
2. **Python's per-item iteration.** Even with zero call overhead, Python must
   still loop over every event it receives. This cost is **irreducible** for a
   workload that touches most nodes — you can only shrink it by *receiving fewer
   events*, which is what native filtering does.

Batching removes the call overhead, and filtering reduces the
iteration count. Neither makes a "reserialize everything" workload free, because
something in Python still iterates the kept events.

## How fast, in relative terms

The comparison that matters for a Python user is the official
`antlr4-python3-runtime`, since that is the other way to consume the same
generated parser. Consider a workload that touches most nodes — close to the
worst case for this design, because Python still iterates every kept event:

- The **bulk event-stream [facade]** runs roughly **10–20× faster** than the
  official pure-Python runtime — and that is the *worst* case for this design.
  Workloads that subscribe to only a subset of rules/tokens go higher still,
  because native filtering drops the rest before Python ever iterates them.
- A **per-node Python listener over the native parse** — the slower escape hatch
  this package also exposes — lands well short of the facade, because it pays one
  FFI crossing per tree node. That per-node crossing is exactly the cost the bulk
  stream removes.
- The practical ceiling for *any* approach that still hands every node to Python
  is a **pure-C++ walk that never enters Python**. The facade closes most of the
  gap to it; you can only go further by *receiving fewer events*.

For a measured comparison on a real grammar — parsing SystemRDL, against both the
pure-Python runtime and the `speedy-antlr` tree-translation accelerator — see the
[SystemRDL benchmark](benchmarks/systemrdl.md) (~21× faster than pure-Python and
~8× faster than speedy-antlr, at lower peak memory).

### Underlying C++ runtime

This package bundles the ANTLR4 C++ runtime with a lock-free [DFA]-edge patch on
the per-character lexer read path (the vendored snapshot; see
`vendor/antlr4-cpp/UPDATING.md`). Versus the stock C++ runtime, that patch alone
measured roughly **1.7–1.8× lexer** and **1.3–1.4× total-parse** throughput,
single-threaded, and more under concurrency.

## Limitation: semantic predicates and embedded actions

This is the most important correctness boundary, so it is called out loudly.

The runtime executes the **interpreted [ATN]** ([`ParserInterpreter`][ATN interpreter] /
`LexerInterpreter`). It does **not** compile or run target-language code embedded
in your grammar:

- **[Semantic predicates][semantic predicate]** — `{...}?` gating an alternative.
- **[Embedded actions][embedded action]** — `{...}` code blocks.

A generated, compiled ANTLR parser runs these as native code. The ATN
interpreter cannot, so any grammar whose parse **depends** on a predicate to
disambiguate, or on an action to set state that later parsing reads, will not
parse correctly here. There is no error for this — the interpreter simply makes
the prediction the ATN encodes without the predicate, which may differ from what
your grammar intends.

If your grammar relies on predicates or actions for correct parsing, use the
official `antlr4-python3-runtime` (its generated parser executes them), or
restructure the grammar to be predicate-free.

Grammars that are purely structural — most data and config formats, many DSLs —
are unaffected.

To find out where your grammar stands, run
[`antlrope check <parser-module>`](reference/cli.md#antlrope-check) on the
generated parser: it scans the serialized ATNs and reports every semantic
predicate and embedded action by rule (exit status 0 when there are none).
Precedence predicates from left-recursive rules and the built-in lexer commands
(`-> skip`, `-> channel(...)`, ...) are fine and are not flagged.

## Other notes

- **Single streaming pass.** You get one ordered traversal, not a retained tree.
  If you need random access, re-walking, XPath, or rewriting, keep the parse
  tree from the official runtime.
- **[GIL].** The native parse **releases the GIL**, so other Python threads keep
  running during a parse and `asyncio.to_thread(listener.walk, ...)` won't block
  the event loop.
- **A full per-record listener costs about its parse again.** Walking a record with
  every rule/token subscribed pays one Python loop iteration per kept event, so a
  fully-subscribed listener roughly doubles the per-record cost over the native parse
  alone (the "Python's per-item iteration" cost above). Claw it back by subscribing to
  fewer rules/tokens — the facade emits only those from C++ — or by aggregating inside
  a rule so fewer events cross into Python at all. The
  [streaming-records recipe](streaming-records.md#cost-of-a-full-per-record-listener)
  ties this to a record pipeline.

## Parallel parsing

When your input is a sequence of **independent pieces** — the records of a log,
the top-level definitions of a source file, the sections of a document — you can
parse them concurrently across CPU cores. Split the text into chunks — the
[chunking helpers](chunking.md) split on token boundaries from a single cheap
lexer pass, or bring your own regex — and hand them to
[walk_parallel](parallel-parsing.md):

```python
chunks = RecordListener.split_on_token(text, RecordListener.RECORD, where="before")
records = [
    ln.to_model()                               # one result per chunk, in order
    for ln in RecordListener.walk_parallel(
        chunks, start_rule="record"
    )
]
```

`walk_parallel` yields lazily with a bounded number of parses in flight, so you
can consume results incrementally instead of holding the whole input in memory.

Each chunk parses on a worker thread with the GIL released, so the parses overlap.
Worker threads use independent specs internally, so they never contend on a shared
ATN.

**How much speedup?** It depends on how much of your per-chunk work is the native
parse versus Python in your callbacks — the parse parallelizes, but the per-event
Python dispatch still holds the GIL (Amdahl's law). Measured on an 18-core M5 Max,
hundreds of small chunks:

- **Parse-bound** work (light callbacks — counting, validation): **~3×** and
  climbing with cores.
- **Callback-heavy** work (rebuilding a rich object per node): **~2×**, plateauing
  early because the Python dispatch serializes.

To push callback-heavy workloads further you currently need a **free-threaded
(no-GIL) CPython** build, where the dispatch parallelizes too — `walk_parallel`
benefits automatically with no code change. Process-based parallelism is the other
option, at the cost of pickling results back.

Two implementation notes, both bundled here:

- **Per-DFA locks.** A spec owns a mutable ATN. Concurrent parses sharing one spec
  *used* to serialize on a single per-ATN lock guarding DFA construction — slower
  than serial. The vendored runtime moves those write locks onto each DFA (see
  `vendor/antlr4-cpp/UPDATING.md`, Patch 2), so a shared spec now scales like
  independent ones; edge reads were already lock-free.
- **Cold DFA per parse.** Each parse builds its own prediction DFA from scratch, so
  very small chunks spend proportionally more time warming up. Larger chunks
  amortize this away — real-world chunks are usually big enough that it's
  negligible.

### Chunking: lexer vs regex

The [chunking helpers](chunking.md) come in three flavors that cost very
differently: regex-based (`split_on_pattern` / `chunk_by_pattern`, a text scan),
token-based (`split_on_token` / `split_between_tokens`, a lexer pass), and
rule-based (`chunk_by_rule`, a full parse). Producing the *same* chunks — each
object of a JSON array of 200k flat objects (~11 MB) — on an 18-core M5 Max:

| method (~11 MB / 200k objects) | scan/parse stage | full chunking |
| ------------------------------ | ---------------: | ------------: |
| regex (`chunk_by_pattern`)         |  ~220 MB/s | ~99 MB/s |
| lexer (`split_between_tokens`)     |   ~30 MB/s | ~23 MB/s |
| rule  (`chunk_by_rule`)            |   ~14 MB/s | ~13 MB/s |

The regex just scans; the lexer tokenizes the *entire* input (then drops all but
the boundary tokens in C++); the rule chunker runs a full structural parse. So the
underlying stage gets ~7× slower from regex to lexer and ~2× again to a parse —
the last ratio grows with grammar complexity (JSON's prediction is cheap; an
ambiguous grammar parses much slower than it lexes). End to end the gaps narrow a
little, since all three pay the same per-chunk Python cost (the `SourceMap` plus,
per chunk, slicing + trimming + position lookup). Reproduce with
`scripts/bench_chunking.py`.

Pick by constraint, not just speed:

- **Regex** is much faster, but **not token-aware** — a delimiter inside a string
  literal or comment will still match and mis-split. Use it when the delimiter
  cannot appear in disguise (or you've confirmed it can't).
- **Token-based** never splits inside a string/comment token, and handles
  whitespace/[channels][token channel] the way the grammar does.
- **Rule-based** cuts on real grammar structure (no delimiter heuristic at all),
  at the cost of a parse — but only the spans cross into Python. Reach for it when
  the per-chunk `walk_parallel` callback work dominates this first parse, or when
  records simply aren't marked by a token/regex boundary.

Either way the splitting cost is usually negligible next to the per-chunk parse it
feeds.

For a file too large to hold in memory, `stream_on_token`
([chunking](chunking.md)) is the delimiter splitter's streaming form: it opens the
file in C++ and lexes it over a sliding window, materializing one chunk at a time
instead of the whole text plus a whole-input `SourceMap`. Paired with
`walk_parallel` (which already pulls chunks lazily with a bounded number of parses
in flight), peak memory is roughly one chunk plus the parses in flight — flat in
the file size. It still tokenizes the entire input, so throughput tracks the
token-based row above; what changes is the memory profile, not the speed.
`stream_on_pattern` is the same idea for the regex splitter — it reads the source
incrementally (Python-side, so any text encoding), committing a delimiter once a
character past it is read; throughput tracks the regex row, memory stays flat.

[FFI]: glossary.md#ffi
[facade]: glossary.md#facade
[DFA]: glossary.md#dfa
[ATN]: glossary.md#atn
[ATN interpreter]: glossary.md#atn-interpreter
[semantic predicate]: glossary.md#semantic-predicate
[embedded action]: glossary.md#embedded-action
[GIL]: glossary.md#gil
[token channel]: glossary.md#token-channel
