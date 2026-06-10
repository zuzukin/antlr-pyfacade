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

## How fast, in relative terms

The comparison that matters for a Python user is the official
`antlr4-python3-runtime`, since that is the other way to consume the same
generated parser. Consider a workload that touches most nodes — close to the
worst case for this design, because Python still iterates every kept event:

- The **bulk event-stream facade** runs roughly **10–20× faster** than the
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

### Underlying C++ runtime

This package bundles the ANTLR4 C++ runtime with a lock-free DFA-edge patch on
the per-character lexer read path (the vendored snapshot; see
`vendor/antlr4-cpp/UPDATING.md`). Versus the stock C++ runtime, that patch alone
measured roughly **1.7–1.8× lexer** and **1.3–1.4× total-parse** throughput,
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
- **Threading.** The native parse **releases the GIL**, so other Python threads
  keep running during a parse and `asyncio.to_thread(listener.walk, ...)` won't
  block the event loop. For parallel *throughput*, give **each thread its own
  specs** — call [`load_specs(..., cached=False)`](api.md#load_specs) per worker
  thread rather than sharing one result. A spec owns the deserialized ATN, whose
  parser-prediction state is shared mutable data; concurrent parses that share
  one spec are correct but contend on it and do **not** scale (the bundled
  lock-free patch covers only the lexer's DFA edge reads, not the parser
  prediction path). With independent specs, parses run in parallel across cores —
  measured ~2× on 4 threads for a parse-bound workload, memory-bandwidth limited
  beyond that.
