# Copyright 2026 Christopher Barber
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Driver for generated grammar-specific event listeners.

A generated `<Grammar>EventListener` subclass declares named callbacks
(`enter<Rule>` / `exit<Rule>` / `visitTerminal` / `visitError`) just like the
stock ANTLR listener. [drive][antlrope.FacadeListener.drive] runs the bulk native event
stream and dispatches those callbacks, instead of building a Python parse tree and
walking it.

It derives the native rule/token masks from *which* callbacks the subclass
actually overrides, so only the node kinds the consumer cares about cross into
Python (the unsubscribed rest are dropped C++-side before the buffer is built).

The class is also the grammar's chunking API: classmethods like
[split_on_token][antlrope.FacadeListener.split_on_token] and
[chunk_by_rule][antlrope.FacadeListener.chunk_by_rule] split a whole source into
positioned [Chunk][antlrope.Chunk]s for
[walk_parallel][antlrope.FacadeListener.walk_parallel], sourcing the lexer/parser
from the baked-in `LEXER` / `PARSER`.
"""

from __future__ import annotations

import codecs
import os
import re
import struct
import sys
import threading
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from typing import ClassVar, NamedTuple, Protocol, Self, cast

from . import _native
from .location import LineCol, SourceMap

# Type aliases (PEP 695). `type X = ...` is lazily evaluated, so these cost nothing
# at import despite living at module scope — no `TYPE_CHECKING` guard needed.
# A streaming text source: a filesystem path, an open text file object, or any
# iterable of str pieces (a file object iterates as lines; a generator works).
type TextSource = str | os.PathLike[str] | Iterable[str]
# One token type, or several treated as equivalent.
type TokenTypes = int | Iterable[int]
# An (open, close) bracket pair; either side may be one or several types.
type Pair = tuple[TokenTypes, TokenTypes]
# A grammar rule name or index, or several of them.
type RuleTypes = str | int | Iterable[str | int]

__all__ = [
    "Chunk",
    "FacadeListener",
    "LexToken",
]

EV_ENTER, EV_EXIT, EV_TERMINAL, EV_ERROR = 0, 1, 2, 3
_REC = "<4i"
# Record layout emitted by _native.lex: (type, channel, start, stop).
_TOK = struct.Struct("<4i")
# Record layout emitted by _native.rule_spans: (rule_index, start, stop).
_RULE = struct.Struct("<3i")

#: The default token channel — what the lexer routes ordinary tokens to.
DEFAULT_CHANNEL = 0

# Structural types for the stock ANTLR `<Grammar>Parser` / `<Grammar>Lexer`
# classes — just the grammar metadata antlrope reads off them. A generated class
# satisfies these without nominal inheritance: a `Protocol` matches by structure,
# so the ANTLR runtime `Parser` / `Lexer` subclass the tool emits qualifies as-is.
# (A `Protocol` *cannot* itself subclass `Parser` / `Lexer` — protocols may only
# derive from other protocols — but it doesn't need to.) antlrope never
# instantiates these classes; it only reads this metadata and drives the parse from
# the serialized ATN in C++. Note `serializedATN()` is a *module*-level function
# (resolved via the class's `__module__`), not a class member, so it isn't here.
class ParserProtocol(Protocol):
    """The stock ANTLR `<Grammar>Parser` class surface that antlrope consumes."""

    literalNames: ClassVar[Sequence[str]]
    symbolicNames: ClassVar[Sequence[str]]
    ruleNames: ClassVar[Sequence[str]]
    grammarFileName: ClassVar[str]


class LexerProtocol(Protocol):
    """The stock ANTLR `<Grammar>Lexer` class surface that antlrope consumes."""

    literalNames: ClassVar[Sequence[str]]
    symbolicNames: ClassVar[Sequence[str]]
    ruleNames: ClassVar[Sequence[str]]
    channelNames: ClassVar[Sequence[str]]
    modeNames: ClassVar[Sequence[str]]
    grammarFileName: ClassVar[str]


# Cache specs by class so repeated walks of a grammar pay the ATN deserialization
# cost once. Parser and lexer specs cache independently — the lexer-only chunkers
# need no parser spec. The Python3 ANTLR target emits a module-level
# `serializedATN()` alongside each class, resolved here via the class's module.
_PARSER_SPEC_CACHE: dict[type[ParserProtocol], _native.ParserSpec] = {}
_LEXER_SPEC_CACHE: dict[type[LexerProtocol], _native.LexerSpec] = {}


def _build_parser_spec(parser_cls: type[ParserProtocol]) -> _native.ParserSpec:
    mod = sys.modules[parser_cls.__module__]
    grammar_file = getattr(parser_cls, "grammarFileName", "<grammar>.g4")
    return _native.ParserSpec(
        grammar_file,
        list(parser_cls.literalNames),
        list(parser_cls.symbolicNames),
        list(parser_cls.ruleNames),
        mod.serializedATN(),
    )


def _build_lexer_spec(lexer_cls: type[LexerProtocol]) -> _native.LexerSpec:
    mod = sys.modules[lexer_cls.__module__]
    grammar_file = getattr(lexer_cls, "grammarFileName", "<grammar>.g4")
    return _native.LexerSpec(
        grammar_file,
        list(lexer_cls.literalNames),
        list(lexer_cls.symbolicNames),
        list(lexer_cls.ruleNames),
        list(lexer_cls.channelNames),
        list(lexer_cls.modeNames),
        mod.serializedATN(),
    )


# Per-thread spec cache for parallel parsing. Each worker thread builds its own
# (parser_spec, lexer_spec) once per grammar (uncached). With the vendored runtime's
# per-DFA locks a shared spec scales too, but a per-thread spec is the simple, robust
# default — no shared mutable state at all (see docs/performance.md "Parallel parsing").
_thread_specs = threading.local()


def _specs_for_thread(
    cls: type[FacadeListener],
) -> tuple[_native.ParserSpec, _native.LexerSpec]:
    cache = getattr(_thread_specs, "cache", None)
    if cache is None:
        cache = _thread_specs.cache = {}
    key = (cls.LEXER, cls.PARSER)
    specs = cache.get(key)
    if specs is None:
        specs = cache[key] = (
            _build_parser_spec(cls.PARSER),
            _build_lexer_spec(cls.LEXER),
        )
    return specs


def _as_set(types: TokenTypes) -> frozenset[int]:
    """Normalize one token type or an iterable of them to a frozenset."""
    return frozenset((types,)) if isinstance(types, int) else frozenset(types)


def _normalize_pairs(
    pairs: Pair | list[Pair],
) -> list[tuple[frozenset[int], frozenset[int]]]:
    """Normalize the `pairs` argument to a list of (open-set, close-set)."""
    plist = [pairs] if isinstance(pairs, tuple) else list(pairs)
    out: list[tuple[frozenset[int], frozenset[int]]] = []
    for p in plist:
        if not (isinstance(p, tuple) and len(p) == 2):
            raise ValueError(f"each pair must be an (open, close) tuple, got {p!r}")
        out.append((_as_set(p[0]), _as_set(p[1])))
    if not out:
        raise ValueError("pairs must contain at least one (open, close) pair")
    return out


def _read_increments(
    fobj: object, window_chars: int | None, window_lines: int | None
) -> Iterator[str]:
    """Yield successive text increments from a text file-like `fobj`.

    With `window_lines` set, reads that many lines per step (capped at
    `window_chars` characters if also set); otherwise reads `window_chars`-sized
    blocks. The increment size only affects how often the regex re-runs and how
    much read-ahead is buffered — never the output.
    """
    if window_lines is not None and window_lines > 0:
        cap = window_chars if window_chars and window_chars > 0 else None
        while True:
            lines: list[str] = []
            total = 0
            for _ in range(window_lines):
                line = fobj.readline()  # type: ignore[attr-defined]
                if not line:
                    break
                lines.append(line)
                total += len(line)
                if cap is not None and total >= cap:
                    break
            if not lines:
                return
            yield "".join(lines)
    else:
        size = window_chars if window_chars and window_chars > 0 else 65536
        while True:
            piece = fobj.read(size)  # type: ignore[attr-defined]
            if not piece:
                return
            yield piece


class LexToken(NamedTuple):
    """One token from [lex][antlrope.FacadeListener.lex].

    `line` / `column` are not carried (they are cheap to derive from `start` with
    a [SourceMap][antlrope.SourceMap]); keeping the record to four ints keeps
    a full-stream `lex()` light.
    """

    type: int
    channel: int
    start: int  # 0-based codepoint offset of the first character
    stop: int  # 0-based codepoint offset of the last character (inclusive)


class Chunk(NamedTuple):
    """A contiguous chunk of source text plus location information.

    These are produced by the [FacadeListener][antlrope.FacadeListener] chunking
    classmethods, such as
    [chunk_by_pattern][antlrope.FacadeListener.chunk_by_pattern], for consumption
    by [FacadeListener.walk_parallel][antlrope.FacadeListener.walk_parallel].
    """

    text: str
    """
    Text contents of the chunk.
    """

    offset: int = 0
    """
    Starting character offset of chunk.
    """

    line: int = 1
    """
    Starting line number of the chunk (indexed from 1).
    """

    column: int = 0
    """
    Starting column number of the chunk (index from 0).
    """

    sourcename: str = ""
    """
    Name of source (e.g. filename or path).
    """

    def after(self, text: str) -> Chunk:
        """Return a `Chunk` for `text` positioned immediately after this one.

        Computes the starting location based on the contents and starting
        position of the current chunk and copies the sourcename.
        """
        newlines = self.text.count("\n")
        offset = self.offset + len(self.text)
        if newlines == 0:
            return Chunk(
                text, offset, self.line, self.column + len(self.text), self.sourcename
            )
        column = len(self.text) - self.text.rfind("\n") - 1
        return Chunk(text, offset, self.line + newlines, column, self.sourcename)

    @staticmethod
    def _from_span(
        text: str, sm: SourceMap, start: int, stop: int, sourcename: str = ""
    ) -> Chunk | None:
        """Build a positioned `Chunk` for `text[start:stop]`, trimming surrounding
        whitespace; return `None` if the region is whitespace-only."""
        seg = text[start:stop]
        stripped = seg.lstrip()
        body = stripped.rstrip()
        if not body:
            return None
        offset = start + (len(seg) - len(stripped))  # advance past leading whitespace
        line, column = sm.line_col(offset)
        return Chunk(body, offset, line, column, sourcename)

    @staticmethod
    def _split_stream(
        increments: Iterator[str],
        rx: re.Pattern[str],
        where: str,
        sourcename: str = "",
    ) -> Iterator[Chunk]:
        """Split the concatenation of `increments` at each `rx` match, streaming.

        Holds only the current open chunk plus one read-ahead increment: it searches
        a growing buffer for the next delimiter, and only commits a match once a
        character past it has been read (or EOF) — so a match is never truncated by a
        read boundary. Reproduces `split_on_pattern` over the same text for
        delimiters that fit within the buffer.
        """
        before = where == "before"
        buf = ""
        base = 0  # absolute codepoint offset of buf[0]; kept == chunk_start
        chunk_start = 0  # absolute start of the current open (un-emitted) chunk
        resume = 0  # absolute offset to resume searching from (>= chunk_start)
        origin = 0  # absolute offset for which (oline, ocol) hold
        oline = 1  # 1-based line, like SourceMap
        ocol = 0  # 0-based column
        eof = False

        def advance_origin(to: int) -> None:
            nonlocal origin, oline, ocol
            seg = buf[origin - base : to - base]
            if seg:
                newlines = seg.count("\n")
                if newlines:
                    oline += newlines
                    ocol = len(seg) - seg.rindex("\n") - 1
                else:
                    ocol += len(seg)
                origin = to

        def make_chunk(a: int, b: int) -> Chunk | None:
            # Region [a, b): trim surrounding whitespace, advance origin to b, and
            # return a positioned Chunk (None for a whitespace-only region).
            seg = buf[a - base : b - base]
            stripped = seg.lstrip()
            body = stripped.rstrip()
            if not body:
                advance_origin(b)
                return None
            offset = a + (len(seg) - len(stripped))
            advance_origin(offset)
            line, column = oline, ocol
            advance_origin(b)
            return Chunk(body, offset, line, column, sourcename)

        while True:
            match = rx.search(buf, resume - base)
            if match is not None and (match.end() < len(buf) or eof):
                mstart = base + match.start()
                mend = base + match.end()
                boundary = mstart if before else mend
                chunk = make_chunk(chunk_start, boundary)
                if chunk is not None:
                    yield chunk
                chunk_start = boundary
                # Resume past this delimiter (non-overlapping, like finditer); guard a
                # zero-width match so the search position always advances.
                resume = mend if mend > mstart else mstart + 1
                if chunk_start > base:  # drop the emitted prefix
                    buf = buf[chunk_start - base :]
                    base = chunk_start
                continue
            if eof:
                chunk = make_chunk(chunk_start, base + len(buf))
                if chunk is not None:
                    yield chunk
                return
            piece = next(increments, None)
            if piece is None:
                eof = True
            elif piece:
                buf += piece


class FacadeListener:
    """Base for generated `<Grammar>EventListener` classes.

    Provides source-location access for the *current* event: while a callback is
    running, [span][antlrope.FacadeListener.span] returns its
    `(start, stop)` character offsets and
    [line_col][antlrope.FacadeListener.line_col] the 1-based line / 0-based
    column of its start. [drive][antlrope.FacadeListener.drive] populates this state per
    dispatched callback; outside a callback it reflects the most recent one.
    """

    # The stock ANTLR `<Grammar>Lexer` / `<Grammar>Parser` classes plus the grammar
    # metadata, all set by every generated subclass (declared here, no value).
    LEXER: ClassVar[type[LexerProtocol]]
    PARSER: ClassVar[type[ParserProtocol]]
    ruleNames: ClassVar[list[str]]
    START_RULE: ClassVar[int]

    _pyfacade_text: str = ""
    _pyfacade_start: int = -1
    _pyfacade_stop: int = -1
    _pyfacade_sourcemap: SourceMap | None = None
    # Source position of the parsed text's first character, so positions can be
    # reported against the whole source (see Chunk / walk_parallel). The
    # defaults — offset 0, line 1, column 0 — leave a plain `walk` unchanged.
    _pyfacade_base_offset: int = 0
    _pyfacade_base_linecol = LineCol()
    # Name of the source being parsed (e.g. a filename), for diagnostics. Empty
    # unless a Chunk carried a sourcename or `drive` was given one.
    _pyfacade_sourcename: str = ""

    # Reassigned to a fresh list by `drive` on every walk (never mutated in
    # place), so the shared class-level default is safe — hence the RUF012 waiver.
    syntax_errors: list[_native.ParseError] = []  # noqa: RUF012
    """Parse diagnostics collected during the most recent `walk`.

    A list of [ParseError][antlrope.ParseError] records, empty when the
    parse had no errors. The default ANTLR console error listener is suppressed, so
    these are the only report of a parse failure — inspect them instead of watching
    stderr.
    """

    def span(self) -> tuple[int, int]:
        """Return the `(start, stop)` character offsets of the current event.

        Offsets are into the whole source: for a `walk_parallel` chunk they
        include the chunk's start offset. `(-1, -1)` when the event has no span.
        """
        start, stop = self._pyfacade_start, self._pyfacade_stop
        if start < 0:
            return start, stop
        base = self._pyfacade_base_offset
        return start + base, stop + base

    def line_col(self) -> LineCol | None:
        """Return the `(line, column)` of the current event's start, or `None`.

        Returns:
            The 1-based line and 0-based column of the current event's start, or
            `None` when the event has no source span (e.g. an empty rule). For a
            `walk_parallel` chunk the position is reported against the whole
            source via the chunk's start. The
            [SourceMap][antlrope.SourceMap] is built once per walk on first
            use.
        """
        start = self._pyfacade_start
        if start < 0:
            return None
        sm = self._pyfacade_sourcemap
        if sm is None:
            sm = self._pyfacade_sourcemap = SourceMap(self._pyfacade_text)
        linecol = sm.line_col(start)
        # Offset into the whole source. Only the chunk's first line shares a line
        # with the chunk's start, so only it picks up the start column.
        return self._pyfacade_base_linecol.add(linecol)

    def sourcename(self) -> str:
        """Return the name of the source being parsed (empty if none was set).

        This is the `sourcename` of the [Chunk][antlrope.Chunk] being parsed
        (the chunkers can set it; the streaming ones default it to their file path),
        or whatever was passed to [drive][antlrope.FacadeListener.drive]. Use
        it with [line_col][antlrope.FacadeListener.line_col] to report a
        position as `sourcename:line:column`.
        """
        return self._pyfacade_sourcename

    def visitTerminal(self, token_type: int, text: str) -> None:
        """No-op terminal callback; override in a subclass to handle tokens."""

    def visitError(self, token_type: int, text: str) -> None:
        """No-op error callback; override in a subclass to handle error nodes."""

    @classmethod
    def _facade_base(cls) -> type[FacadeListener]:
        """Return the generated `<Grammar>EventListener` in this class's ancestry.

        That base (the class that directly subclasses `FacadeListener`) holds the
        no-op callback stubs [drive][antlrope.FacadeListener.drive] compares against to
        detect overrides, plus `ruleNames` / `START_RULE`. Works whether `cls` is
        the generated class itself or a user subclass of it.

        Raises:
            TypeError: If `cls` is not a generated facade listener subclass.
        """
        for klass in cls.__mro__:
            if FacadeListener in klass.__bases__:
                return cast("type[FacadeListener]", klass)
        raise TypeError(f"{cls.__name__} is not a generated facade listener subclass")

    @classmethod
    def _resolve_start_rule(
        cls, base: type[FacadeListener], start_rule: int | str | None
    ) -> int:
        """Turn a rule name, rule index, or `None` into a rule index for `base`."""
        if start_rule is None:
            return base.START_RULE
        if isinstance(start_rule, int):
            return start_rule
        try:
            return list(base.ruleNames).index(start_rule)
        except ValueError:
            raise ValueError(
                f"unknown start rule {start_rule!r}; "
                f"known rules: {list(base.ruleNames)}"
            ) from None

    @classmethod
    def _resolve_rule(cls, rule: str | int) -> int:
        """Resolve a rule name or index to a rule index for this grammar."""
        if isinstance(rule, int):
            return rule
        names = list(cls.ruleNames)
        try:
            return names.index(rule)
        except ValueError:
            raise ValueError(f"unknown rule {rule!r}; known rules: {names}") from None

    @classmethod
    def parser_spec(cls, *, cached: bool = True) -> _native.ParserSpec:
        """Return the native `parser_spec` built from this grammar's `PARSER` class.

        Reads the serialized ATN + name/vocabulary metadata off the baked-in stock
        `<Grammar>Parser` and hands it to the C++ runtime — the bridge that makes the
        runtime grammar-agnostic, with no codegen of our own. Pair it with
        [lexer_spec][antlrope.FacadeListener.lexer_spec] to feed
        [drive][antlrope.FacadeListener.drive] directly.

        Args:
            cached: When `True` (default), reuse/store the result in the per-parser
                cache. Pass `False` to force a fresh, independent spec — neither read
                from nor written to the cache — to avoid sharing entirely (e.g. one
                spec per worker thread).

        Returns:
            The `parser_spec` for the grammar. A spec owns a mutable ATN; with the
            vendored runtime's per-DFA locks sharing one across threads is correct and
            scales, so most parallel code can share a cached spec (or use
            [walk_parallel][antlrope.FacadeListener.walk_parallel]).
        """
        if cached:
            hit = _PARSER_SPEC_CACHE.get(cls.PARSER)
            if hit is not None:
                return hit
        spec = _build_parser_spec(cls.PARSER)
        if cached:
            _PARSER_SPEC_CACHE[cls.PARSER] = spec
        return spec

    @classmethod
    def lexer_spec(cls, *, cached: bool = True) -> _native.LexerSpec:
        """Return the native `lexer_spec` built from this grammar's `LEXER` class.

        The lexer-only counterpart of
        [parser_spec][antlrope.FacadeListener.parser_spec], for the token-based
        chunkers (and [lex][antlrope.FacadeListener.lex]) that lex without parsing.

        Args:
            cached: When `True` (default), reuse/store the result in the per-lexer
                cache; `False` forces a fresh, uncached spec.

        Returns:
            The `lexer_spec` for the grammar.
        """
        if cached:
            hit = _LEXER_SPEC_CACHE.get(cls.LEXER)
            if hit is not None:
                return hit
        spec = _build_lexer_spec(cls.LEXER)
        if cached:
            _LEXER_SPEC_CACHE[cls.LEXER] = spec
        return spec

    def walk(
        self,
        text: str,
        *,
        start_rule: int | str | None = None,
        filtered: bool = True,
    ) -> Self:
        """Parse `text` with this listener's baked-in lexer/parser and return `self`.

        Runs the parse in C++ and dispatches the event stream to this listener's
        callbacks. The lexer/parser come from the generated subclass's `LEXER` /
        `PARSER`, so no class arguments are needed.

        Args:
            start_rule: The rule to parse as — a rule name, a rule index, or `None`
                for the grammar's start rule.
            filtered: When `True` (default), only overridden rules/tokens are
                emitted by C++; `False` forces the full event stream.

        Returns:
            `self`, so calls chain (e.g. `result = Collector().walk(text).result`).

        Raises:
            TypeError: If called on a class that is not a generated
                `<Grammar>EventListener` subclass.
        """
        rule = self._resolve_start_rule(self._facade_base(), start_rule)
        self.drive(self.parser_spec(), self.lexer_spec(), text, rule, filtered=filtered)
        return self

    @classmethod
    def walk_parallel(
        cls,
        chunks: Iterable[str | Chunk],
        *,
        start_rule: int | str | None = None,
        max_workers: int | None = None,
        filtered: bool = True,
        factory: Callable[[], Self] | None = None,
    ) -> Iterator[Self]:
        """Parse independent `chunks` across a thread pool, one listener each.

        The native parse releases the GIL, so the parses overlap across cores. Each
        worker thread uses its own specs (built once via `cached=False`), so they
        never contend on a shared ATN. The per-event Python dispatch still holds
        the GIL, so parallel speedup scales with how parse-heavy the work is
        relative to per-callback Python work — see the "Parallel parsing" section
        of `docs/performance.md`.

        Args:
            chunks: The pieces of source to parse, each a self-contained piece
                (e.g. one record or top-level definition) that parses as
                `start_rule`. A bare `str` is treated as contiguous with the
                previous chunk and its source position is computed; a
                [Chunk][antlrope.Chunk] pins
                an explicit `offset` / `line` / `column` so callbacks
                report [span][antlrope.FacadeListener.span] /
                [line_col][antlrope.FacadeListener.line_col] against the
                whole source. Mix freely: a `Chunk` re-anchors the running position
                for the contiguous `str` chunks that follow it.
            start_rule: The rule each chunk parses as — a rule name, a rule index,
                or `None` for the grammar's start rule.
            max_workers: The maximum number of parses in flight at once (also the
                ordering/buffer window). Defaults to `os.cpu_count()`. With `1` it
                runs inline, without a pool.
            filtered: When `True` (default), only overridden rules/tokens are
                emitted by C++; `False` forces the full event stream.
            factory: A zero-argument callable returning a fresh listener, for
                subclasses whose constructor needs arguments. Defaults to `cls`.

        Returns:
            A lazy iterator of listeners, one per chunk, **in input order**. Chunks
            are pulled and parsed on demand with at most `max_workers` parses in
            flight, so neither the whole input nor all results are held at once —
            consume it incrementally (or `list(...)` it if you want them all). Each
            listener carries its accumulated state plus its
            [syntax_errors][antlrope.FacadeListener.syntax_errors].

        Raises:
            TypeError: If called on a class that is not a generated
                `<Grammar>EventListener` subclass (no baked-in `LEXER` / `PARSER`).
        """
        base = cls._facade_base()  # raises if not a generated facade subclass
        rule = cls._resolve_start_rule(base, start_rule)  # validate eagerly
        make = factory if factory is not None else cls
        workers = max_workers if max_workers is not None else (os.cpu_count() or 1)

        def run(chunk: Chunk) -> Self:
            parser_spec, lexer_spec = _specs_for_thread(cls)
            listener = make()
            listener.drive(
                parser_spec,
                lexer_spec,
                chunk.text,
                rule,
                filtered=filtered,
                origin=(chunk.offset, chunk.line, chunk.column),
                sourcename=chunk.sourcename,
            )
            return listener

        def resolved() -> Iterator[Chunk]:
            # A bare str continues contiguously from the previous chunk; a Chunk
            # pins its own position and re-anchors the str chunks that follow it.
            # The empty seed chunk starts the first str at the origin (0, 1, 0).
            chunk = Chunk("")
            for item in chunks:
                if isinstance(item, Chunk):
                    chunk = item
                elif isinstance(item, str):
                    chunk = chunk.after(item)
                else:
                    raise TypeError(
                        f"chunks must be str or Chunk, got {type(item).__name__}"
                    )
                yield chunk

        def stream() -> Iterator[Self]:
            if workers <= 1:
                for chunk in resolved():
                    yield run(chunk)
                return
            # Bounded-window parallelism: keep ~`workers` parses in flight and yield
            # in input order, so peak memory tracks the window, not the chunk count.
            with ThreadPoolExecutor(max_workers=workers) as pool:
                pending: deque[Future[Self]] = deque()
                for chunk in resolved():
                    pending.append(pool.submit(run, chunk))
                    if len(pending) > workers:
                        yield pending.popleft().result()
                while pending:
                    yield pending.popleft().result()

        return stream()

    def drive(
        self,
        parser_spec: _native.ParserSpec,
        lexer_spec: _native.LexerSpec,
        text: str,
        start_rule: int,
        *,
        filtered: bool = True,
        origin: tuple[int, int, int] = (0, 1, 0),
        sourcename: str = "",
    ) -> None:
        """Run the native parse and dispatch this listener's overridden callbacks.

        Usually invoked for you by the generated `walk` /
        [walk_parallel][antlrope.FacadeListener.walk_parallel]; call it
        directly to drive a listener from already-loaded specs.

        Args:
            parser_spec: The native parser spec (see
                [parser_spec][antlrope.FacadeListener.parser_spec]).
            lexer_spec: The native lexer spec.
            text: The source to parse.
            start_rule: The index of the rule to start parsing at.
            filtered: When `True` (default), only overridden rules/tokens are
                emitted by C++; `False` forces a faithful full event stream
                regardless of overrides.
            origin: The `(offset, line, column)` of `text`'s first character, so
                callbacks report positions against the whole source. Defaults to
                the start of the source, `(0, 1, 0)`.
            sourcename: Optional name of the source (e.g. a filename), returned by
                [sourcename][antlrope.FacadeListener.sourcename] during the
                walk.
        """
        cls = type(self)
        # The generated <Grammar>EventListener base holds the no-op callback stubs
        # to compare against for override detection, plus ruleNames.
        base_cls = self._facade_base()
        rule_names = base_cls.ruleNames

        enter: list[Callable | None] = [None] * len(rule_names)
        leave: list[Callable | None] = [None] * len(rule_names)
        rule_mask: list[int] = []
        for idx, name in enumerate(rule_names):
            cap = name[0].upper() + name[1:]
            e_over = getattr(cls, "enter" + cap) is not getattr(base_cls, "enter" + cap)
            x_over = getattr(cls, "exit" + cap) is not getattr(base_cls, "exit" + cap)
            if e_over:
                enter[idx] = getattr(self, "enter" + cap)
            if x_over:
                leave[idx] = getattr(self, "exit" + cap)
            if e_over or x_over:
                rule_mask.append(idx)

        visit = None
        token_mask: list[int] | None = []
        if cls.visitTerminal is not base_cls.visitTerminal:
            visit = self.visitTerminal
            toks = getattr(cls, "TERMINAL_TOKENS", None)
            token_mask = list(toks) if toks is not None else None

        on_error = None
        if cls.visitError is not base_cls.visitError:
            on_error = self.visitError

        # filtered=False forces a faithful full stream regardless of overrides.
        r_mask = rule_mask if filtered else None
        t_mask = token_mask if filtered else None
        raw, errors = _native.parse_events(
            parser_spec, lexer_spec, text, start_rule, r_mask, t_mask
        )
        self.syntax_errors = errors

        # Source-location state read by span / line_col. Reset the cached map so a
        # reused listener re-derives it for this text.
        self._pyfacade_text = text
        self._pyfacade_sourcemap = None
        self._pyfacade_sourcename = sourcename
        self._pyfacade_base_offset = origin[0]
        self._pyfacade_base_linecol = LineCol(origin[1], origin[2])

        for kind, payload, start, stop in struct.iter_unpack(_REC, raw):
            if kind == EV_TERMINAL:
                if visit is not None:
                    self._pyfacade_start = start
                    self._pyfacade_stop = stop
                    visit(payload, text[start : stop + 1])
            elif kind == EV_ENTER:
                cb = enter[payload]
                if cb is not None:
                    self._pyfacade_start = start
                    self._pyfacade_stop = stop
                    cb()
            elif kind == EV_EXIT:
                cb = leave[payload]
                if cb is not None:
                    self._pyfacade_start = start
                    self._pyfacade_stop = stop
                    cb()
            elif kind == EV_ERROR and on_error is not None:
                self._pyfacade_start = start
                self._pyfacade_stop = stop
                err_text = text[start : stop + 1] if 0 <= start <= stop else ""
                on_error(payload, err_text)

    # ------------------------------------------------------------------ chunking
    # Split a whole source into positioned `Chunk`s for `walk_parallel`. Token- and
    # rule-based chunkers source the lexer/parser from this class's baked-in `LEXER`
    # / `PARSER`; the regex ones need neither. See `docs/chunking.md`.

    @classmethod
    def lex(
        cls,
        text: str,
        *,
        keep: Iterable[int] | None = None,
        cached: bool = True,
    ) -> Iterator[LexToken]:
        """Tokenize `text` with the grammar's lexer (no parsing).

        Lazy: the work runs as the result is iterated. Wrap in `list(...)` for random
        access. The native lexer streams tokens rather than buffering the whole stream.

        Args:
            text: The source to tokenize.
            keep: Optional token types to return; the lexer drops every other token in
                C++ so only these cross into Python. `None` returns all tokens.
            cached: Reuse the cached lexer spec (see
                [lexer_spec][antlrope.FacadeListener.lexer_spec]).

        Yields:
            The kept tokens in source order (the EOF sentinel omitted). Tokens the
            lexer drops via `-> skip` do not appear; tokens routed to a non-default
            channel (`-> channel(...)`) appear with that `channel`. Lexer errors are
            recovered from and not reported here.
        """
        spec = cls.lexer_spec(cached=cached)
        mask = None if keep is None else list(keep)
        raw, _errors = _native.lex(spec, text, mask)
        for rec in _TOK.iter_unpack(raw):
            yield LexToken(*rec)

    @classmethod
    def split_on_token(
        cls,
        text: str,
        token_types: TokenTypes,
        *,
        where: str = "before",
        channel: int | None = DEFAULT_CHANNEL,
        sourcename: str = "",
    ) -> Iterator[Chunk]:
        """Split `text` into chunks at each delimiter token.

        Token-aware: because it runs the grammar's lexer, a delimiter that appears
        inside a string or comment token never causes a split. The price is lexing the
        whole input — roughly an order of magnitude slower than the regex
        [split_on_pattern][antlrope.FacadeListener.split_on_pattern] at finding the
        delimiters (~4x end to end), though still negligible next to the parse it
        feeds. See the "Chunking: lexer vs regex" notes in `docs/performance.md`.

        Args:
            text: The source to split.
            token_types: The delimiter token type, or several types that all act as
                delimiters (e.g. `MyLexer.RECORD`, or `{MyLexer.RECORD, MyLexer.NOTE}`).
            where: `"before"` starts a new chunk at each delimiter (each chunk begins
                with one), so content before the first delimiter is its own leading
                chunk; `"after"` ends a chunk at each delimiter (each chunk ends with
                one), so content after the last delimiter is a trailing chunk.
            channel: Only tokens on this channel are split on (default: the default
                channel). Pass `None` to consider all channels.
            sourcename: Optional source name (e.g. a filename) recorded on each
                [Chunk][antlrope.Chunk], surfaced during a walk as
                [sourcename][antlrope.FacadeListener.sourcename].

        Yields:
            One [Chunk][antlrope.Chunk] per region between delimiters, trimmed of
            surrounding whitespace and carrying its source position. Whitespace-only
            regions are skipped.
        """
        if where not in ("before", "after"):
            raise ValueError(f"where must be 'before' or 'after', got {where!r}")
        delims = _as_set(token_types)
        bounds = [
            t
            for t in cls.lex(text, keep=delims)
            if channel is None or t.channel == channel
        ]
        sm = SourceMap(text)
        n = len(text)
        if where == "before":
            first = bounds[0].start if bounds else n
            if first > 0:  # leading region, before the first delimiter
                chunk = Chunk._from_span(text, sm, 0, first, sourcename)
                if chunk is not None:
                    yield chunk
            for i, b in enumerate(bounds):
                end = bounds[i + 1].start if i + 1 < len(bounds) else n
                chunk = Chunk._from_span(text, sm, b.start, end, sourcename)
                if chunk is not None:
                    yield chunk
        else:  # after
            prev = 0
            for b in bounds:
                chunk = Chunk._from_span(text, sm, prev, b.stop + 1, sourcename)
                if chunk is not None:
                    yield chunk
                prev = b.stop + 1
            if prev < n:  # trailing region, after the last delimiter
                chunk = Chunk._from_span(text, sm, prev, n, sourcename)
                if chunk is not None:
                    yield chunk

    @classmethod
    def stream_on_token(
        cls,
        path: str | os.PathLike[str],
        token_types: TokenTypes,
        *,
        where: str = "before",
        encoding: str = "utf-8",
        channel: int | None = DEFAULT_CHANNEL,
        sourcename: str = "",
        batch: int = 256,
        cached: bool = True,
        _block_bytes: int = 0,
    ) -> Iterator[Chunk]:
        """Stream chunks from a file at each delimiter token, without holding it all.

        The streaming counterpart of
        [split_on_token][antlrope.FacadeListener.split_on_token]: instead of taking
        the whole source as a `str`, it opens `path` in C++ and lexes it incrementally
        over a sliding window, slicing out and freeing each chunk as it goes — so peak
        memory is roughly one chunk rather than the whole file. The yielded
        [Chunk][antlrope.Chunk]s drop straight into
        [walk_parallel][antlrope.FacadeListener.walk_parallel], which pulls them
        lazily, keeping the whole pipeline bounded.

        Args:
            path: Filesystem path to the source (opened by the native layer as UTF-8).
            token_types: The delimiter token type, or several types that all act as
                delimiters (see
                [split_on_token][antlrope.FacadeListener.split_on_token]).
            where: `"before"` starts a new chunk at each delimiter; `"after"` ends a
                chunk at each delimiter (see split_on_token).
            encoding: The source encoding. Only UTF-8 is supported today (Python codec
                aliases such as `"utf8"` are accepted); the keyword is reserved so other
                encodings can be added later. For a non-UTF-8 source now, decode it in
                Python (`Path(p).read_text(encoding=...)`) and use the in-memory
                [split_on_token][antlrope.FacadeListener.split_on_token].
            channel: Only tokens on this channel are split on (default: the default
                channel). Pass `None` to consider all channels.
            sourcename: Source name recorded on each [Chunk][antlrope.Chunk] (and
                surfaced as [sourcename][antlrope.FacadeListener.sourcename] during
                a walk). Defaults to `str(path)`.
            batch: How many chunk records to pull from C++ per call — a throughput knob,
                not observable in the output.
            cached: Reuse the cached lexer spec (see
                [lexer_spec][antlrope.FacadeListener.lexer_spec]).

        Yields:
            One [Chunk][antlrope.Chunk] per region between delimiters, trimmed of
            surrounding whitespace and carrying its source position; whitespace-only
            regions are skipped. Equivalent to `split_on_token` over the file's text.

        Raises:
            ValueError: If `where` is not `"before"`/`"after"`, or `encoding` is not
                UTF-8.
        """
        if where not in ("before", "after"):
            raise ValueError(f"where must be 'before' or 'after', got {where!r}")
        # Reserve the keyword for future encodings while only UTF-8 is implemented.
        # codecs.lookup normalizes aliases ("utf8", "UTF-8", "U8") to "utf-8".
        if codecs.lookup(encoding).name != "utf-8":
            raise ValueError(
                f"stream_on_token currently supports only UTF-8, got {encoding!r}; "
                f"decode in Python and use split_on_token for other encodings"
            )
        src_path = os.fspath(path)
        if not sourcename:
            sourcename = src_path
        spec = cls.lexer_spec(cached=cached)
        chunker = _native.StreamChunker(
            spec,
            src_path,
            list(_as_set(token_types)),
            0 if where == "before" else 1,
            channel,
            True,  # lenient: substitute U+FFFD for malformed bytes
            _block_bytes,
        )
        more = True
        while more:
            rows, more = chunker.next_batch(batch)
            for offset, line, column, body in rows:
                yield Chunk(body, offset, line, column, sourcename)

    @classmethod
    def split_between_tokens(
        cls,
        text: str,
        pairs: Pair | list[Pair],
        *,
        nested: bool = False,
        channel: int | None = DEFAULT_CHANNEL,
        sourcename: str = "",
    ) -> Iterator[Chunk]:
        """Yield a chunk for each region bounded by an opener/closer pair.

        Token-aware, like [split_on_token][antlrope.FacadeListener.split_on_token]:
        it lexes the whole input, so a bracket inside a string or comment is ignored,
        at the cost of being slower than a plain regex over the text (see the
        "Chunking: lexer vs regex" notes in `docs/performance.md`).

        Args:
            text: The source to split.
            pairs: One `(open, close)` pair, or a list of them. Each side is a token
                type or several equivalent types (e.g. `(MyLexer.LBRACE,
                MyLexer.RBRACE)`, or `({MyLexer.BEGIN, MyLexer.DO}, {MyLexer.END})`).
                With multiple pairs (e.g. `[(LPAREN, RPAREN), (LBRACK, RBRACK)]`) each
                opener is matched only by a closer of its **own** pair, so distinct
                bracket kinds nest correctly. Open and close types should be disjoint.
            nested: When `True`, treat regions as balanced — match openers to closers
                by depth (respecting pair identity) and emit the outermost regions.
                When `False` (default), each opener pairs with the next closer of its
                pair and scanning resumes after it.
            channel: Only tokens on this channel are considered (default: the default
                channel). Pass `None` to consider all channels.
            sourcename: Optional source name (e.g. a filename) recorded on each
                [Chunk][antlrope.Chunk], surfaced during a walk as
                [sourcename][antlrope.FacadeListener.sourcename].

        Yields:
            One [Chunk][antlrope.Chunk] per region — the text from the opener's
            start to the closer's stop, inclusive — in source order. An unmatched
            opener yields nothing; a closer with no matching open is ignored.
        """
        norm = _normalize_pairs(pairs)
        open_to_pair: dict[int, int] = {}
        close_to_pair: dict[int, int] = {}
        keep: set[int] = set()
        for i, (opens, closes) in enumerate(norm):
            for o in opens:
                open_to_pair[o] = i
                keep.add(o)
            for c in closes:
                close_to_pair[c] = i
                keep.add(c)
        toks = [
            t
            for t in cls.lex(text, keep=keep)
            if channel is None or t.channel == channel
        ]
        sm = SourceMap(text)
        n = len(toks)
        if nested:
            stack: list[int] = []  # pair ids of the currently-open brackets
            start: int | None = None
            for idx in range(n):
                ttype = toks[idx].type
                if ttype in open_to_pair:
                    if not stack:
                        start = idx
                    stack.append(open_to_pair[ttype])
                elif ttype in close_to_pair:
                    # Only a closer matching the innermost opener pops the stack;
                    # a mismatched/stray closer is ignored.
                    if stack and stack[-1] == close_to_pair[ttype]:
                        stack.pop()
                        if not stack and start is not None:
                            chunk = Chunk._from_span(
                                text,
                                sm,
                                toks[start].start,
                                toks[idx].stop + 1,
                                sourcename,
                            )
                            if chunk is not None:
                                yield chunk
                            start = None
        else:
            idx = 0
            while idx < n:
                pair_id = open_to_pair.get(toks[idx].type)
                if pair_id is not None:
                    j = idx + 1
                    while j < n and close_to_pair.get(toks[j].type) != pair_id:
                        j += 1
                    if j >= n:
                        break  # opener with no matching closer
                    chunk = Chunk._from_span(
                        text, sm, toks[idx].start, toks[j].stop + 1, sourcename
                    )
                    if chunk is not None:
                        yield chunk
                    idx = j + 1
                else:
                    idx += 1

    @classmethod
    def split_on_pattern(
        cls,
        text: str,
        pattern: str | re.Pattern[str],
        *,
        where: str = "before",
        flags: int | re.RegexFlag = 0,
        sourcename: str = "",
    ) -> Iterator[Chunk]:
        """Split `text` into chunks at each match of a delimiter regex.

        The regex analogue of
        [split_on_token][antlrope.FacadeListener.split_on_token]. No lexer is
        involved, so it is much faster — roughly an order of magnitude at finding
        delimiters and a few times end to end (the per-chunk Python work is shared) —
        but **not token-aware**: a match inside a string or comment still delimits.
        Prefer it when the delimiter can't appear in disguise; otherwise use the
        token-based splitter. See the "Chunking: lexer vs regex" notes in
        `docs/performance.md`.

        Args:
            text: The source to split.
            pattern: The delimiter regular expression (a `str` or compiled pattern).
            where: `"before"` starts each chunk at a match; `"after"` ends each chunk
                at a match (see split_on_token).
            flags: `re` flags, used only when `pattern` is a `str`.
            sourcename: Optional source name (e.g. a filename) recorded on each
                [Chunk][antlrope.Chunk], surfaced during a walk as
                [sourcename][antlrope.FacadeListener.sourcename].

        Yields:
            One [Chunk][antlrope.Chunk] per region between matches, trimmed of
            surrounding whitespace; whitespace-only regions are skipped.
        """
        if where not in ("before", "after"):
            raise ValueError(f"where must be 'before' or 'after', got {where!r}")
        rx = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
        sm = SourceMap(text)
        matches = list(rx.finditer(text))
        n = len(text)
        if where == "before":
            first = matches[0].start() if matches else n
            if first > 0:  # leading region, before the first match
                chunk = Chunk._from_span(text, sm, 0, first, sourcename)
                if chunk is not None:
                    yield chunk
            for i, m in enumerate(matches):
                end = matches[i + 1].start() if i + 1 < len(matches) else n
                chunk = Chunk._from_span(text, sm, m.start(), end, sourcename)
                if chunk is not None:
                    yield chunk
        else:  # after
            prev = 0
            for m in matches:
                chunk = Chunk._from_span(text, sm, prev, m.end(), sourcename)
                if chunk is not None:
                    yield chunk
                prev = m.end()
            if prev < n:  # trailing region, after the last match
                chunk = Chunk._from_span(text, sm, prev, n, sourcename)
                if chunk is not None:
                    yield chunk

    @classmethod
    def stream_on_pattern(
        cls,
        source: TextSource,
        pattern: str | re.Pattern[str],
        *,
        where: str = "before",
        flags: int | re.RegexFlag = 0,
        window_chars: int | None = 65536,
        window_lines: int | None = None,
        encoding: str = "utf-8",
        sourcename: str = "",
    ) -> Iterator[Chunk]:
        """Stream chunks from a text source at each delimiter regex match.

        The streaming counterpart of
        [split_on_pattern][antlrope.FacadeListener.split_on_pattern]: it reads
        `source` incrementally and yields positioned [Chunk][antlrope.Chunk]s
        without holding the whole input, so paired with
        [walk_parallel][antlrope.FacadeListener.walk_parallel] the pipeline stays
        bounded. Because the regex is Python's, encoding is handled on the Python side
        (unlike the lexer-based
        [stream_on_token][antlrope.FacadeListener.stream_on_token], which reads UTF-8
        in C++) — any encoding a text file supports works.

        A delimiter match is only committed once a character past it has been read (or
        the source ends), so a match is never split across a read boundary, **as long
        as the delimiter fits within the read window**. A region with no delimiter is
        buffered in full (like the other streamers).

        Args:
            source: A filesystem `path` (opened with `encoding`), an already-open text
                file object, or any iterable of `str` pieces (e.g. lines, or a
                generator). For an in-memory string, use `split_on_pattern` instead.
            pattern: The delimiter regular expression (a `str` or compiled pattern).
            where: `"before"` starts each chunk at a match; `"after"` ends each chunk at
                a match (see split_on_pattern).
            flags: `re` flags, used only when `pattern` is a `str`.
            window_chars: Read/search increment in characters (default 64K). Controls
                how often the regex re-runs and how much read-ahead is buffered, not the
                output. Used when reading a path or file object.
            window_lines: If set, read this many lines per step instead (still capped by
                `window_chars` if both are given) — convenient for line-oriented
                delimiters. Ignored for a plain `str` iterable, which is consumed as-is.
            encoding: Text encoding, used only when `source` is a path. Any codec
                Python supports.
            sourcename: Source name recorded on each [Chunk][antlrope.Chunk] (and
                surfaced as [sourcename][antlrope.FacadeListener.sourcename] during
                a walk). Defaults to the path when `source` is a path, else `None` — pass
                it for a stream or iterable that has no path.

        Yields:
            One [Chunk][antlrope.Chunk] per region between matches, trimmed of
            surrounding whitespace and carrying its source position; whitespace-only
            regions are skipped. Equivalent to `split_on_pattern` over the source's
            decoded text.

        Raises:
            ValueError: If `where` is not `"before"`/`"after"`.
        """
        if where not in ("before", "after"):
            raise ValueError(f"where must be 'before' or 'after', got {where!r}")
        rx = re.compile(pattern, flags) if isinstance(pattern, str) else pattern

        opened = None
        if isinstance(source, (str, os.PathLike)):
            fspath = os.fspath(source)
            if not sourcename:
                sourcename = fspath
            opened = open(fspath, encoding=encoding)  # noqa: SIM115
            increments = _read_increments(opened, window_chars, window_lines)
        elif hasattr(source, "read"):
            increments = _read_increments(source, window_chars, window_lines)
        else:
            increments = iter(source)
        try:
            yield from Chunk._split_stream(increments, rx, where, sourcename)
        finally:
            if opened is not None:
                opened.close()

    @classmethod
    def chunk_by_pattern(
        cls,
        text: str,
        pattern: str | re.Pattern[str],
        *,
        flags: int | re.RegexFlag = 0,
        sourcename: str = "",
    ) -> Iterator[Chunk]:
        """Yield one chunk per non-overlapping match of `pattern`.

        Here the pattern matches a whole record (rather than a delimiter), so each
        match *is* a chunk and the text between matches is dropped. No lexer is
        involved — fast, but not token-aware; see
        [split_on_pattern][antlrope.FacadeListener.split_on_pattern] and the
        "Chunking: lexer vs regex" notes in `docs/performance.md` for the
        speed/correctness trade-off.

        Args:
            text: The source to split.
            pattern: A regular expression matching one record (a `str` or compiled
                pattern).
            flags: `re` flags, used only when `pattern` is a `str`.
            sourcename: Optional source name (e.g. a filename) recorded on each
                [Chunk][antlrope.Chunk], surfaced during a walk as
                [sourcename][antlrope.FacadeListener.sourcename].

        Yields:
            One [Chunk][antlrope.Chunk] per match, trimmed of surrounding
            whitespace; empty matches are skipped.
        """
        rx = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
        sm = SourceMap(text)
        for m in rx.finditer(text):
            chunk = Chunk._from_span(text, sm, m.start(), m.end(), sourcename)
            if chunk is not None:
                yield chunk

    @classmethod
    def chunk_by_rule(
        cls,
        text: str,
        rule: RuleTypes,
        *,
        start_rule: str | int | None = None,
        outermost: bool = True,
        cached: bool = True,
        sourcename: str = "",
    ) -> Iterator[Chunk]:
        """Yield each occurrence of a grammar `rule` as a chunk.

        Unlike the token and regex chunkers, this **parses** the whole input (with the
        grammar's `ParserInterpreter`) to find where the rule occurs — the structural
        counterpart to the heuristic splitters. The parse runs **entirely in C++** and
        only the resulting `(start, stop)` spans cross into Python, so it stays cheap
        relative to the per-chunk `walk_parallel` re-parse it feeds; prefer it when
        that callback work dominates, or when no token/regex delimiter cleanly marks a
        record. See `docs/performance.md`.

        Args:
            text: The source to split.
            rule: The rule to chunk by — a rule name or index, or several of them
                (e.g. `"function"`, or `{"function", "class"}`).
            start_rule: The rule the whole input parses as — a name, an index, or
                `None` for the grammar's start rule (index 0).
            outermost: When `True` (default), only top-level occurrences are emitted;
                a matched rule nested inside another match is skipped. `False` emits
                every occurrence (which would overlap).
            cached: Reuse the cached specs (see
                [parser_spec][antlrope.FacadeListener.parser_spec]).
            sourcename: Optional source name (e.g. a filename) recorded on each
                [Chunk][antlrope.Chunk], surfaced during a walk as
                [sourcename][antlrope.FacadeListener.sourcename].

        Yields:
            One [Chunk][antlrope.Chunk] per matched rule occurrence, in source
            order, trimmed of surrounding whitespace and carrying its position. An
            empty occurrence (a rule that consumed no token) is skipped.
        """
        parser_spec = cls.parser_spec(cached=cached)
        lexer_spec = cls.lexer_spec(cached=cached)
        if isinstance(rule, (int, str)):
            rule_mask = [cls._resolve_rule(rule)]
        else:
            rule_mask = [cls._resolve_rule(r) for r in rule]
        start_idx = 0 if start_rule is None else cls._resolve_rule(start_rule)

        raw, _errors = _native.rule_spans(
            parser_spec, lexer_spec, text, start_idx, rule_mask, outermost
        )
        sm = SourceMap(text)
        for _ridx, start, stop in _RULE.iter_unpack(raw):
            if start < 0:  # empty rule occurrence — no source span
                continue
            chunk = Chunk._from_span(text, sm, start, stop + 1, sourcename)
            if chunk is not None:
                yield chunk

    @classmethod
    def stream_by_rule(
        cls,
        path: str | os.PathLike[str],
        rule: RuleTypes,
        *,
        sourcename: str = "",
        encoding: str = "utf-8",
        batch: int = 256,
        cached: bool = True,
        _block_bytes: int = 0,
    ) -> Iterator[Chunk]:
        """Stream chunks from a file that is a sequence of a grammar `rule`.

        The streaming counterpart of
        [chunk_by_rule][antlrope.FacadeListener.chunk_by_rule], for input that is a
        top-level **sequence of records** — each record an occurrence of `rule` (or one
        of several rules). It parses one record at a time over a bounded-memory
        pipeline (the native layer opens the file and runs lexer → parser over a
        sliding window), yielding each as a positioned [Chunk][antlrope.Chunk]
        without holding the whole token stream or parse tree. The chunks feed
        [walk_parallel][antlrope.FacadeListener.walk_parallel] like any other.

        Unlike `chunk_by_rule` — which parses the whole input and finds the rule *anywhere*
        in the tree — this is the bounded-memory "file of records" form. Records must be
        **directly adjacent**: only lexer-skipped tokens (whitespace, comments) may sit
        between them. With several candidate `rule`s, the next token chooses which to parse
        (via each rule's start-token set), so the candidates should have **disjoint leading
        tokens** (e.g. `class` vs `def`); on overlap the first listed wins. An on-channel
        separator between records (e.g. a comma) is not supported — use `chunk_by_rule` or
        [stream_on_token][antlrope.FacadeListener.stream_on_token] there.

        Args:
            path: Filesystem path to the source (opened by the native layer as UTF-8).
            rule: The record rule — a rule name or index, or several of them (a set of
                top-level record types, e.g. `{"classdef", "funcdef"}`).
            sourcename: Source name recorded on each [Chunk][antlrope.Chunk] (and
                surfaced as [sourcename][antlrope.FacadeListener.sourcename] during a
                walk). Defaults to `str(path)`.
            encoding: The source encoding. Only UTF-8 is supported today (Python codec
                aliases are accepted); the keyword is reserved for future encodings.
            batch: How many records to pull from C++ per call — a throughput knob.
            cached: Reuse the cached specs (see [parser_spec][antlrope.FacadeListener.parser_spec]).

        Yields:
            One [Chunk][antlrope.Chunk] per record, in source order, carrying its
            position. The stream stops at end of input, or at the first token that begins
            no candidate rule (or a record that fails to parse) — best-effort, like the
            other chunkers.

        Raises:
            ValueError: If `encoding` is not UTF-8, or a rule name is unknown.
        """
        if codecs.lookup(encoding).name != "utf-8":
            raise ValueError(
                f"stream_by_rule currently supports only UTF-8, got {encoding!r}; "
                f"decode in Python and use chunk_by_rule for other encodings"
            )
        if isinstance(rule, (int, str)):
            rule_indices = [cls._resolve_rule(rule)]
        else:
            rule_indices = [cls._resolve_rule(r) for r in rule]
        src_path = os.fspath(path)
        if not sourcename:
            sourcename = src_path
        parser_spec = cls.parser_spec(cached=cached)
        lexer_spec = cls.lexer_spec(cached=cached)
        chunker = _native.StreamRuleChunker(
            parser_spec,
            lexer_spec,
            src_path,
            rule_indices,
            True,  # lenient: substitute U+FFFD for malformed bytes
            _block_bytes,
        )
        more = True
        while more:
            rows, more = chunker.next_batch(batch)
            for offset, line, column, body in rows:
                yield Chunk(body, offset, line, column, sourcename)
