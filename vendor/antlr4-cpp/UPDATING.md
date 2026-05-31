# Vendored ANTLR4 C++ runtime

`src/` is a verbatim copy of the official ANTLR4 C++ runtime source tree
(`runtime/Cpp/runtime/src` from the antlr/antlr4 repository). It is vendored —
rather than pulled as a git submodule — because submodules do not survive sdist
packaging, and the goal is a self-contained source distribution that builds with
no external checkout.

## Provenance

- **Upstream repo:** https://github.com/antlr/antlr4 (`dev` branch lineage)
- **Snapshot commit:** `8d3a921f2` (fork `analog-cbarber/antlr4`, branch
  `cpp-lockfree-dfa-edges`)
- **Patch applied on top:** the lock-free DFA-edge change (PR1,
  `cpp-lockfree-dfa-edges`). `DFAState::edges` is a lazily-allocated array of
  `std::atomic<DFAState*>` with lock-free `getEdge`, replacing the
  `FlatHashMap` guarded by `ATN::_edgeMutex`. This is the per-character read-path
  speedup; once it lands upstream the snapshot can be refreshed without carrying
  the patch.
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
3. Rebuild and run `pytest` to confirm parity.
