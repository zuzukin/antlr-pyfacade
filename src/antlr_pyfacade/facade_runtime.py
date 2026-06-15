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

"""Driver for generated grammar-specific event listeners.

A generated `<Grammar>EventListener` subclass declares named callbacks
(`enter<Rule>` / `exit<Rule>` / `visitTerminal` / `visitError`) just like the
stock ANTLR listener. [`drive`][antlr_pyfacade.drive] runs the bulk native event
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
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, NamedTuple

from . import _native
from .location import SourceMap
from .specs import load_specs

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from concurrent.futures import Future

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
    """A piece of source plus where it begins, for `walk_parallel`.

    Pass a bare `str` for a chunk that is contiguous with the previous one (its
    position is computed); pass a `Chunk` to pin an explicit source position via
    `offset` / `line` / `column` — e.g. for pieces that are not contiguous in the
    original source. The position lets per-event
    [`span`][antlr_pyfacade.FacadeListener.span] /
    [`line_col`][antlr_pyfacade.FacadeListener.line_col] be reported against the
    whole source rather than the chunk.
    """

    text: str
    offset: int = 0  # 0-based character offset of the first character
    line: int = 1  # 1-based line of the first character
    column: int = 0  # 0-based column of the first character


def _advance(chunk: Chunk) -> tuple[int, int, int]:
    """Return the `(offset, line, column)` immediately after `chunk`.

    That is where the next chunk begins when chunks are contiguous.
    """
    text = chunk.text
    newlines = text.count("\n")
    offset = chunk.offset + len(text)
    if newlines == 0:
        return offset, chunk.line, chunk.column + len(text)
    return offset, chunk.line + newlines, len(text) - text.rfind("\n") - 1


class FacadeListener:
    """Base for generated `<Grammar>EventListener` classes.

    Provides source-location access for the *current* event: while a callback is
    running, [`span`][antlr_pyfacade.FacadeListener.span] returns its
    `(start, stop)` character offsets and
    [`line_col`][antlr_pyfacade.FacadeListener.line_col] the 1-based line / 0-based
    column of its start. [`drive`][antlr_pyfacade.drive] populates this state per
    dispatched callback; outside a callback it reflects the most recent one.
    """

    _pyfacade_text: str = ""
    _pyfacade_start: int = -1
    _pyfacade_stop: int = -1
    _pyfacade_sourcemap: SourceMap | None = None
    # Source position of the parsed text's first character, so positions can be
    # reported against the whole source (see ChunkStart / walk_parallel). The
    # defaults — offset 0, line 1, column 0 — leave a plain `walk` unchanged.
    _pyfacade_base_offset: int = 0
    _pyfacade_base_line: int = 1
    _pyfacade_base_col: int = 0

    # Reassigned to a fresh list by `drive` on every walk (never mutated in
    # place), so the shared class-level default is safe — hence the RUF012 waiver.
    syntax_errors: list[_native.ParseError] = []  # noqa: RUF012
    """Parse diagnostics collected during the most recent `walk`.

    A list of [`ParseError`][antlr_pyfacade.ParseError] records, empty when the
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

    def line_col(self) -> tuple[int, int] | None:
        """Return the `(line, column)` of the current event's start, or `None`.

        Returns:
            The 1-based line and 0-based column of the current event's start, or
            `None` when the event has no source span (e.g. an empty rule). For a
            `walk_parallel` chunk the position is reported against the whole
            source via the chunk's start. The
            [`SourceMap`][antlr_pyfacade.SourceMap] is built once per walk on first
            use.
        """
        start = self._pyfacade_start
        if start < 0:
            return None
        sm = self._pyfacade_sourcemap
        if sm is None:
            sm = self._pyfacade_sourcemap = SourceMap(self._pyfacade_text)
        line, col = sm.line_col(start)
        # Offset into the whole source. Only the chunk's first line shares a line
        # with the chunk's start, so only it picks up the start column.
        if line == 1:
            return self._pyfacade_base_line, self._pyfacade_base_col + col
        return self._pyfacade_base_line + line - 1, col

    def visitTerminal(self, token_type: int, text: str) -> None:
        """No-op terminal callback; override in a subclass to handle tokens."""

    def visitError(self, token_type: int, text: str) -> None:
        """No-op error callback; override in a subclass to handle error nodes."""

    @classmethod
    def _facade_base(cls) -> type:
        """Return the generated `<Grammar>EventListener` in this class's ancestry.

        That base (the class that directly subclasses `FacadeListener`) holds the
        no-op callback stubs [`drive`][antlr_pyfacade.drive] compares against to
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

    @classmethod
    def walk_parallel(
        cls,
        chunks: Iterable[str | Chunk],
        # TODO - more precise base classes or Protocols for lexer/parser
        lexer_cls: type,
        parser_cls: type,
        *,
        start_rule: int | str | None = None,
        max_workers: int | None = None,
        filtered: bool = True,
        factory: Callable[[], FacadeListener] | None = None,
    ) -> Iterator[FacadeListener]:
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
                [`Chunk`][antlr_pyfacade.Chunk] pins
                an explicit `offset` / `line` / `column` so callbacks
                report [`span`][antlr_pyfacade.FacadeListener.span] /
                [`line_col`][antlr_pyfacade.FacadeListener.line_col] against the
                whole source. Mix freely: a `Chunk` re-anchors the running position
                for the contiguous `str` chunks that follow it.
            lexer_cls: The stock ANTLR-generated `<Grammar>Lexer` class.
            parser_cls: The stock ANTLR-generated `<Grammar>Parser` class.
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
            [`syntax_errors`][antlr_pyfacade.FacadeListener.syntax_errors].
        """
        base = cls._facade_base()
        rule = cls._resolve_start_rule(base, start_rule)  # validate eagerly
        make = factory if factory is not None else cls
        workers = max_workers if max_workers is not None else (os.cpu_count() or 1)

        def run(chunk: Chunk) -> FacadeListener:
            parser_spec, lexer_spec = _specs_for_thread(lexer_cls, parser_cls)
            listener = make()
            drive(
                listener,
                base,
                parser_spec,
                lexer_spec,
                chunk.text,
                rule,
                filtered=filtered,
                origin=(chunk.offset, chunk.line, chunk.column),
            )
            return listener

        def resolved() -> Iterator[Chunk]:
            # A bare str continues contiguously from the previous chunk; a Chunk
            # pins its own position and re-anchors the str chunks that follow it.
            pos = (0, 1, 0)
            for item in chunks:
                if isinstance(item, Chunk):
                    chunk = item
                elif isinstance(item, str):
                    chunk = Chunk(item, *pos)
                else:
                    raise TypeError(
                        f"chunks must be str or Chunk, got {type(item).__name__}"
                    )
                yield chunk
                pos = _advance(chunk)

        def stream() -> Iterator[FacadeListener]:
            if workers <= 1:
                for chunk in resolved():
                    yield run(chunk)
                return
            # Bounded-window parallelism: keep ~`workers` parses in flight and yield
            # in input order, so peak memory tracks the window, not the chunk count.
            with ThreadPoolExecutor(max_workers=workers) as pool:
                pending: deque[Future[FacadeListener]] = deque()
                for chunk in resolved():
                    pending.append(pool.submit(run, chunk))
                    if len(pending) > workers:
                        yield pending.popleft().result()
                while pending:
                    yield pending.popleft().result()

        return stream()


# TODO - should this be a method of FacadeListener?
def drive(
    listener: FacadeListener,
    base_cls: type,  # TODO: more precise base class or Protocol
    # TODO: too many positional args
    parser_spec: _native.ParserSpec,
    lexer_spec: _native.LexerSpec,
    text: str,
    start_rule: int,
    *,
    filtered: bool = True,
    origin: tuple[int, int, int] = (0, 1, 0),
) -> None:
    """Run the native parse and dispatch overridden callbacks on `listener`.

    Args:
        listener: The listener instance whose overridden callbacks are dispatched.
        base_cls: The generated `<Grammar>EventListener` base; its no-op stubs are
            the reference for detecting which callbacks the subclass overrode.
        parser_spec: The native parser spec (see
            [`load_specs`][antlr_pyfacade.load_specs]).
        lexer_spec: The native lexer spec.
        text: The source to parse.
        start_rule: The index of the rule to start parsing at.
        filtered: When `True` (default), only overridden rules/tokens are emitted
            by C++; `False` forces a faithful full event stream regardless of
            overrides.
        origin: The `(offset, line, column)` of `text`'s first character, so
            callbacks report positions against the whole source. Defaults to the
            start of the source, `(0, 1, 0)`.
    """
    cls = type(listener)
    rule_names = base_cls.ruleNames

    enter: list[Callable | None] = [None] * len(rule_names)
    leave: list[Callable | None] = [None] * len(rule_names)
    rule_mask: list[int] = []
    for idx, name in enumerate(rule_names):
        cap = name[0].upper() + name[1:]
        e_over = getattr(cls, "enter" + cap) is not getattr(base_cls, "enter" + cap)
        x_over = getattr(cls, "exit" + cap) is not getattr(base_cls, "exit" + cap)
        if e_over:
            enter[idx] = getattr(listener, "enter" + cap)
        if x_over:
            leave[idx] = getattr(listener, "exit" + cap)
        if e_over or x_over:
            rule_mask.append(idx)

    visit = None
    token_mask: list[int] | None = []
    if cls.visitTerminal is not base_cls.visitTerminal:
        visit = listener.visitTerminal
        toks = getattr(cls, "TERMINAL_TOKENS", None)
        token_mask = list(toks) if toks is not None else None

    on_error = None
    if cls.visitError is not base_cls.visitError:
        on_error = listener.visitError

    # filtered=False forces a faithful full stream regardless of overrides.
    r_mask = rule_mask if filtered else None
    t_mask = token_mask if filtered else None
    raw, errors = _native.parse_events(
        parser_spec, lexer_spec, text, start_rule, r_mask, t_mask
    )
    listener.syntax_errors = errors

    # Source-location state read by FacadeListener.span / .line_col. Reset the
    # cached map so a reused listener re-derives it for this text.
    listener._pyfacade_text = text
    listener._pyfacade_sourcemap = None
    (
        listener._pyfacade_base_offset,
        listener._pyfacade_base_line,
        listener._pyfacade_base_col,
    ) = origin

    for kind, payload, start, stop in struct.iter_unpack(_REC, raw):
        if kind == EV_TERMINAL:
            if visit is not None:
                listener._pyfacade_start = start
                listener._pyfacade_stop = stop
                visit(payload, text[start : stop + 1])
        elif kind == EV_ENTER:
            cb = enter[payload]
            if cb is not None:
                listener._pyfacade_start = start
                listener._pyfacade_stop = stop
                cb()
        elif kind == EV_EXIT:
            cb = leave[payload]
            if cb is not None:
                listener._pyfacade_start = start
                listener._pyfacade_stop = stop
                cb()
        elif kind == EV_ERROR and on_error is not None:
            listener._pyfacade_start = start
            listener._pyfacade_stop = stop
            err_text = text[start : stop + 1] if 0 <= start <= stop else ""
            on_error(payload, err_text)
