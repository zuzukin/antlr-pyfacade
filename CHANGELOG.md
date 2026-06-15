# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). While the project is in
`0.x`, the patch version is bumped on every change to runtime behavior or
user-facing docs (see [CONTRIBUTING.md](CONTRIBUTING.md)). These early entries are
development notes and may be pruned before the first release.

## [0.1.8] - 2026-06-15

### Added
- Regex-based chunkers in `antlr_pyfacade.chunking`, for when a lexer pass isn't
  needed: `split_on_pattern(text, pattern, where="before"|"after")` (the regex
  analogue of `split_on_token`) and `chunk_by_pattern(text, pattern)` (each match
  is a record). They take the text directly — no lexer — and yield positioned
  `Chunk`s like the token splitters. Faster than the lexer-based splitters for
  simple delimiters but not token-aware; see `docs/performance.md` for measured
  numbers and the trade-off (`scripts/bench_chunking.py`).

## [0.1.7] - 2026-06-15

### Added
- Token-based chunking in `antlr_pyfacade.chunking`, so `walk_parallel` input can
  be produced without a hand-written regex splitter and with exact source
  positions carried automatically. A single lexer pass (in C++, no parsing) drives
  the splitters:
  - `lex(text, LexerCls, keep=...)` returns the token stream as `LexToken(type,
    channel, start, stop)` records; `keep` filters to specific token types in C++
    so only those cross into Python.
  - `split_on_token(text, LexerCls, token_types, where="before"|"after")` splits at
    a delimiter token (one type or several).
  - `split_between_tokens(text, LexerCls, pairs, nested=False)` yields each
    opener/closer region; `pairs` is one `(open, close)` pair or a list of them,
    each side one or several token types, so distinct bracket kinds match
    correctly.
  All yield positioned `Chunk`s. Also adds `load_lexer_spec` and the `lex` native
  entry.

## [0.1.6] - 2026-06-14

### Added
- `walk_parallel` now accepts `str` **or** `Chunk` items, where `Chunk` bundles a
  chunk's text with its source `offset` / `line` / `column`, so callbacks' `span`
  / `line_col` report positions against the whole source rather than each chunk. A
  bare `str` is positioned contiguously after the previous chunk; a `Chunk` pins
  an explicit position and re-anchors the bare strings that follow it. New `Chunk`
  type is exported.

### Changed
- `walk_parallel` now returns a **lazy iterator** instead of a list. Chunks are
  pulled and parsed on demand with at most `max_workers` parses in flight (results
  still yielded in input order), so neither the whole input nor all results need
  to be held in memory — enabling incremental processing. Call `list(...)` on the
  result for the previous eager behavior.
- `FacadeListener.span` / `line_col` report positions offset by the parsed text's
  source origin. Unchanged for a plain `walk` (origin `(0, 1, 0)`).

### Changed
- `FacadeListener.span` / `line_col` report positions offset by the parsed
  text's source origin. Unchanged for a plain `walk` (origin is offset 0,
  line 1, column 0).

## [0.1.5] - 2026-06-14

### Added
- `SourceMap.offset(line, column=0)` — the inverse of `line_col`, mapping a
  1-based line / 0-based column back to a character offset. Validates the line
  number; the column is added without bounds-checking against the line length.

## [0.1.4] - 2026-06-13

### Changed
- The generated facade class is now named `<Grammar.capitalize()>EventListener`
  (e.g. `JsonEventListener`) instead of `<Grammar>EventListener`. Regenerate your
  facade and update references. The JSON example and its tests are updated.

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
