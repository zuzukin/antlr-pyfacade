# Vendored ANTLR4 C++ runtime

`src/` is a verbatim copy of the official ANTLR4 C++ runtime source tree
(`runtime/Cpp/runtime/src` from the antlr/antlr4 repository). It is vendored —
rather than pulled as a git submodule — because submodules do not survive sdist
packaging, and the goal is a self-contained source distribution that builds with
no external checkout.

## Provenance

- **Upstream repo:** https://github.com/antlr/antlr4 (`dev` branch lineage)
- **Snapshot commit:** `910af6e43` (fork `zuzukin/antlr4`, branch
  `cpp-per-dfa-locks`, which stacks Patch 2 on Patch 1). Both patch branches are
  pushed to the fork; since 2026-08-23 they are stacked on the `ts-tests-tsx`
  test-harness branch (`ce99aa84d`, upstream PR #4963) purely so their CI runs
  green — runtime content is unchanged — and base off upstream `7d5770395`:
  - `cpp-lockfree-dfa-edges` (`4097eb8b7`) — Patch 1 only.
  - `cpp-per-dfa-locks` (`910af6e43`) — Patch 1 + Patch 2; this is what `src/` mirrors.
- **Upstream PRs (opened 2026-07-18):** Patch 1 is
  https://github.com/antlr/antlr4/pull/4953, Patch 2 is
  https://github.com/antlr/antlr4/pull/4954 (stacked on #4953).
- **Patch 1 (PR1) — lock-free DFA-edge reads.** `DFAState::edges` is a
  lazily-allocated array of `std::atomic<DFAState*>` with lock-free `getEdge`,
  replacing the `FlatHashMap` guarded by a mutex. This is the per-character
  read-path speedup; once it lands upstream the snapshot can be refreshed without
  carrying the patch.
  - **Fix (must also be applied to the upstream PR1 branch):** the parser edge
    index must keep ANTLR's `t + 1` offset so EOF (`t == -1`) maps to slot 0.
    The first cut dropped it, so `ParserATNSimulator::addDFAEdge` called
    `setEdge((size_t)-1, …)`, wrapping to `edges - 8` — an intermittent
    heap-buffer-overflow that only fired when a decision cached an edge on EOF
    lookahead (e.g. a single-token input). `getExistingTargetState` now reads
    `getEdge(t + 1)`, `addDFAEdge` writes `setEdge(t + 1, maxTokenType + 2, …)`
    and guards `t < -1`. Verified clean under AddressSanitizer.
  - **Fix (2026-07-18, also in the upstream PR):** `DFASerializer::getEdgeLabel`
    must print `getDisplayName(i - 1)` to undo the `t + 1` indexing; the map-era
    code printed the raw slot index, shifting every DFA-dump edge label by one
    (caught by the upstream runtime testsuite's diagnostic-output tests).
- **Patch 2 (PR2) — per-DFA write locks.** The DFA state/edge write locks were
  moved off the ATN (`ATN::_stateMutex` / `ATN::_edgeMutex`, now removed) and onto
  the DFA itself (`dfa::DFA::stateMutex()` / `edgeMutex()`, heap-allocated so DFA
  stays movable). `ATN::_mutex` remains for the lazy `nextTokens` cache. The
  lexer/parser simulators (`LexerATNSimulator`, `ParserATNSimulator`) now lock the
  owning DFA's mutex instead of the ATN's.

  Rationale: a `ParserInterpreter`/`LexerInterpreter` keeps its **own**
  `decisionToDFA`, but the write locks lived on the **shared** ATN, so concurrent
  parses that share one spec serialized on a single per-ATN lock even though their
  DFAs were independent — measured *slower than serial* (~0.6x on 4 threads).
  After this patch, independent DFAs use independent locks (shared-spec parsing
  scales ~2x on 4 threads, matching per-thread specs); a DFA shared across threads
  (generated recognizers' static `decisionToDFA`) still serializes its own
  writers, now at per-decision rather than per-ATN granularity. Edge *reads* stay
  lock-free (Patch 1). Touched files: `dfa/DFA.h`, `atn/ATN.h`,
  `atn/ParserATNSimulator.cpp`, `atn/LexerATNSimulator.cpp`, plus contract
  comments in `dfa/DFAState.{h,cpp}` and `dfa/DFA.cpp`. Recommended before
  upstreaming: a ThreadSanitizer build over the concurrency stress test
  (`tests/test_threading.py::test_shared_spec_concurrency_stress`).
- `LICENSE.txt` is the ANTLR project BSD-3-Clause license, carried alongside the
  sources.

## Refreshing the snapshot

1. Re-copy the runtime source tree from the upstream checkout:
   ```
   rm -rf src
   cp -R /path/to/antlr4/runtime/Cpp/runtime/src src
   cp /path/to/antlr4/LICENSE.txt LICENSE.txt
   ```
2. If PR1 has **not** yet merged upstream, re-apply the lock-free DFA-edge patch
   (or copy from the `cpp-lockfree-dfa-edges` branch instead of `dev`). Once PR1
   is released upstream, drop this step and update the commit reference above.
3. Re-apply Patch 2 (per-DFA write locks) unless it, too, has landed upstream:
   move `_stateMutex`/`_edgeMutex` from `atn/ATN.h` onto `dfa::DFA` and repoint the
   simulator lock sites (see "Patch 2" above for the exact files).
4. Rebuild and run `pytest` to confirm parity.
