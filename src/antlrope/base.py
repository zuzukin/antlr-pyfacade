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
"""

from __future__ import annotations

import os
import struct
import threading
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import ClassVar, NamedTuple, TypeVar

from . import _native
from .location import LineCol, SourceMap
from .specs import load_specs

__all__ = [
    "Chunk",
    "FacadeListener",
]

EV_ENTER, EV_EXIT, EV_TERMINAL, EV_ERROR = 0, 1, 2, 3
_REC = "<4i"

# Per-thread spec cache for parallel parsing. Each worker thread builds its own
# (parser_spec, lexer_spec) once per grammar with cached=False. With the vendored
# runtime's per-DFA locks a shared spec scales too, but a per-thread spec is the
# simple, robust default — independent of that patch and with no shared mutable
# state at all (see docs/performance.md "Parallel parsing").
_thread_specs = threading.local()


def _specs_for_thread(
    lexer_cls: type, parser_cls: type
) -> tuple[_native.ParserSpec, _native.LexerSpec]:
    cache = getattr(_thread_specs, "cache", None)
    if cache is None:
        cache = _thread_specs.cache = {}
    key = (lexer_cls, parser_cls)
    specs = cache.get(key)
    if specs is None:
        specs = cache[key] = load_specs(lexer_cls, parser_cls, cached=False)
    return specs


class Chunk(NamedTuple):
    """A contiguous chunk of source text plus location information.

    These are produced by various "chunker" functions, such as
    [chunk_by_pattern][antlrope.chunking.chunk_by_pattern]
    for consumption by [FacadeListener.walk_parallel][antlrope.FacadeListener.walk_parallel].
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


# Bound to FacadeListener so `walk` returns the concrete subclass (Self-like on
# Python < 3.11, which `requires-python = ">=3.10"` still supports).
_F = TypeVar("_F", bound="FacadeListener")


class FacadeListener:
    """Base for generated `<Grammar>EventListener` classes.

    Provides source-location access for the *current* event: while a callback is
    running, [span][antlrope.FacadeListener.span] returns its
    `(start, stop)` character offsets and
    [line_col][antlrope.FacadeListener.line_col] the 1-based line / 0-based
    column of its start. [drive][antlrope.FacadeListener.drive] populates this state per
    dispatched callback; outside a callback it reflects the most recent one.
    """

    # The stock ANTLR `<Grammar>Lexer` / `<Grammar>Parser` classes, baked into the
    # generated `<Grammar>EventListener` so `walk` / `walk_parallel` need no class
    # arguments. Declared here (no value) and set by every generated subclass.
    LEXER: ClassVar[type]
    PARSER: ClassVar[type]

    _pyfacade_text: str = ""
    _pyfacade_start: int = -1
    _pyfacade_stop: int = -1
    _pyfacade_sourcemap: SourceMap | None = None
    # Source position of the parsed text's first character, so positions can be
    # reported against the whole source (see Chunk / walk_parallel). The
    # defaults — offset 0, line 1, column 0 — leave a plain `walk` unchanged.
    _pyfacade_base_offset: int = 0
    _pyfacade_base_linecol = LineCol()
    # Name of the source being parsed (e.g. a filename), for diagnostics. None
    # unless a Chunk carried a sourcename or `drive` was given one.
    _pyfacade_sourcename: str | None = None

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

    def sourcename(self) -> str | None:
        """Return the name of the source being parsed, or `None`.

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
    def _facade_base(cls) -> type:
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
                return klass
        raise TypeError(f"{cls.__name__} is not a generated facade listener subclass")

    # TODO - pick a more precise declared base type or create a Protocol that has the expected interface

    @classmethod
    def _resolve_start_rule(cls, base: type, start_rule: int | str | None) -> int:
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

    def walk(
        self: _F,
        text: str,
        *,
        start_rule: int | str | None = None,
        filtered: bool = True,
    ) -> _F:
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
        parser_spec, lexer_spec = load_specs(self.LEXER, self.PARSER)
        rule = self._resolve_start_rule(self._facade_base(), start_rule)
        self.drive(parser_spec, lexer_spec, text, rule, filtered=filtered)
        return self

    @classmethod
    def walk_parallel(
        cls: type[_F],
        chunks: Iterable[str | Chunk],
        *,
        start_rule: int | str | None = None,
        max_workers: int | None = None,
        filtered: bool = True,
        factory: Callable[[], _F] | None = None,
    ) -> Iterator[_F]:
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
        lexer_cls = cls.LEXER
        parser_cls = cls.PARSER
        make = factory if factory is not None else cls
        workers = max_workers if max_workers is not None else (os.cpu_count() or 1)

        def run(chunk: Chunk) -> _F:
            parser_spec, lexer_spec = _specs_for_thread(lexer_cls, parser_cls)
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

        def stream() -> Iterator[_F]:
            if workers <= 1:
                for chunk in resolved():
                    yield run(chunk)
                return
            # Bounded-window parallelism: keep ~`workers` parses in flight and yield
            # in input order, so peak memory tracks the window, not the chunk count.
            with ThreadPoolExecutor(max_workers=workers) as pool:
                pending: deque[Future[_F]] = deque()
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
        sourcename: str | None = None,
    ) -> None:
        """Run the native parse and dispatch this listener's overridden callbacks.

        Usually invoked for you by the generated `walk` /
        [walk_parallel][antlrope.FacadeListener.walk_parallel]; call it
        directly to drive a listener from already-loaded specs.

        Args:
            parser_spec: The native parser spec (see
                [load_specs][antlrope.load_specs]).
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
