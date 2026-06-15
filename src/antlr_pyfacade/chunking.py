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

"""Chunkers for [walk_parallel][antlr_pyfacade.FacadeListener.walk_parallel].

Split a whole source into [Chunk][antlr_pyfacade.Chunk]s, each carrying its exact
source position, so the pieces can be parsed in parallel. Two families:

- **Token-based** ([split_on_token][antlr_pyfacade.chunking.split_on_token],
  [split_between_tokens][antlr_pyfacade.chunking.split_between_tokens]): run the
  grammar's lexer once — the cheap stage, no parser/ATN prediction — and split at
  token boundaries. The lexer is asked for **only the boundary tokens** (via
  `token_mask`), so little crosses into Python, and splits never land inside a
  string or comment token.
- **Regex-based** ([split_on_pattern][antlr_pyfacade.chunking.split_on_pattern],
  [chunk_by_pattern][antlr_pyfacade.chunking.chunk_by_pattern]): split on a regular
  expression, no lexer involved. Roughly an order of magnitude faster at finding
  delimiters (a few times end to end), but not token-aware — a delimiter inside a
  string literal will still match.
- **Rule-based** ([chunk_by_rule][antlr_pyfacade.chunking.chunk_by_rule]): parse
  the input once — **entirely in C++**, no Python crossing — and emit each
  occurrence of a grammar rule as a chunk. Cuts on real grammar structure rather
  than a token/regex heuristic, at the cost of a structural parse; worth it when
  the per-chunk callback work dominates the re-parse `walk_parallel` does.

Pick token- or rule-based for correctness around strings/comments and real
structure, regex for raw speed when the delimiter can't appear in disguise. The
"Chunking: lexer vs regex" notes in `docs/performance.md` give measured numbers;
`scripts/bench_chunking.py` reproduces them.

A chunk spans the source between boundaries — surrounding whitespace trimmed, its
start `(offset, line, column)` from a [SourceMap][antlr_pyfacade.SourceMap], and
whitespace-only regions skipped. All chunkers yield lazily and feed straight into
`walk_parallel(chunks, ...)`.
"""

from __future__ import annotations

import re
import struct
from typing import TYPE_CHECKING, NamedTuple

from . import _native
from .facade_runtime import Chunk
from .location import SourceMap
from .specs import load_lexer_spec, load_specs

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    # One token type, or several treated as equivalent.
    TokenTypes = int | Iterable[int]
    # An (open, close) bracket pair; either side may be one or several types.
    Pair = tuple[TokenTypes, TokenTypes]
    # A grammar rule name or index, or several of them.
    RuleTypes = str | int | Iterable[str | int]

# Record layout emitted by _native.lex: (type, channel, start, stop).
_TOK = struct.Struct("<4i")
# Record layout emitted by _native.rule_spans: (rule_index, start, stop).
_RULE = struct.Struct("<3i")

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

    Token-aware: because it runs the grammar's lexer, a delimiter that appears
    inside a string or comment token never causes a split. The price is lexing the
    whole input — roughly an order of magnitude slower than the regex
    [split_on_pattern][antlr_pyfacade.chunking.split_on_pattern] at finding the
    delimiters (~4x end to end), though still negligible next to the parse it
    feeds. See the "Chunking: lexer vs regex" notes in `docs/performance.md`.

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

    Token-aware, like [split_on_token][antlr_pyfacade.chunking.split_on_token]: it
    lexes the whole input, so a bracket inside a string or comment is ignored, at
    the cost of being slower than a plain regex over the text (see the "Chunking:
    lexer vs regex" notes in `docs/performance.md`).

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


def split_on_pattern(
    text: str,
    pattern: str | re.Pattern[str],
    *,
    where: str = "before",
    flags: int | re.RegexFlag = 0,
) -> Iterator[Chunk]:
    """Split `text` into chunks at each match of a delimiter regex.

    The regex analogue of [split_on_token][antlr_pyfacade.chunking.split_on_token].
    No lexer is involved, so it is much faster — roughly an order of magnitude at
    finding delimiters and a few times end to end (the per-chunk Python work is
    shared) — but **not token-aware**: a match inside a string or comment still
    delimits. Prefer it when the delimiter can't appear in disguise; otherwise use
    the token-based splitter. See the "Chunking: lexer vs regex" notes in
    `docs/performance.md`.

    Args:
        text: The source to split.
        pattern: The delimiter regular expression (a `str` or compiled pattern).
        where: `"before"` starts each chunk at a match; `"after"` ends each chunk
            at a match (see split_on_token).
        flags: `re` flags, used only when `pattern` is a `str`.

    Yields:
        One [Chunk][antlr_pyfacade.Chunk] per region between matches, trimmed of
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
            chunk = _emit(text, sm, 0, first)
            if chunk is not None:
                yield chunk
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else n
            chunk = _emit(text, sm, m.start(), end)
            if chunk is not None:
                yield chunk
    else:  # after
        prev = 0
        for m in matches:
            chunk = _emit(text, sm, prev, m.end())
            if chunk is not None:
                yield chunk
            prev = m.end()
        if prev < n:  # trailing region, after the last match
            chunk = _emit(text, sm, prev, n)
            if chunk is not None:
                yield chunk


def chunk_by_pattern(
    text: str,
    pattern: str | re.Pattern[str],
    *,
    flags: int | re.RegexFlag = 0,
) -> Iterator[Chunk]:
    """Yield one chunk per non-overlapping match of `pattern`.

    Here the pattern matches a whole record (rather than a delimiter), so each
    match *is* a chunk and the text between matches is dropped. No lexer is
    involved — fast, but not token-aware; see
    [split_on_pattern][antlr_pyfacade.chunking.split_on_pattern] and the "Chunking:
    lexer vs regex" notes in `docs/performance.md` for the speed/correctness
    trade-off.

    Args:
        text: The source to split.
        pattern: A regular expression matching one record (a `str` or compiled
            pattern).
        flags: `re` flags, used only when `pattern` is a `str`.

    Yields:
        One [Chunk][antlr_pyfacade.Chunk] per match, trimmed of surrounding
        whitespace; empty matches are skipped.
    """
    rx = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
    sm = SourceMap(text)
    for m in rx.finditer(text):
        chunk = _emit(text, sm, m.start(), m.end())
        if chunk is not None:
            yield chunk


def _rule_index(parser_cls: type, rule: str | int) -> int:
    """Resolve a rule name or index to a rule index for `parser_cls`."""
    if isinstance(rule, int):
        return rule
    names = list(parser_cls.ruleNames)
    try:
        return names.index(rule)
    except ValueError:
        raise ValueError(f"unknown rule {rule!r}; known rules: {names}") from None


def chunk_by_rule(
    text: str,
    lexer_cls: type,
    parser_cls: type,
    rule: RuleTypes,
    *,
    start_rule: str | int | None = None,
    outermost: bool = True,
    cached: bool = True,
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
        lexer_cls: The stock ANTLR-generated `<Grammar>Lexer` class.
        parser_cls: The stock ANTLR-generated `<Grammar>Parser` class.
        rule: The rule to chunk by — a rule name or index, or several of them
            (e.g. `"function"`, or `{"function", "class"}`).
        start_rule: The rule the whole input parses as — a name, an index, or
            `None` for the grammar's start rule (index 0).
        outermost: When `True` (default), only top-level occurrences are emitted;
            a matched rule nested inside another match is skipped. `False` emits
            every occurrence (which would overlap).
        cached: Reuse the cached specs (see
            [load_specs][antlr_pyfacade.load_specs]).

    Yields:
        One [Chunk][antlr_pyfacade.Chunk] per matched rule occurrence, in source
        order, trimmed of surrounding whitespace and carrying its position. An
        empty occurrence (a rule that consumed no token) is skipped.
    """
    parser_spec, lexer_spec = load_specs(lexer_cls, parser_cls, cached=cached)
    if isinstance(rule, (int, str)):
        rule_mask = [_rule_index(parser_cls, rule)]
    else:
        rule_mask = [_rule_index(parser_cls, r) for r in rule]
    start_idx = 0 if start_rule is None else _rule_index(parser_cls, start_rule)

    raw, _errors = _native.rule_spans(
        parser_spec, lexer_spec, text, start_idx, rule_mask, outermost
    )
    sm = SourceMap(text)
    for _ridx, start, stop in _RULE.iter_unpack(raw):
        if start < 0:  # empty rule occurrence — no source span
            continue
        chunk = _emit(text, sm, start, stop + 1)
        if chunk is not None:
            yield chunk
