# Benchmark: SystemRDL

A real-world check of `antlr-pyfacade` against the two alternatives a Python ANTLR
user actually has, on a real grammar:

- the official **[antlr4-python3-runtime](https://pypi.org/project/antlr4-python3-runtime/)** (the pure-Python runtime), and
- **[speedy-antlr-tool](https://github.com/amykyta3/speedy-antlr-tool)**, which runs the parser via ANTLR's C++ target and *translates the parse tree back into Python* (a drop-in accelerator that keeps the normal tree/visitor API).

The grammar is **[SystemRDL](https://github.com/SystemRDL/systemrdl-compiler)** — a
hardware register-description language whose grammar is a 461-line, action- and
predicate-free combined grammar (exactly the target-agnostic case all three tools
support).

## TL;DR

Parsing a 2.6 MB input (≈86k lines, ~77k parse-tree nodes):

| | parse time | peak memory | vs pure-Python | vs speedy-antlr |
| --- | ---: | ---: | ---: | ---: |
| pure-Python runtime | 3716 ms | 432 MB | 1.0× | — |
| speedy-antlr | 1427 ms | 1381 MB | 2.6× | 1.0× |
| **antlr-pyfacade** | **179 ms** | **310 MB** | **20.8×** | **8.0×** |

`antlr-pyfacade` is the fastest **and** uses the least peak memory of the three.

## What's measured

Each tool **parses the input and produces the structure you would then consume** —
the cost you pay before any application logic runs:

- **pure-Python**: lex + parse to a Python parse tree.
- **speedy-antlr**: lex + parse in C++, then translate the tree into Python nodes
  (`sa_systemrdl.parse`, the accelerator bundled in `systemrdl-compiler`).
- **antlr-pyfacade**: parse in C++ and emit the full, unfiltered bulk event buffer
  (`parse_events`) — no Python tree.

Wall-clock is the best of 7 warm runs over an in-memory string; **peak memory** is
the process's peak resident set (`ru_maxrss`), each tool measured in a fresh
process. Inputs are a real Accellera register block (`atxmega_spi`) replicated with
unique names to three sizes.

Environment: Apple Silicon, macOS 26, CPython 3.14.5; antlr4-python3-runtime 4.13.2;
ANTLR tool 4.13.2; systemrdl-compiler 1.32.2 (speedy-antlr accelerator);
antlr-pyfacade 0.1.21.

## Results

| input | tool | parse time | peak memory |
| --- | --- | ---: | ---: |
| small (85 L, 3 KB) | pure-Python | 3.4 ms | 20 MB |
| | speedy-antlr | 0.9 ms | 32 MB |
| | **antlr-pyfacade** | **0.8 ms** | 28 MB |
| medium (8.6k L, 0.26 MB) | pure-Python | 281 ms | 97 MB |
| | speedy-antlr | 85 ms | 192 MB |
| | **antlr-pyfacade** | **18 ms** | **70 MB** |
| large (86k L, 2.6 MB) | pure-Python | 3716 ms | 432 MB |
| | speedy-antlr | 1427 ms | 1381 MB |
| | **antlr-pyfacade** | **179 ms** | **310 MB** |

At the smallest size everything is dominated by interpreter/extension load (~20–30 MB
base, sub-millisecond parse); the differences appear once the input is non-trivial.

## Why antlr-pyfacade wins on both axes

`antlr-pyfacade` **never materializes a Python parse tree**. It parses in C++, walks
the C++ tree once into a compact flat `int32` buffer, and hands Python a single
transfer — so it pays neither the per-node Python object construction nor the memory
of a Python tree.

The contrast with **speedy-antlr** is the instructive part. Speedy-antlr also parses
in C++ (hence faster than pure-Python), but it then rebuilds the *entire* tree as
Python objects. During that translation it transiently holds **both** the C++ tree
and the Python tree, which is why its peak memory reaches **1.4 GB to parse a 2.6 MB
file** — 3× the pure-Python peak and 4.5× the antlr-pyfacade peak. Pure-Python is
slow at parsing *and* builds the heavy Python tree.

So the bulk-event-stream design beats both the pure-Python runtime and the
tree-translation accelerator, on speed *and* on memory.

## Correctness

The event stream reproduces the pure-Python parse tree exactly. On the medium input
the pure-Python tree walk reports 50,201 rule contexts, 26,601 terminals, 0 errors;
the `antlr-pyfacade` event buffer contains exactly 50,201 rule-enter, 50,201
rule-exit, 26,601 terminal, and 0 error events.

## What this does and does not show

- **Parse-only.** These numbers cover producing the consumable structure, not the
  application logic that consumes it. A consumer still has to *do* something with the
  result; an end-to-end comparison (building a real model from the parse) is the next
  step. Note that `antlr-pyfacade`'s consumption is also cheaper — a Python loop over
  the buffer, with no per-node foreign-function call — so the end-to-end gap should
  only widen.
- **The trade-off is the programming model.** Speedy-antlr is a *drop-in*: your
  existing listeners/visitors keep working against a real Python tree. `antlr-pyfacade`
  requires expressing the consumer as an [event listener](../migrating.md) (no
  context objects; reconstruct state from event order). That porting cost is real and
  is the thing to weigh against the speed/memory win. Cases that genuinely need a
  retained, randomly-accessible tree (XPath, rewriting) are not a fit — see
  [Performance & limitations](../performance.md).
- **Synthetic sizing.** The input is one real register block replicated; the
  structure is realistic SystemRDL, but exact ratios will vary on real corpora and
  hardware. The ratios, not the absolute milliseconds, are the takeaway.
