# How it works

## The problem with a per-node listener

The classic ANTLR consumption model builds a [parse tree] and walks it, calling
`enterEveryRule` / `exitEveryRule` / `visitTerminal` once per node. With a
Python listener over a C++ parse, **every one of those calls is a
[foreign-function crossing][FFI]**. For a document that produces tens of millions of
tree nodes, the per-node crossing — not the parse itself — dominates the
runtime. Moving the parse to C++ barely helps if Python is still poked once per
node.

## The bulk filtered event stream

`antlrope` removes the per-node crossing. After the C++ runtime finishes
parsing, a native iterative depth-first traversal (mirroring ANTLR's
`IterativeParseTreeWalker`: pre-order rule-enter and terminals, post-order
rule-exit) appends one fixed record per visited item into a single contiguous
buffer, which is handed to Python in **one** transfer.

Each record is four `int32` values:

| field | meaning |
|---|---|
| `kind` | `0 = ENTER_RULE`, `1 = EXIT_RULE`, `2 = TERMINAL`, `3 = ERROR` |
| `payload` | rule index (enter/exit) or token type (terminal/error) |
| `start` | source char index of the item's first codepoint (`-1` if none) |
| `stop` | source char index of the item's last codepoint (`-1` if none) |

For a terminal/error the span is the token; for a rule it is the rule's full
extent (first token start … last token stop). Items with no span — an empty
rule, or an inserted/missing error token — report `-1`.

Token **text is never copied across the boundary**. The runtime returns only the
integer `(start, stop)` span; Python recovers the text on demand by slicing the
original source string, `text[start : stop + 1]`. Most consumers only need the
text of a few token kinds, so most slices never happen.

## Native filtering via masks

The second lever is **filtering in C++**. A consumer usually cares about a
subset of rules and tokens. `parse_events` accepts a `rule_mask` and a
`token_mask` (lists of indices to keep); events that fail the mask are dropped
*before* they are appended to the buffer. This cuts the number of records Python
must iterate, not merely the per-call cost.

The generated [facade] wires this up automatically. `drive` (the engine behind the
facade's `walk`) inspects **which callbacks your subclass actually overrides** —
comparing each `enter<Rule>` / `exit<Rule>` / `visitTerminal` against the
generated base class's no-op stub — and builds the masks from exactly those.
Subscribe to three rules and one token type, and the C++ side emits only those
events. Override nothing extra and you pay for nothing extra.

You can force a faithful, unfiltered stream with `walk(..., filtered=False)`,
which is useful for diagnostics and for the correctness tests.

## What runs where

- **C++**: [ATN] deserialization, `LexerInterpreter` + `ParserInterpreter`, the
  full parse to a tree, and the masked DFS that builds the event buffer.
- **Python**: one loop over the buffer (`struct.iter_unpack("<4i", raw)`),
  dispatching your overridden callbacks and slicing token text as needed.

There is no generated C++ parser and no compilation of your grammar. The C++
runtime is driven entirely from the **serialized ATN** that the stock
`-Dlanguage=Python3` ANTLR tool already emits, plus the rule/token name metadata
read off the generated Python classes (see
[`parser_spec`](reference/api.md#antlrope.FacadeListener.parser_spec) /
[`lexer_spec`](reference/api.md#antlrope.FacadeListener.lexer_spec)).

## The vendored runtime and its patches

`antlrope` builds against a **vendored copy of the official ANTLR4 C++ runtime**
(BSD-3-Clause, carried verbatim under `vendor/antlr4-cpp/src`) rather than the
system runtime, so the wheel is self-contained. On top of that pristine copy it
carries two performance patches, both written to be contributed back upstream as
pull requests (tracked on the `zuzukin/antlr4` fork; see
`vendor/antlr4-cpp/UPDATING.md` for the exact branches and commit):

- **Lock-free DFA-edge reads.** The ATN simulator's hot path — looking up the next
  DFA edge per input character — is changed from a mutex-guarded hash map to a
  lazily-allocated array of `std::atomic<DFAState*>`, so the per-character read
  path takes no lock. This is a straight single-thread parse speedup.
- **Per-DFA write locks.** The DFA state/edge *write* locks are moved off the
  shared ATN and onto each DFA. The stock runtime guards DFA mutation with a lock
  that lives on the ATN, which every interpreter sharing a spec also shares — so
  concurrent parses of one grammar serialize on a single lock even though their
  DFAs are independent. Moving the lock onto the DFA lets independent parses
  proceed in parallel; this is what makes [parallel parsing](parallel-parsing.md)
  with a shared spec actually scale across threads instead of running *slower*
  than serial.

Neither patch changes parse results — they are purely concurrency/throughput
improvements — and both are kept as small, isolated diffs so the snapshot can drop
them once (if) they land upstream.

### How much do the patches contribute?

Rebuilding `antlrope` against the **pristine** upstream runtime and against each
patch in turn isolates their effect (parsing a 4.7 MB JSON document on an Apple
M5 Max; `scripts/bench_runtime_patches.py`):

| runtime | single-thread parse | shared-spec parse, 4 threads |
| --- | ---: | ---: |
| pristine upstream | 551 ms | **0.5×** (parallel *slower* than serial) |
| + lock-free DFA reads | 486 ms | 0.6× |
| + per-DFA write locks | ~480 ms | **~2.0×** |

Two distinct takeaways:

- **The single-thread win is mostly architecture, not the runtime.** The lock-free
  read path shaves ~12% off the parse; the rest of `antlrope`'s ~20× margin over
  the pure-Python runtime (see [the SystemRDL benchmark](benchmarks/systemrdl.md))
  comes from the bulk event stream, not the patched C++. Even on the stock runtime
  `antlrope` would be ~18× faster than pure-Python here. (JSON is lexer-heavy, which
  flatters this patch — its win is in the lexer's per-character DFA hot path; a
  parser-heavy grammar shows less.)
- **The parallel win is entirely the runtime.** On the stock runtime, parsing a
  *shared* spec across threads is **2× slower than serial** — the per-ATN write lock
  serializes every thread. The per-DFA write locks turn that into a ~2× speedup
  (≈4× better wall-clock than the stock runtime threaded). Without this patch,
  [parallel parsing](parallel-parsing.md) over a shared spec is pointless.

[parse tree]: glossary.md#parse-tree
[FFI]: glossary.md#ffi
[facade]: glossary.md#facade
[ATN]: glossary.md#atn
