# Glossary

Short definitions of the parsing, runtime, and packaging terms that appear
throughout these docs.

## ATN {#atn}

**Augmented Transition Network** — the state machine ANTLR compiles a grammar into,
with one sub-network per rule, that drives the parser's and lexer's decisions. ANTLR
emits it as a compact **serialized ATN** (an integer array) inside the generated
parser and lexer modules. `antlrope` deserializes that array and runs it directly
with the official C++ runtime — which is why there is no per-grammar C++ codegen.
See [How it works](concepts.md).

## ATN interpreter {#atn-interpreter}

ANTLR's `ParserInterpreter` / `LexerInterpreter` — the runtime components that
*execute* the [ATN](#atn) directly to parse input, instead of running code generated
for one specific grammar. `antlrope` drives the C++ runtime's interpreters from the
serialized ATN, so it works for any grammar with no code-generation step of its own.

## DFA {#dfa}

**Deterministic Finite Automaton** — the lookahead automaton ANTLR builds and caches
as it parses, to make each parsing decision fast. Its states are shared mutable data
hanging off the [ATN](#atn); the vendored C++ runtime makes the DFA-edge reads
lock-free so parses can run concurrently. See
[Parallel parsing](parallel-parsing.md).

## embedded action {#embedded-action}

Target-language code written inline in a grammar between `{` and `}` — e.g.
`{ count += 1; }` — that ANTLR copies into the generated parser to run during a
parse. Because `antlrope` interprets the [ATN](#atn) rather than running
grammar-specific generated code, it **cannot** execute embedded actions; grammars
that depend on them won't parse correctly. See
[Performance & limitations](performance.md).

## facade {#facade}

The `<Grammar>EventListener` class `antlrope` generates from your parser. You
subclass it and override only the callbacks you care about; it bakes in the
lexer/parser and provides `walk` / `walk_parallel` and the chunkers. It mirrors the
stock ANTLR listener interface so consumer code looks familiar. See
[Getting started](getting-started.md).

## FFI {#ffi}

**Foreign Function Interface** — the boundary across which Python calls into native
(C/C++) code and back. Every crossing has overhead, so a per-node parse-tree walk
pays an FFI cost *per tree node*. `antlrope` instead crosses once per parse, handing
Python a single bulk event buffer. See [How it works](concepts.md).

## GIL {#gil}

**Global Interpreter Lock** — CPython's lock that lets only one thread run Python
bytecode at a time. `antlrope`'s native parse releases the GIL, so the parses
themselves overlap across threads; the per-event Python dispatch still holds it, so
[`walk_parallel`](parallel-parsing.md)'s speedup scales with how parse-heavy the
work is. On a **free-threaded** (no-GIL) CPython build the dispatch parallelizes too.

## manylinux {#manylinux}

A packaging standard for Linux Python wheels that are portable across many
distributions. `antlrope`'s Linux wheels target a manylinux baseline, so
`pip install` fetches a working pre-compiled binary on most systems without a local
compiler. See [Installation](installation.md).

## parse tree {#parse-tree}

The tree of rule and token nodes a traditional parser builds to represent the
structure of the input; ANTLR's listeners and visitors walk it node by node.
`antlrope` does **not** materialize a parse tree — it delivers the same information
as a flat, ordered stream of events — so reach for the official runtime when you
need a retained, randomly-accessible tree. See [How it works](concepts.md).

## semantic predicate {#semantic-predicate}

A grammar condition written in target-language code, `{ ... }?` — e.g.
`{ version >= 3 }?` — that ANTLR evaluates during a parse to choose between
alternatives. Like [embedded actions](#embedded-action), `antlrope` cannot evaluate
them, so predicate-dependent grammars won't parse correctly. See
[Performance & limitations](performance.md).

## token channel {#token-channel}

A numbered stream the lexer can route tokens to (with `-> channel(...)`), used to
keep tokens like whitespace and comments out of the parser's way while still
preserving them. The default channel carries ordinary tokens; the token-based
[chunkers](chunking.md) let you choose which channel to split on.
