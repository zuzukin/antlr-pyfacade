# Motivation

ANTLR is an excellent parser generator, and its Python target is convenient — you
write a `.g4` grammar, generate Python, and consume the parse with a listener or
visitor. But the generated parser *runs* in pure Python, and for large inputs that
is slow: the official `antlr4-python3-runtime` is typically an order of magnitude
slower than the C++ runtime, and a Python `ParseTreeListener` over the parse pays a
[foreign-function crossing][FFI] **per tree node** — which, for documents with millions of
nodes, dominates everything else.

The usual escape hatch is to switch your whole toolchain to the C++ (or Java)
target: generate a C++ parser, compile it, and write your application logic in C++.
That's a large step, and it throws away the convenience of staying in Python.

**Antlrope** takes a different path. It drives the **official ANTLR4 C++
runtime's [ATN interpreter]** directly from the *[serialized ATN][ATN]* that the stock
`-Dlanguage=Python3` ANTLR tool already emits — so there is **no per-grammar C++
codegen and nothing for you to compile**. The parse runs in C++, and instead of one
Python call per node, a single bulk, filtered event stream crosses into Python in
one batch. You keep writing plain-Python listeners; you just get C++ parsing speed
under them (typically **10–20×** the pure-Python runtime, and more when you
subscribe to only part of the grammar).

The goal is to make the fast path the *easy* path: if you can write an ANTLR
grammar and a Python class, you shouldn't have to learn C++ or change your build to
parse quickly.

## The name

*antl**rope*** is a pun on *antelope* that extends ANTLR's antler imagery — and
**OPE** stands for **O**rdered **P**arse **E**vents: the distinctive thing this
runtime does is hand Python the parse as one DFS-ordered stream of events
(rule-enter, rule-exit, terminal, error) rather than a per-node parse-tree walk.

## When the official runtime is the right choice

Antlrope does not replace `antlr4-python3-runtime` — it targets the
throughput case. Prefer the official runtime when your grammar relies on **[semantic
predicates][semantic predicate] or [embedded actions][embedded action]**, when you need the **retained [parse tree]** (random
access, rewriting, re-walking) rather than a single streaming pass, or when the
input is small enough that per-node cost doesn't matter. See
[Migrating](../migrating.md) and
[Performance & limitations](../performance.md) for the full boundary.

[FFI]: ../glossary.md#ffi
[ATN interpreter]: ../glossary.md#atn-interpreter
[ATN]: ../glossary.md#atn
[semantic predicate]: ../glossary.md#semantic-predicate
[embedded action]: ../glossary.md#embedded-action
[parse tree]: ../glossary.md#parse-tree
