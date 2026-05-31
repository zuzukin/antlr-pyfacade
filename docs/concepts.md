# How it works

## The problem with a per-node listener

The classic ANTLR consumption model builds a parse tree and walks it, calling
`enterEveryRule` / `exitEveryRule` / `visitTerminal` once per node. With a
Python listener over a C++ parse, **every one of those calls is a
foreign-function crossing**. For a document that produces tens of millions of
tree nodes, the per-node crossing — not the parse itself — dominates the
runtime. Moving the parse to C++ barely helps if Python is still poked once per
node.

## The bulk filtered event stream

`antlr-pyfacade` removes the per-node crossing. After the C++ runtime finishes
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

The generated facade wires this up automatically. `drive` (the engine behind the
facade's `walk`) inspects **which callbacks your subclass actually overrides** —
comparing each `enter<Rule>` / `exit<Rule>` / `visitTerminal` against the
generated base class's no-op stub — and builds the masks from exactly those.
Subscribe to three rules and one token type, and the C++ side emits only those
events. Override nothing extra and you pay for nothing extra.

You can force a faithful, unfiltered stream with `walk(..., filtered=False)`,
which is useful for diagnostics and for the correctness tests.

## What runs where

- **C++**: ATN deserialization, `LexerInterpreter` + `ParserInterpreter`, the
  full parse to a tree, and the masked DFS that builds the event buffer.
- **Python**: one loop over the buffer (`struct.iter_unpack("<4i", raw)`),
  dispatching your overridden callbacks and slicing token text as needed.

There is no generated C++ parser and no compilation of your grammar. The C++
runtime is driven entirely from the **serialized ATN** that the stock
`-Dlanguage=Python3` ANTLR tool already emits, plus the rule/token name metadata
read off the generated Python classes (see [`load_specs`](api.md#load_specs)).
