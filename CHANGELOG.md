# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). While the project is in
`0.x`, the patch version is bumped on every change to runtime behavior or
user-facing docs (see [CONTRIBUTING.md](CONTRIBUTING.md)). These early entries are
development notes and may be pruned before the first release.

## [0.2.26] - 2026-06-27

### Changed
- Documentation now styles the product name as **Antlrope** (capitalized, bold on
  first mention per page), reserving the lowercase `antlrope` for the Python module,
  the CLI command, and the package id. The convention is recorded in CONTRIBUTING.

## [0.2.25] - 2026-06-24

### Changed
- **Breaking:** the low-level native layer is now internal. `parse_events`,
  `ParserSpec`, and `LexerSpec` are no longer exported from `antlrope`, and
  `FacadeListener.drive` / `.parser_spec` / `.lexer_spec` are now `_drive` /
  `_parser_spec` / `_lexer_spec`. Use `walk` / `walk_parallel` (and the chunkers);
  the raw event buffer is no longer a public API.
- **Breaking:** the generated facade's `LEXER` / `PARSER` class variables are now
  `_LEXER` / `_PARSER`, and the `LexerProtocol` / `ParserProtocol` typing protocols are
  no longer exported from `antlrope`. The baked-in lexer/parser are an implementation
  detail of the generated subclass.

## [0.2.24] - 2026-06-24

### Added
- `antlrope gen` now writes a **provenance header** into the generated facade: the
  antlrope version, the exact command, the run directory (relative to the output
  file), and a SHA256 of each input module — all deterministic, so output stays
  byte-reproducible. Two new subcommands consume it: **`antlrope regen <file>`**
  re-runs the recorded command from the recorded directory to regenerate in place, and
  **`antlrope up-to-date <file>`** re-hashes the inputs (and checks the version) and
  exits non-zero when the file is stale.

## [0.2.23] - 2026-06-24

### Added
- Export `LineCol` (the 1-based-line / 0-based-column source position returned by
  `SourceMap.line_col()` and surfaced by `FacadeListener.line_col()`) as a top-level
  public name, and document it in the API reference. It was already public from
  `antlrope.location` but missing from the package's public surface.

## [0.2.22] - 2026-06-24

### Changed
- **Breaking (CLI):** the facade generator is now the `antlrope gen` subcommand rather
  than bare `antlrope <parser-module> <name>`. `antlrope` is now a command group (with
  room for future subcommands); bare `antlrope` prints help and `antlrope --version` is
  unchanged. Update invocations to `antlrope gen …` (`antlrope generate` is an accepted
  alias). The CLI moved into the new `antlrope.cli` package (entry point
  `antlrope.cli.main`, one module per subcommand); the old `antlrope.generate` module is
  removed.

## [0.2.21] - 2026-06-23

### Changed
- The facade generator now emits the `ruleNames` list in ruff/black format — kept on
  one line when it fits, otherwise exploded one-per-line with a trailing comma — so
  the generated `<Grammar>EventListener` is format-clean as written, with no
  `ruff format` pass needed after generating. Previously a grammar with many rules
  produced a single very long line.

## [0.2.20] - 2026-06-22

### Changed
- Docs: the command-line reference now shows the current angle-bracket metavar names
  (`<parser-module>`, `<name>`, `<lexer-module>`, `<file>`), matching `antlrope --help`.

## [0.2.19] - 2026-06-22

### Added
- A **"streaming records" recipe** page — an end-to-end "file of records" pipeline: a
  streaming chunker into `walk_parallel`, handling the preamble, preserving a
  whitespace terminator with `trim=False`, absolute positions, and recovering
  off-channel metadata via `lex`. Linked from the chunking, parallel-parsing, and
  performance pages.

### Changed
- Docs: the chunking page documents `trim=` and the leading/trailing preamble region;
  "How it works" explains that the walk is channel-blind (off-channel tokens are not in
  the event stream) and how to recover them via `lex`; the performance page notes the
  cost of a full per-record listener and its two levers (subscribe to fewer
  rules/tokens, or aggregate in a rule).

## [0.2.18] - 2026-06-22

### Changed
- `stream_by_rule` now **fails loudly instead of silently truncating**. When an
  on-channel token begins no candidate record rule (e.g. an unsupported header or
  record separator), or a chosen record consumes no tokens, it raises a `RuntimeError`
  naming the offending token (type, text, `line:column`) and the candidate rules,
  rather than quietly ending the stream — which previously surfaced a malformed input
  as an empty or truncated result. Records parsed before the offending token are still
  yielded first, so the error arrives after them. The streaming char source's `size()`
  message is likewise rewritten to explain the cause (the parser fell back to
  whole-input error recovery) and to point at `chunk_by_rule` / the `split_*` chunkers.

## [0.2.17] - 2026-06-22

### Added
- `trim=` (default `True`) on the delimiter chunkers — `split_on_token`,
  `stream_on_token`, `split_on_pattern`, `stream_on_pattern`, `split_between_tokens`,
  and `chunk_by_pattern`. With `trim=False` each region is kept verbatim and only
  truly-empty (zero-length) regions are dropped, instead of stripping surrounding
  whitespace and skipping whitespace-only regions. This lets a record's mandatory
  whitespace terminator (e.g. a trailing newline) survive the split. The native
  streamer (`StreamChunker`) honors `trim=` identically to its in-memory `split_*`
  oracle. `chunk_by_rule` is unaffected — its spans are already token-exact.

## [0.2.16] - 2026-06-22

### Added
- A "Type checking" section in the installation docs, plus a
  `scripts/typecheck_smoke.py` guard (checked by `pixi run typecheck`) that the
  public API resolves as `from antlrope import …`. antlrope's shipped types are
  correct — `py.typed` ships in the wheel and the re-exports are public via `__all__`
  (verified: Pyright reports 0 errors against an installed wheel). A "could not be
  resolved" error means the checker is pointed at the wrong interpreter, not at the
  environment where antlrope is installed.

## [0.2.15] - 2026-06-21

### Changed
- The schema indexing example (`examples/schema/index.py` and its docs page) now
  uses the new scope helpers: `current_rule()` (with a no-op `enterEveryRule` to
  subscribe to all rules) distinguishes a definition name from a field name from a
  field type, replacing the hand-tracked `_in_body` flag and `_last_id` lookahead.

## [0.2.14] - 2026-06-21

### Added
- Consumer-ergonomics helpers on `FacadeListener`, so listeners no longer hand-roll
  scope/state scaffolding:
  - **Scope/depth:** `depth()`, `rule_stack()`, `current_rule()` — auto-maintained
    nesting state (tracks the rules you subscribe to; override the new
    `enterEveryRule`/`exitEveryRule` no-op hooks to track the full parse tree).
  - **Current text:** `text()` — the source slice of the current event (token text,
    or a rule's whole extent), so rule text needs no manual `span()` slicing.
  - **Name lookups:** `token_name(token_type)` and `rule_name(index)`.

  All additive and backward-compatible; no native/C++ changes.

## [0.2.13] - 2026-06-21

### Added
- `ParserProtocol` and `LexerProtocol` — structural types describing the stock
  ANTLR `<Grammar>Parser` / `<Grammar>Lexer` class surface antlrope reads
  (`literalNames`, `symbolicNames`, `ruleNames`, plus the lexer's `channelNames` /
  `modeNames`, and `grammarFileName`). `FacadeListener.LEXER` / `PARSER` are now
  typed `ClassVar[type[LexerProtocol]]` / `ClassVar[type[ParserProtocol]]` instead
  of a bare `type`, and the spec builders take them too. A generated class satisfies
  these structurally — no nominal inheritance needed (and a Protocol cannot itself
  subclass `Lexer` / `Parser`).

### Changed
- The internal `TextSource` / `TokenTypes` / `Pair` / `RuleTypes` type aliases use
  PEP 695 `type` syntax and live at module scope (no `TYPE_CHECKING` guard) — they
  are lazily evaluated, so they cost nothing at import while existing at runtime.
- Ruff's `target-version` is now `py312` (was `py310`), matching `requires-python`
  and the pyright floor.

## [0.2.12] - 2026-06-21

### Changed
- Reference-doc signatures now render as their own formatted code block, wrapped
  one-argument-per-line for long signatures (mkdocstrings `separate_signature` +
  `line_length = 80`, formatted by Ruff).
- The documentation toolchain now comes from conda-forge — `zensical`,
  `mkdocstrings-python`, `mkdocstrings-python-xref`, and `ruff` are conda
  dependencies. (Only `mike`, a git-only fork, remains a PyPI dependency.) Zensical's
  conda-forge package is a CEP-20 abi3 build with a `py310` build string that denotes
  its 3.10 floor, not a 3.10-only lock — it installs fine on 3.12–3.14.
- `clean` now also removes Zensical's `.zensical/` incremental cache (a stale cache
  there can otherwise mask docs config changes).

## [0.2.11] - 2026-06-21

### Changed
- The vendored-runtime patch branches now live on the **`zuzukin/antlr4`** fork
  (moved from `analog-cbarber/antlr4`), consolidating them under the same org as
  the project. Updated the references in **How it works** and
  `vendor/antlr4-cpp/UPDATING.md`.

## [0.2.10] - 2026-06-21

### Changed
- **Breaking: the minimum Python is now 3.12** (was 3.10). Dropping 3.10/3.11
  (3.10 reaches end-of-life in October 2026) lets antlrope ship a single CPython
  **Stable ABI (`abi3`)** wheel per platform instead of one per interpreter:
  `[tool.scikit-build] wheel.py-api = "cp312"` plus nanobind's `STABLE_ABI` now
  build one `cp312-abi3` wheel that runs on 3.12, 3.13, 3.14 and future CPythons
  with no rebuild. `CMakeLists.txt` now also requests Python's SABI component
  (`${SKBUILD_SABI_COMPONENT}`) so the limited-API build actually engages — without
  it nanobind silently falls back to a full-ABI build and the wheel is mis-tagged.
  Local `pixi run build` is unaffected (it still builds a normal version-specific
  extension).
- `FacadeListener.walk` / `walk_parallel` now use `typing.Self` for their return
  types, replacing the `_F = TypeVar(...)` workaround that was needed while 3.10 was
  supported.

### Added
- Binary wheels for **Linux aarch64** (native GitHub `ubuntu-24.04-arm` runner),
  alongside the existing Linux x86_64, macOS arm64/x86_64, and Windows x86_64.

### Fixed
- conda recipe: corrected the stale `analog-cbarber` homepage/repository URLs to
  `zuzukin`, and documented (for conda-forge reviewers) why the recipe vendors and
  static-links the ANTLR4 C++ runtime instead of depending on `antlr-cpp-runtime`.

## [0.2.9] - 2026-06-21

### Added
- A "The vendored runtime and its patches" section in **How it works** documenting
  the two performance patches `antlrope` carries on top of the vendored ANTLR4 C++
  runtime (lock-free DFA-edge reads; per-DFA write locks for shared-spec parallel
  scaling), both written for upstream PRs, **with a measured breakdown of each
  patch's contribution** (lock-free reads ≈12% of single-thread parse; per-DFA locks
  turn shared-spec parallel parsing from 0.5× to ~2× scaling). Both patch branches
  are now pushed to the `analog-cbarber/antlr4` fork; `vendor/antlr4-cpp/UPDATING.md`
  points the snapshot reference at them.
- `scripts/bench_runtime_patches.py`, a harness that rebuilds against pristine /
  patched runtimes to reproduce that breakdown.

## [0.2.8] - 2026-06-21

### Added
- A "Reproduce it" link from the SystemRDL benchmark page to the
  [`zuzukin/srdl-bench`](https://github.com/zuzukin/srdl-bench) harness.

## [0.2.7] - 2026-06-20

### Added
- conda-forge install instructions alongside PyPI (`conda install -c conda-forge
  antlrope`) in the README and the installation docs.
- A **Glossary** page defining the non-obvious terms used throughout the docs (ATN,
  DFA, GIL, FFI, semantic predicate, embedded action, parse tree, facade, …), with
  reference-style links to it from the pages where those terms appear.

## [0.2.6] - 2026-06-20

### Changed
- `FacadeListener.sourcename()` now returns `str` (an empty string when no source
  name was set) rather than `str | None`, matching `Chunk.sourcename` and the
  chunkers' `sourcename=""` default. A never-walked listener returns `""` instead of
  `None`.

## [0.2.5] - 2026-06-20

### Added
- An **Examples** section in the docs, with two worked programs: the JSON value
  reconstruction (`examples/json/to_python.py`) and a new **schema-indexing**
  example (`examples/schema/`) — a small message/enum IDL parsed three ways
  (whole-file walk, `chunk_by_rule` + `walk_parallel`, and bounded-memory
  `stream_by_rule`), with guidance on when each pays off. Both examples are now
  smoke-tested in CI (`pixi run example` / `example-schema`).

## [0.2.4] - 2026-06-20

### Changed
- **Spec building moved onto `FacadeListener`.** The top-level `load_specs` /
  `load_lexer_spec` are replaced by the classmethods
  `FacadeListener.parser_spec(*, cached=True)` and
  `FacadeListener.lexer_spec(*, cached=True)`, which build the native specs from the
  baked-in `PARSER` / `LEXER` — call `MyListener.parser_spec()` /
  `MyListener.lexer_spec()` (e.g. to feed `drive(...)` directly). Parser and lexer
  specs now cache independently. **Breaking**; the `antlrope.specs` module and the two
  top-level functions are removed.

## [0.2.3] - 2026-06-20

### Changed
- **Chunkers are now classmethods on `FacadeListener`.** `lex`, `split_on_token`,
  `split_between_tokens`, `split_on_pattern`, `stream_on_pattern`,
  `chunk_by_pattern`, `chunk_by_rule`, `stream_on_token`, and `stream_by_rule` moved
  off the top-level `antlrope` namespace onto the generated `<Grammar>EventListener`,
  sourcing the lexer/parser from the baked-in `LEXER` / `PARSER` — call them as
  `MyListener.split_on_token(text, …)` / `MyListener.chunk_by_rule(text, "rule")` and
  drop the `lexer_cls` / `parser_cls` arguments. **Breaking**; the `antlrope.chunking`
  module is removed. `Chunk`, `LexToken`, `load_specs`, and `load_lexer_spec` remain
  top-level exports.

## [0.2.2] - 2026-06-20

### Changed
- **Generated facades bake in the lexer and parser**, so `walk` and `walk_parallel`
  no longer take `lexer_cls` / `parser_cls`: write `listener.walk(text)` and
  `Cls.walk_parallel(chunks, …)`. The generated `<Grammar>EventListener` imports the
  stock classes and exposes them as `LEXER` / `PARSER` class attributes. **Breaking**
  for code generated by an older release — regenerate the facade and drop the class
  arguments from the call sites. The standalone chunkers (`chunk_by_rule`,
  `stream_by_rule`, `lex`, `split_on_token`, …) are unchanged and still take an
  explicit lexer/parser.
- `walk` now lives on `FacadeListener` (a template method over the baked-in
  `LEXER` / `PARSER`) instead of being emitted into each generated file, so the
  generated facade is smaller and `walk` / `walk_parallel` return the concrete
  subclass type (`Collector().walk(text)` is a `Collector`).

### Added
- `antlrope generate` derives the lexer module from the parser's by ANTLR's
  `<Grammar>Lexer` / `<Grammar>Parser` convention; the new `--lexer` flag overrides
  it when the lexer is named differently. The lexer is imported at generation time,
  so a wrong path fails immediately with a clear error.

## [0.2.1] - 2026-06-19

### Added
- **Logo and favicon** (`docs/assets/`) — an antelope-head mark whose ridged horns
  double as the ordered event stream, in warm tan/brown. The README shows a
  light/dark logo lockup (`logo.svg` / `logo-dark.svg`) via `<picture>`, with the
  `ope` (Ordered Parse Events) of the wordmark accented; the docs site uses the mark
  as its favicon and header logo. Earlier green and side-profile explorations are
  kept under `docs/assets/alternates/`.

## [0.2.0] - 2026-06-19

### Changed
- **Renamed the project from `antlr-pyfacade` to `antlrope`** — a single word (no
  dash) and a pun on *antelope* that extends ANTLR's antler imagery, where **OPE =
  Ordered Parse Events** (the parse tree is delivered as one DFS-ordered stream of
  events). The import package, the distribution name, and the console script all
  become `antlrope` (`import antlrope`, `pip install antlrope`, `antlrope …`).
  **Regenerate facades** produced by an older release: their generated header and
  `from antlr_pyfacade import …` line become `antlrope`. Entries below predate the
  rename and refer to the old name.

## [0.1.23] - 2026-06-19

### Added
- A summary **benchmark chart** (`docs/benchmarks/systemrdl.svg`, generated by
  `make_chart.py`) in the README and atop the benchmark page, visualizing the
  SystemRDL speed/memory results.

### Fixed
- README documentation links: the dead `docs/api.md` now points to
  `docs/reference/api.md`, plus links to the published site, installation, chunking,
  and the benchmark. Documentation only.

## [0.1.22] - 2026-06-19

### Added
- A **SystemRDL benchmark** page (`docs/benchmarks/systemrdl.md`, linked from
  Performance) measuring `antlr-pyfacade` against the pure-Python runtime and the
  `speedy-antlr` tree-translation accelerator on a real action-free grammar. Both
  parse-only and an end-to-end consumer task (collecting identifiers): ~21–23× faster
  than pure-Python and ~8–9× faster than speedy-antlr on a 2.6 MB input, at lower peak
  memory, with the event stream / consumer output verified identical to a pure-Python
  tree walk. Documentation only.

## [0.1.21] - 2026-06-19

### Added
- `stream_by_rule(path, LexerCls, ParserCls, rule, *, sourcename=..., encoding=...)`
  — the streaming counterpart of `chunk_by_rule`, completing the streaming chunker
  family. For input that is a top-level **sequence of records** (each an occurrence of
  a grammar `rule`, or one of several), it parses one record at a time over a
  bounded-memory pipeline (native `Utf8FileCharStream` → `LexerInterpreter` →
  `UnbufferedTokenStream` → `ParserInterpreter`), yielding positioned `Chunk`s without
  holding the whole token stream or parse tree. With several candidate rules the next
  token chooses which to parse (by each rule's start-token set), so they should have
  disjoint leading tokens (e.g. `class` vs `def`). Records must be directly adjacent
  (only lexer-skipped whitespace/comments between them); unlike `chunk_by_rule` it
  doesn't find a rule anywhere in a full parse — for nesting/comma-separated records,
  use `chunk_by_rule` or `stream_on_token`.

## [0.1.20] - 2026-06-19

### Added
- An `llms.txt` published at the documentation-site root (`/llms.txt`, per
  [llmstxt.org](https://llmstxt.org/)) — a concise, LLM-oriented overview of the
  library (install, workflow, the listener model, the public API, and doc links) to
  help coding agents use it. Served as a raw file; it does not appear in the
  rendered docs, nav, search, or sitemap.

## [0.1.19] - 2026-06-19

### Added
- Docstrings on the native `ParseError`, `LexerSpec`, and `ParserSpec` classes (and
  on `ParseError`'s fields), carried into the `_native.pyi` stub by `stubgen` and
  rendered in the API Reference — previously these showed only signatures. No
  behavior change.

## [0.1.18] - 2026-06-19

### Changed
- Reorganized the documentation site into four header tabs — **User Guide /
  Installation / Reference / About** — modeled on whl2conda. The **Reference** is now
  generated from the package docstrings via mkdocstrings (a single API page plus a
  command-line page); the old hand-written `api.md` is replaced by pared-down
  Chunking and Parallel-parsing guide pages that defer signatures to the Reference.
  Adds an Installation tab and an About tab (release notes, license, motivation,
  acknowledgements). Documentation only — no code or API changes.

## [0.1.17] - 2026-06-19

### Fixed
- The generated facade's token-type constants for **anonymous string literals**
  now use ANTLR's positional `T__n` naming (matching the stock lexer/parser:
  `T__0` is the first literal, token type 1), instead of a name synthesized from
  the token-type value (`T__1` for type 1). The symbolic-named constants were
  always correct; only the anonymous literals were off, so e.g. `MyLexer.T__0`
  now has a matching `MyEventListener.T__0`. **Regenerate facades** produced by an
  older `antlr-pyfacade` if you reference their `T__n` constants. The bundled JSON
  example facade and its consumer are regenerated/updated.

## [0.1.16] - 2026-06-19

### Changed
- The chunk source-name added in 0.1.15 is now spelled **`sourcename`** (was
  `name`) throughout — `Chunk.sourcename`, the `sourcename=` keyword, and
  `FacadeListener.sourcename()` / `drive(..., sourcename=...)` — and is now an
  option on **every** chunker (`split_on_token`, `split_between_tokens`,
  `split_on_pattern`, `chunk_by_pattern`, `chunk_by_rule`, and the streaming pair),
  not just the streaming ones. The in-memory chunkers leave it `None` unless given;
  the streaming ones still default it to their file path.

## [0.1.15] - 2026-06-19

### Added
- Chunks can carry a **source name** for diagnostics. `Chunk` gains an optional
  `name` field (a bare `str` chunk inherits the name of the chunk it follows), and
  `stream_on_token` / `stream_on_pattern` take a `name=` keyword — defaulting to the
  file path, and the way to name a path-less stream or iterable passed to
  `stream_on_pattern`. The name surfaces during a walk as the new
  `FacadeListener.source_name()` (and `drive(..., source_name=...)`), so a callback
  can report a position as `name:line:column`.

## [0.1.14] - 2026-06-19

### Added
- `stream_on_pattern(source, pattern, *, where=..., flags=..., window_chars=...,
  window_lines=..., encoding="utf-8")` — the streaming counterpart of
  `split_on_pattern`. Reads `source` (a filesystem path opened with `encoding`, an
  open text file, or any iterable of `str`) incrementally and yields positioned
  `Chunk`s without holding the whole input, so paired with `walk_parallel` the
  pipeline stays bounded. The regex runs Python-side, so any text encoding works
  (unlike the UTF-8-only, C++-side `stream_on_token`). A delimiter is committed
  only once a character past it has been read, so it is never split across a read
  boundary as long as it fits within the `window_chars`/`window_lines` window; a
  region with no delimiter is buffered in full.

## [0.1.13] - 2026-06-19

### Added
- `stream_on_token(path, LexerCls, token_types, *, where=..., encoding="utf-8",
  channel=...)` — the streaming counterpart of `split_on_token`. The native layer
  opens the file itself and lexes it incrementally over a sliding window
  (`Utf8FileCharStream`), slicing out and freeing each chunk as it goes, so peak
  memory is ~one chunk rather than the whole file. Yields positioned `Chunk`s
  lazily, so paired with `walk_parallel` the whole pipeline is bounded in the file
  size. Reads UTF-8 (the `encoding` keyword accepts Python codec aliases for UTF-8
  and is reserved for future encodings); for other encodings, decode in Python and
  use `split_on_token`. Only delimiter-based splitting streams so far —
  `split_between_tokens` and `chunk_by_rule` still take the whole text.

## [0.1.12] - 2026-06-15

### Changed
- `lex` now yields its tokens lazily (an iterator) instead of returning a list;
  wrap in `list(...)` for random access. Internally the native lexer streams
  tokens (a `nextToken()` loop) instead of buffering the whole token stream, so
  peak memory no longer scales with the total token count — only the kept tokens
  cross into Python. The chunkers' behavior and output are unchanged.

## [0.1.11] - 2026-06-15

### Added
- `Chunk.after(text)` returns the next contiguous chunk for `text`, positioned
  where this chunk's text ends (replaces the internal `_advance` helper).

### Changed
- `drive` is now a method of `FacadeListener`
  (`listener.drive(parser_spec, lexer_spec, text, start_rule, *, filtered=...,
  origin=...)`) rather than a standalone function, and it derives the generated
  base class itself (one fewer argument). It is no longer exported as
  `antlr_pyfacade.drive`. The generated facade's `walk` now calls `self.drive(...)`
  and no longer imports `drive` — **regenerate facades** produced by an older
  `antlr-pyfacade`.

## [0.1.10] - 2026-06-15

### Changed
- Renamed two internal modules for clarity: `facade_runtime` → `base` and
  `gen_facade` → `generate`. Code imports from the top-level `antlr_pyfacade`
  package and the `antlr-pyfacade` console script is unchanged, so this only
  affects anything that imported those submodules directly.
- Trimmed the public top-level namespace to the high-level API. The low-level
  binding diagnostics (`parse_count`, `parse_walk`, `parse_stage_times`,
  `atn_shape`) and the parse-tree node classes (`AtnShape`, `ParseTree`,
  `RuleContext`, `ParserRuleContext`, `TerminalNode`, `ErrorNode`, `Token`,
  `ParseTreeListener`) are no longer re-exported from `antlr_pyfacade` — reach
  them via `antlr_pyfacade._native` if needed. The facade (`FacadeListener`,
  `drive`), `load_specs` / `load_lexer_spec`, the chunkers, `SourceMap`, `Chunk`,
  `ParseError`, `LexerSpec` / `ParserSpec`, and the raw `parse_events` remain.

## [0.1.9] - 2026-06-15

### Added
- Rule-based chunking: `chunk_by_rule(text, LexerCls, ParserCls, rule, *,
  start_rule=None, outermost=True)` parses the input (entirely in C++) and yields
  each occurrence of a grammar `rule` (one or several rule names/indices) as a
  positioned `Chunk`. `outermost=True` keeps only top-level occurrences. For
  records defined by grammar structure rather than a token/regex delimiter — pays
  for a structural parse, but only the spans cross into Python. Backed by a new
  native `rule_spans` entry.

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
