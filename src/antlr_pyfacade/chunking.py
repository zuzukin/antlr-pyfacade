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

"""Token-based chunkers for [walk_parallel][antlr_pyfacade.FacadeListener.walk_parallel].

Run the grammar's lexer once — the cheap stage, no parser and no ATN prediction —
and split the source into [Chunk][antlr_pyfacade.Chunk]s at chosen token
boundaries. This lets a large input be parsed in parallel without writing a regex
splitter, and each chunk carries its exact source position.

The chunkers ask the lexer for **only the boundary tokens they need** (via
`token_mask`), so little crosses into Python. A chunk then spans the source
between consecutive boundaries — its surrounding whitespace is trimmed and its
start `(offset, line, column)` is computed from a [SourceMap][antlr_pyfacade.SourceMap]
over the whole text. Whitespace-only regions are skipped. The chunkers yield
lazily and their output drops straight into `walk_parallel(chunks, ...)`.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, NamedTuple

from . import _native
from .facade_runtime import Chunk
from .location import SourceMap
from .specs import load_lexer_spec

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    # One token type, or several treated as equivalent.
    TokenTypes = int | Iterable[int]
    # An (open, close) bracket pair; either side may be one or several types.
    Pair = tuple[TokenTypes, TokenTypes]

# Record layout emitted by _native.lex: (type, channel, start, stop).
_TOK = struct.Struct("<4i")

#: The default token channel — what the lexer routes ordinary tokens to.
DEFAULT_CHANNEL = 0


class LexToken(NamedTuple):
    """One token from [lex][antlr_pyfacade.chunking.lex].

    `line` / `column` are not carried (they are cheap to derive from `start` with
    a [SourceMap][antlr_pyfacade.SourceMap]); keeping the record to four ints keeps
    a full-stream `lex()` light.
    """

    type: int
    channel: int
    start: int  # 0-based codepoint offset of the first character
    stop: int  # 0-based codepoint offset of the last character (inclusive)


def lex(
    text: str,
    lexer_cls: type,
    *,
    keep: Iterable[int] | None = None,
    cached: bool = True,
) -> list[LexToken]:
    """Tokenize `text` with the grammar's lexer (no parsing).

    Args:
        text: The source to tokenize.
        lexer_cls: The stock ANTLR-generated `<Grammar>Lexer` class.
        keep: Optional token types to return; the lexer drops every other token in
            C++ so only these cross into Python. `None` returns all tokens.
        cached: Reuse the cached lexer spec (see
            [load_lexer_spec][antlr_pyfacade.load_lexer_spec]).

    Returns:
        The kept tokens in source order (the EOF sentinel omitted). Tokens the
        lexer drops via `-> skip` do not appear; tokens routed to a non-default
        channel (`-> channel(...)`) appear with that `channel`. Lexer errors are
        recovered from and not reported here.
    """
    spec = load_lexer_spec(lexer_cls, cached=cached)
    mask = None if keep is None else list(keep)
    raw, _errors = _native.lex(spec, text, mask)
    return [LexToken(*rec) for rec in _TOK.iter_unpack(raw)]


def _emit(text: str, sm: SourceMap, start: int, stop: int) -> Chunk | None:
    """Build a positioned `Chunk` for `text[start:stop]`, trimming surrounding
    whitespace; return `None` if the region is whitespace-only."""
    seg = text[start:stop]
    stripped = seg.lstrip()
    body = stripped.rstrip()
    if not body:
        return None
    offset = start + (len(seg) - len(stripped))  # advance past leading whitespace
    line, column = sm.line_col(offset)
    return Chunk(body, offset, line, column)


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


def split_on_token(
    text: str,
    lexer_cls: type,
    token_types: TokenTypes,
    *,
    where: str = "before",
    channel: int | None = DEFAULT_CHANNEL,
) -> Iterator[Chunk]:
    """Split `text` into chunks at each delimiter token.

    Args:
        text: The source to split.
        lexer_cls: The stock ANTLR-generated `<Grammar>Lexer` class.
        token_types: The delimiter token type, or several types that all act as
            delimiters (e.g. `MyLexer.RECORD`, or `{MyLexer.RECORD, MyLexer.NOTE}`).
        where: `"before"` starts a new chunk at each delimiter (each chunk begins
            with one), so content before the first delimiter is its own leading
            chunk; `"after"` ends a chunk at each delimiter (each chunk ends with
            one), so content after the last delimiter is a trailing chunk.
        channel: Only tokens on this channel are split on (default: the default
            channel). Pass `None` to consider all channels.

    Yields:
        One [Chunk][antlr_pyfacade.Chunk] per region between delimiters, trimmed of
        surrounding whitespace and carrying its source position. Whitespace-only
        regions are skipped.
    """
    if where not in ("before", "after"):
        raise ValueError(f"where must be 'before' or 'after', got {where!r}")
    delims = _as_set(token_types)
    bounds = [
        t
        for t in lex(text, lexer_cls, keep=delims)
        if channel is None or t.channel == channel
    ]
    sm = SourceMap(text)
    n = len(text)
    if where == "before":
        first = bounds[0].start if bounds else n
        if first > 0:  # leading region, before the first delimiter
            chunk = _emit(text, sm, 0, first)
            if chunk is not None:
                yield chunk
        for i, b in enumerate(bounds):
            end = bounds[i + 1].start if i + 1 < len(bounds) else n
            chunk = _emit(text, sm, b.start, end)
            if chunk is not None:
                yield chunk
    else:  # after
        prev = 0
        for b in bounds:
            chunk = _emit(text, sm, prev, b.stop + 1)
            if chunk is not None:
                yield chunk
            prev = b.stop + 1
        if prev < n:  # trailing region, after the last delimiter
            chunk = _emit(text, sm, prev, n)
            if chunk is not None:
                yield chunk


def split_between_tokens(
    text: str,
    lexer_cls: type,
    pairs: Pair | list[Pair],
    *,
    nested: bool = False,
    channel: int | None = DEFAULT_CHANNEL,
) -> Iterator[Chunk]:
    """Yield a chunk for each region bounded by an opener/closer pair.

    Args:
        text: The source to split.
        lexer_cls: The stock ANTLR-generated `<Grammar>Lexer` class.
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

    Yields:
        One [Chunk][antlr_pyfacade.Chunk] per region — the text from the opener's
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
        for t in lex(text, lexer_cls, keep=keep)
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
                        chunk = _emit(text, sm, toks[start].start, toks[idx].stop + 1)
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
                chunk = _emit(text, sm, toks[idx].start, toks[j].stop + 1)
                if chunk is not None:
                    yield chunk
                idx = j + 1
            else:
                idx += 1
