# Performance & limitations

## Where the speed comes from — and its ceiling

Two costs dominate consuming a large parse from Python:

1. **Per-node FFI crossings.** A Python `ParseTreeListener` over a C++ parse is
   called once per tree node. The bulk event stream removes this entirely: one
   transfer instead of millions of calls.
2. **Python's per-item iteration.** Even with zero call overhead, Python must
   still loop over every event it receives. This cost is **irreducible** for a
   workload that touches most nodes — you can only shrink it by *receiving fewer
   events*, which is what native filtering does.

So the honest framing: batching removes the call overhead; filtering reduces the
iteration count. Neither makes a "reserialize everything" workload free, because
something in Python still iterates the kept events.

## Measured throughput (testbed)

From the development testbed — converting JSON to YAML, which is close to a
**worst case** because it touches essentially every node — on an 84 MiB input,
Apple M5 Max, single-threaded:

| backend | MiB/s |
|---|---:|
| official pure-Python runtime | 0.52 |
| mypyc-compiled model | 4.09 |
| native parse, per-node Python listener | 4.45 |
| native parse, **bulk event-stream facade** | ~6–9 |
| native parse, C++ counting walk (no Python) | 9.03 |
| Java (generated parser) | 41.7 |

Reading this: the per-node Python listener (4.45) barely beats mypyc despite the
C++ parse, because it pays the per-node crossing. The bulk facade closes most of
the remaining gap to the C++-only walk (9.03), which is the practical ceiling for
*any* approach that still hands every node to Python. Real consumers usually
filter to a subset and land closer to — or above — that line, because they never
iterate the dropped events at all.

json2yaml is deliberately near the worst case. A consumer that, say, extracts a
handful of token kinds from a large file will see a much larger win, since
filtering removes the bulk of the iteration before Python ever sees it.

### Underlying C++ runtime

This package bundles the ANTLR4 C++ runtime with a lock-free DFA-edge patch on
the per-character lexer read path (the vendored snapshot; see
`vendor/antlr4-cpp/UPDATING.md`). On the testbed inputs that patch alone gave
roughly **1.7–1.8× lexer** and **1.3–1.4× total-parse** throughput versus stock,
single-threaded, and more under concurrency.

## Limitation: semantic predicates and embedded actions

This is the most important correctness boundary, so it is called out loudly.

The runtime executes the **interpreted ATN** (`ParserInterpreter` /
`LexerInterpreter`). It does **not** compile or run target-language code embedded
in your grammar:

- **Semantic predicates** — `{...}?` gating an alternative.
- **Embedded actions** — `{...}` code blocks.

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

## Other notes

- **Single streaming pass.** You get one ordered traversal, not a retained tree.
  If you need random access, re-walking, XPath, or rewriting, keep the parse
  tree from the official runtime.
- **Threading.** The bundled lock-free read path makes concurrent parses on
  separate threads safe and contention-free at the DFA edge table; each parse
  still uses its own interpreter/stream instances.
