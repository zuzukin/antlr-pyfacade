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

import codecs
import os
import re
import struct
from typing import TYPE_CHECKING, NamedTuple

from . import _native
from .base import Chunk
from .location import SourceMap
from .specs import load_lexer_spec, load_specs

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    # A streaming text source: a filesystem path, an open text file object, or any
    # iterable of str pieces (a file object iterates as lines; a generator works).
    TextSource = str | os.PathLike[str] | Iterable[str]
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
) -> Iterator[LexToken]:
    """Tokenize `text` with the grammar's lexer (no parsing).

    Lazy: the work runs as the result is iterated. Wrap in `list(...)` for random
    access. The native lexer streams tokens rather than buffering the whole stream.

    Args:
        text: The source to tokenize.
        lexer_cls: The stock ANTLR-generated `<Grammar>Lexer` class.
        keep: Optional token types to return; the lexer drops every other token in
            C++ so only these cross into Python. `None` returns all tokens.
        cached: Reuse the cached lexer spec (see
            [load_lexer_spec][antlr_pyfacade.load_lexer_spec]).

    Yields:
        The kept tokens in source order (the EOF sentinel omitted). Tokens the
        lexer drops via `-> skip` do not appear; tokens routed to a non-default
        channel (`-> channel(...)`) appear with that `channel`. Lexer errors are
        recovered from and not reported here.
    """
    spec = load_lexer_spec(lexer_cls, cached=cached)
    mask = None if keep is None else list(keep)
    raw, _errors = _native.lex(spec, text, mask)
    for rec in _TOK.iter_unpack(raw):
        yield LexToken(*rec)


def _emit(
    text: str, sm: SourceMap, start: int, stop: int, sourcename: str | None = None
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
    sourcename: str | None = None,
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
        sourcename: Optional source name (e.g. a filename) recorded on each
            [Chunk][antlr_pyfacade.Chunk], surfaced during a walk as
            [sourcename][antlr_pyfacade.FacadeListener.sourcename].

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
            chunk = _emit(text, sm, 0, first, sourcename)
            if chunk is not None:
                yield chunk
        for i, b in enumerate(bounds):
            end = bounds[i + 1].start if i + 1 < len(bounds) else n
            chunk = _emit(text, sm, b.start, end, sourcename)
            if chunk is not None:
                yield chunk
    else:  # after
        prev = 0
        for b in bounds:
            chunk = _emit(text, sm, prev, b.stop + 1, sourcename)
            if chunk is not None:
                yield chunk
            prev = b.stop + 1
        if prev < n:  # trailing region, after the last delimiter
            chunk = _emit(text, sm, prev, n, sourcename)
            if chunk is not None:
                yield chunk


def stream_on_token(
    path: str | os.PathLike[str],
    lexer_cls: type,
    token_types: TokenTypes,
    *,
    where: str = "before",
    encoding: str = "utf-8",
    channel: int | None = DEFAULT_CHANNEL,
    sourcename: str | None = None,
    batch: int = 256,
    cached: bool = True,
    _block_bytes: int = 0,
) -> Iterator[Chunk]:
    """Stream chunks from a file at each delimiter token, without holding it all.

    The streaming counterpart of [split_on_token][antlr_pyfacade.chunking.split_on_token]:
    instead of taking the whole source as a `str`, it opens `path` in C++ and lexes
    it incrementally over a sliding window, slicing out and freeing each chunk as it
    goes — so peak memory is roughly one chunk rather than the whole file. The
    yielded [Chunk][antlr_pyfacade.Chunk]s drop straight into
    [walk_parallel][antlr_pyfacade.FacadeListener.walk_parallel], which pulls them
    lazily, keeping the whole pipeline bounded.

    Args:
        path: Filesystem path to the source (opened by the native layer as UTF-8).
        lexer_cls: The stock ANTLR-generated `<Grammar>Lexer` class.
        token_types: The delimiter token type, or several types that all act as
            delimiters (see [split_on_token][antlr_pyfacade.chunking.split_on_token]).
        where: `"before"` starts a new chunk at each delimiter; `"after"` ends a
            chunk at each delimiter (see split_on_token).
        encoding: The source encoding. Only UTF-8 is supported today (Python codec
            aliases such as `"utf8"` are accepted); the keyword is reserved so other
            encodings can be added later. For a non-UTF-8 source now, decode it in
            Python (`Path(p).read_text(encoding=...)`) and use the in-memory
            [split_on_token][antlr_pyfacade.chunking.split_on_token].
        channel: Only tokens on this channel are split on (default: the default
            channel). Pass `None` to consider all channels.
        sourcename: Source name recorded on each [Chunk][antlr_pyfacade.Chunk] (and
            surfaced as [sourcename][antlr_pyfacade.FacadeListener.sourcename] during
            a walk). Defaults to `str(path)`.
        batch: How many chunk records to pull from C++ per call — a throughput knob,
            not observable in the output.
        cached: Reuse the cached lexer spec (see
            [load_lexer_spec][antlr_pyfacade.load_lexer_spec]).

    Yields:
        One [Chunk][antlr_pyfacade.Chunk] per region between delimiters, trimmed of
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
    if sourcename is None:
        sourcename = src_path
    spec = load_lexer_spec(lexer_cls, cached=cached)
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


def split_between_tokens(
    text: str,
    lexer_cls: type,
    pairs: Pair | list[Pair],
    *,
    nested: bool = False,
    channel: int | None = DEFAULT_CHANNEL,
    sourcename: str | None = None,
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
        sourcename: Optional source name (e.g. a filename) recorded on each
            [Chunk][antlr_pyfacade.Chunk], surfaced during a walk as
            [sourcename][antlr_pyfacade.FacadeListener.sourcename].

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
                        chunk = _emit(
                            text, sm, toks[start].start, toks[idx].stop + 1, sourcename
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
                chunk = _emit(text, sm, toks[idx].start, toks[j].stop + 1, sourcename)
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
    sourcename: str | None = None,
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
        sourcename: Optional source name (e.g. a filename) recorded on each
            [Chunk][antlr_pyfacade.Chunk], surfaced during a walk as
            [sourcename][antlr_pyfacade.FacadeListener.sourcename].

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
            chunk = _emit(text, sm, 0, first, sourcename)
            if chunk is not None:
                yield chunk
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else n
            chunk = _emit(text, sm, m.start(), end, sourcename)
            if chunk is not None:
                yield chunk
    else:  # after
        prev = 0
        for m in matches:
            chunk = _emit(text, sm, prev, m.end(), sourcename)
            if chunk is not None:
                yield chunk
            prev = m.end()
        if prev < n:  # trailing region, after the last match
            chunk = _emit(text, sm, prev, n, sourcename)
            if chunk is not None:
                yield chunk


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


def _split_stream(
    increments: Iterator[str], rx: re.Pattern[str], where: str, sourcename: str | None
) -> Iterator[Chunk]:
    """Split the concatenation of `increments` at each `rx` match, streaming.

    Holds only the current open chunk plus one read-ahead increment: it searches a
    growing buffer for the next delimiter, and only commits a match once a
    character past it has been read (or EOF) — so a match is never truncated by a
    read boundary. Reproduces `split_on_pattern` over the same text for delimiters
    that fit within the buffer.
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


def stream_on_pattern(
    source: TextSource,
    pattern: str | re.Pattern[str],
    *,
    where: str = "before",
    flags: int | re.RegexFlag = 0,
    window_chars: int | None = 65536,
    window_lines: int | None = None,
    encoding: str = "utf-8",
    sourcename: str | None = None,
) -> Iterator[Chunk]:
    """Stream chunks from a text source at each delimiter regex match.

    The streaming counterpart of
    [split_on_pattern][antlr_pyfacade.chunking.split_on_pattern]: it reads `source`
    incrementally and yields positioned [Chunk][antlr_pyfacade.Chunk]s without
    holding the whole input, so paired with
    [walk_parallel][antlr_pyfacade.FacadeListener.walk_parallel] the pipeline stays
    bounded. Because the regex is Python's, encoding is handled on the Python side
    (unlike the lexer-based
    [stream_on_token][antlr_pyfacade.chunking.stream_on_token], which reads UTF-8 in
    C++) — any encoding a text file supports works.

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
        sourcename: Source name recorded on each [Chunk][antlr_pyfacade.Chunk] (and
            surfaced as [sourcename][antlr_pyfacade.FacadeListener.sourcename] during
            a walk). Defaults to the path when `source` is a path, else `None` — pass
            it for a stream or iterable that has no path.

    Yields:
        One [Chunk][antlr_pyfacade.Chunk] per region between matches, trimmed of
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
        if sourcename is None:
            sourcename = fspath
        opened = open(fspath, encoding=encoding)  # noqa: SIM115
        increments = _read_increments(opened, window_chars, window_lines)
    elif hasattr(source, "read"):
        increments = _read_increments(source, window_chars, window_lines)
    else:
        increments = iter(source)
    try:
        yield from _split_stream(increments, rx, where, sourcename)
    finally:
        if opened is not None:
            opened.close()


def chunk_by_pattern(
    text: str,
    pattern: str | re.Pattern[str],
    *,
    flags: int | re.RegexFlag = 0,
    sourcename: str | None = None,
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
        sourcename: Optional source name (e.g. a filename) recorded on each
            [Chunk][antlr_pyfacade.Chunk], surfaced during a walk as
            [sourcename][antlr_pyfacade.FacadeListener.sourcename].

    Yields:
        One [Chunk][antlr_pyfacade.Chunk] per match, trimmed of surrounding
        whitespace; empty matches are skipped.
    """
    rx = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
    sm = SourceMap(text)
    for m in rx.finditer(text):
        chunk = _emit(text, sm, m.start(), m.end(), sourcename)
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
    sourcename: str | None = None,
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
        sourcename: Optional source name (e.g. a filename) recorded on each
            [Chunk][antlr_pyfacade.Chunk], surfaced during a walk as
            [sourcename][antlr_pyfacade.FacadeListener.sourcename].

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
        chunk = _emit(text, sm, start, stop + 1, sourcename)
        if chunk is not None:
            yield chunk


def stream_by_rule(
    path: str | os.PathLike[str],
    lexer_cls: type,
    parser_cls: type,
    rule: RuleTypes,
    *,
    sourcename: str | None = None,
    encoding: str = "utf-8",
    batch: int = 256,
    cached: bool = True,
    _block_bytes: int = 0,
) -> Iterator[Chunk]:
    """Stream chunks from a file that is a sequence of a grammar `rule`.

    The streaming counterpart of [chunk_by_rule][antlr_pyfacade.chunking.chunk_by_rule],
    for input that is a top-level **sequence of records** — each record an occurrence
    of `rule` (or one of several rules). It parses one record at a time over a
    bounded-memory pipeline (the native layer opens the file and runs lexer → parser
    over a sliding window), yielding each as a positioned [Chunk][antlr_pyfacade.Chunk]
    without holding the whole token stream or parse tree. The chunks feed
    [walk_parallel][antlr_pyfacade.FacadeListener.walk_parallel] like any other.

    Unlike `chunk_by_rule` — which parses the whole input and finds the rule *anywhere*
    in the tree — this is the bounded-memory "file of records" form. Records must be
    **directly adjacent**: only lexer-skipped tokens (whitespace, comments) may sit
    between them. With several candidate `rule`s, the next token chooses which to parse
    (via each rule's start-token set), so the candidates should have **disjoint leading
    tokens** (e.g. `class` vs `def`); on overlap the first listed wins. An on-channel
    separator between records (e.g. a comma) is not supported — use `chunk_by_rule` or
    [stream_on_token][antlr_pyfacade.chunking.stream_on_token] there.

    Args:
        path: Filesystem path to the source (opened by the native layer as UTF-8).
        lexer_cls: The stock ANTLR-generated `<Grammar>Lexer` class.
        parser_cls: The stock ANTLR-generated `<Grammar>Parser` class.
        rule: The record rule — a rule name or index, or several of them (a set of
            top-level record types, e.g. `{"classdef", "funcdef"}`).
        sourcename: Source name recorded on each [Chunk][antlr_pyfacade.Chunk] (and
            surfaced as [sourcename][antlr_pyfacade.FacadeListener.sourcename] during a
            walk). Defaults to `str(path)`.
        encoding: The source encoding. Only UTF-8 is supported today (Python codec
            aliases are accepted); the keyword is reserved for future encodings.
        batch: How many records to pull from C++ per call — a throughput knob.
        cached: Reuse the cached specs (see [load_specs][antlr_pyfacade.load_specs]).

    Yields:
        One [Chunk][antlr_pyfacade.Chunk] per record, in source order, carrying its
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
        rule_indices = [_rule_index(parser_cls, rule)]
    else:
        rule_indices = [_rule_index(parser_cls, r) for r in rule]
    src_path = os.fspath(path)
    if sourcename is None:
        sourcename = src_path
    parser_spec, lexer_spec = load_specs(lexer_cls, parser_cls, cached=cached)
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
