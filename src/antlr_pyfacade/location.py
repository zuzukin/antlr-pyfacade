"""Turn source character offsets into (line, column) positions.

The event stream reports ``start``/``stop`` as character (codepoint) offsets
into the source string — the same indices that slice it directly. To report a
position to a user (e.g. on a parse error) build one :class:`SourceMap` over the
source and call :meth:`SourceMap.line_col`; the newline scan is done once and
each lookup is an O(log n) bisect.
"""

from __future__ import annotations

import bisect


class SourceMap:
    """Maps character offsets in a source string to ``(line, column)``.

    Line numbers are **1-based** and columns are **0-based**, matching ANTLR's
    own ``line:column`` error reporting and ``Token.getCharPositionInLine``.
    """

    __slots__ = ("_line_starts",)

    def __init__(self, text: str) -> None:
        # Offset of the first character of each line (line 1 starts at 0).
        starts = [0]
        i = text.find("\n")
        while i != -1:
            starts.append(i + 1)
            i = text.find("\n", i + 1)
        self._line_starts = starts

    def line_col(self, offset: int) -> tuple[int, int]:
        """Return ``(line, column)`` for a character ``offset``."""
        if offset < 0:
            raise ValueError(f"offset must be non-negative, got {offset}")
        line_idx = bisect.bisect_right(self._line_starts, offset) - 1
        return line_idx + 1, offset - self._line_starts[line_idx]
