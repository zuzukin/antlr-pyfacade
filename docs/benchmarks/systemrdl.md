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

`antlr-pyfacade` is the fastest **and** uses the least peak memory of the three. The
gap holds [end to end](#end-to-end-parse-and-consume) once you also *consume* the
result — and the consumer's output is identical to a pure-Python tree walk.

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

## End-to-end: parse *and* consume

Parsing is only half the job — you have to consume the result. A representative
consumer task: **collect every identifier (`ID` token) in the file**, implemented
identically across all four (pure-Python and speedy-antlr walk the tree with a
`ParseTreeListener`; `antlr-pyfacade` uses an event listener). All four produce the
**identical** list of identifiers (verified by hash; 32,000 ids on the large input).

| input | tool | end-to-end time | peak memory |
| --- | --- | ---: | ---: |
| medium (0.26 MB) | pure-Python | 306 ms | 99 MB |
| | speedy-antlr | 102 ms | 189 MB |
| | antlr-pyfacade (all terminals) | 20 ms | 63 MB |
| | **antlr-pyfacade (native `ID` filter)** | **17 ms** | **56 MB** |
| large (2.6 MB) | pure-Python | 3963 ms | 418 MB |
| | speedy-antlr | 1618 ms | 1398 MB |
| | antlr-pyfacade (all terminals) | 197 ms | 242 MB |
| | **antlr-pyfacade (native `ID` filter)** | **174 ms** | **218 MB** |

End-to-end, `antlr-pyfacade` is **~21–23× faster than the pure-Python runtime and
~8–9× faster than speedy-antlr**, at the lowest peak memory.

Two effects compound here. First, the tree-walking tools must traverse *every* node
to reach the terminals; the facade only receives the events its listener subscribes
to. Subscribing to **only the `ID` token** (`TERMINAL_TOKENS = [ID]`) makes the C++
side emit just those terminals — no rule events, no other tokens cross into Python —
shaving a further ~10% of time and memory over receiving all terminals. The
tree-walk approaches have no equivalent; they pay for the whole tree regardless.

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

- **The trade-off is the programming model.** Speedy-antlr is a *drop-in*: your
  existing listeners/visitors keep working against a real Python parse tree.
  `antlr-pyfacade` requires expressing the consumer as an
  [event listener](../migrating.md) — no context objects; you reconstruct state from
  event order. For the identifier task above that was actually *fewer* lines (no node
  objects, no walker setup), but a task that leans on parse-tree context (parent/child
  navigation, the text of a whole subtree, random access) needs restructuring to the
  event-plus-explicit-stack model — that restructuring is the real porting cost to
  weigh against the speed/memory win. A workload that genuinely needs a retained,
  randomly-accessible tree (XPath, rewriting) is not a fit — see
  [Performance & limitations](../performance.md).
- **One consumer task.** The end-to-end numbers are for a single representative task;
  a different task changes the *consume* cost, but the parse cost — which dominates —
  is fixed.
- **Synthetic sizing.** The input is one real register block replicated; the
  structure is realistic SystemRDL, but exact ratios will vary on real corpora and
  hardware. Read the ratios, not the absolute milliseconds.
