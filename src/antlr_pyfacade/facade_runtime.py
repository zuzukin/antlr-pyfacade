"""Driver for generated grammar-specific event listeners.

A generated ``<Grammar>EventListener`` subclass declares named callbacks
(``enter<Rule>`` / ``exit<Rule>`` / ``visitTerminal`` / ``visitError``) just
like the stock ANTLR listener. ``drive`` runs the bulk native event stream and
dispatches those callbacks, instead of building a Python parse tree and walking
it.

It derives the native rule/token masks from *which* callbacks the subclass
actually overrides, so only the node kinds the consumer cares about cross into
Python (the unsubscribed rest are dropped C++-side before the buffer is built).
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from . import _native
from .location import SourceMap

if TYPE_CHECKING:
    from collections.abc import Callable

EV_ENTER, EV_EXIT, EV_TERMINAL, EV_ERROR = 0, 1, 2, 3
_REC = "<4i"


class FacadeListener:
    """Base for generated ``<Grammar>EventListener`` classes.

    Provides source-location access for the *current* event: while a callback
    is running, :meth:`span` returns its ``(start, stop)`` character offsets and
    :meth:`line_col` the 1-based line / 0-based column of its start. ``drive``
    populates this state per dispatched callback; outside a callback it reflects
    the most recent one.
    """

    _pyfacade_text: str = ""
    _pyfacade_start: int = -1
    _pyfacade_stop: int = -1
    _pyfacade_sourcemap: SourceMap | None = None

    def span(self) -> tuple[int, int]:
        """``(start, stop)`` character offsets of the current event."""
        return self._pyfacade_start, self._pyfacade_stop

    def line_col(self) -> tuple[int, int] | None:
        """``(line, column)`` of the current event's start, or ``None``.

        Returns ``None`` when the current event has no source span (e.g. an
        empty rule). The :class:`SourceMap` is built once per walk on first use.
        """
        start = self._pyfacade_start
        if start < 0:
            return None
        sm = self._pyfacade_sourcemap
        if sm is None:
            sm = self._pyfacade_sourcemap = SourceMap(self._pyfacade_text)
        return sm.line_col(start)


def drive(
    listener,
    base_cls,
    parser_spec,
    lexer_spec,
    text: str,
    start_rule: int,
    *,
    filtered: bool = True,
) -> None:
    """Run the native parse and dispatch overridden callbacks on ``listener``.

    ``base_cls`` is the generated ``<Grammar>EventListener`` base (its no-op
    stubs are the reference for detecting which callbacks the subclass
    overrode). When ``filtered`` is True (default), only overridden
    rules/tokens are emitted by C++; ``filtered=False`` forces a faithful full
    event stream regardless of overrides.
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
    raw = _native.parse_events(
        parser_spec, lexer_spec, text, start_rule, r_mask, t_mask
    )

    # Source-location state read by FacadeListener.span / .line_col. Reset the
    # cached map so a reused listener re-derives it for this text.
    listener._pyfacade_text = text
    listener._pyfacade_sourcemap = None

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
        elif kind == EV_ERROR:
            if on_error is not None:
                listener._pyfacade_start = start
                listener._pyfacade_stop = stop
                err_text = text[start : stop + 1] if 0 <= start <= stop else ""
                on_error(payload, err_text)
