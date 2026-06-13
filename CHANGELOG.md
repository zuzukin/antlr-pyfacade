# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). While the project is in
`0.x`, the patch version is bumped on every change to runtime behavior or
user-facing docs (see [CONTRIBUTING.md](CONTRIBUTING.md)). These early entries are
development notes and may be pruned before the first release.

## [0.1.3] - 2026-06-13

### Fixed
- Heap-buffer-overflow in the vendored runtime's parser DFA-edge cache. The
  lock-free-edges patch had dropped ANTLR's `t + 1` edge-index offset, so caching
  an edge on EOF lookahead (e.g. a single-token input) wrote out of bounds and
  intermittently crashed the process (SIGSEGV / SIGBUS / abort). Restored the
  offset and sized the table `maxTokenType + 2`; verified clean under
  AddressSanitizer.

## [0.1.2] - 2026-06-13

### Added
- `antlr-pyfacade --version` prints the version.

## [0.1.1] - 2026-06-13

### Changed
- The version is declared once, in `src/antlr_pyfacade/VERSION`. pyproject reads
  it at build time (scikit-build-core regex provider) and
  `antlr_pyfacade.__version__` reads it via `importlib.resources`.

### Removed
- `_native.__version__` — the compiled extension no longer carries a version
  string; the package version is sourced from the VERSION file.

## [0.1.0] - 2026-05-31

### Added
- Initial C++-accelerated ANTLR runtime for Python: a bulk, filtered event stream
  over the vendored ANTLR4 C++ runtime; a generated `<Grammar>EventListener`
  facade with `walk` / `walk_parallel`, `load_specs`, source-position helpers, and
  collected parse errors.
- GIL released during the native parse, and per-DFA write locks in the vendored
  runtime so concurrent parses scale.
- `_native` type stub and `py.typed`; pixi `build` / `stubgen` tasks.
