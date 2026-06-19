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
Turn source character offsets into `(line, column)` positions.

The event stream reports `start`/`stop` as character (codepoint) offsets into the
source string — the same indices that slice it directly. To report a position to a
user (e.g. on a parse error) build one [SourceMap][antlrope.SourceMap] over
the source and call [SourceMap.line_col][antlrope.SourceMap.line_col]; the
newline scan is done once and each lookup is an O(log n) bisect.
"""

from __future__ import annotations

import bisect


class SourceMap:
    """Maps character offsets in a source string to `(line, column)`.

    Line numbers are **1-based** and columns are **0-based**, matching ANTLR's
    own `line:column` error reporting and `Token.getCharPositionInLine`.
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
        """Return the `(line, column)` for a character `offset`.

        Args:
            offset: A non-negative character (codepoint) offset into the source.

        Returns:
            The 1-based line and 0-based column of `offset`.

        Raises:
            ValueError: If `offset` is negative.
        """
        if offset < 0:
            raise ValueError(f"offset must be non-negative, got {offset}")
        line_idx = bisect.bisect_right(self._line_starts, offset) - 1
        return line_idx + 1, offset - self._line_starts[line_idx]

    def offset(self, line: int, column: int = 0) -> int:
        """Return the character offset for a 1-based `line` and 0-based `column`.

        The inverse of [line_col][antlrope.SourceMap.line_col]:
        `offset(*line_col(o)) == o` for any valid offset `o`.

        Args:
            line: A 1-based line number.
            column: A 0-based column within the line. Added to the line's start
                offset without bounds-checking against the line length, so a
                `column` past the end of the line yields an offset into a later
                line.

        Returns:
            The character (codepoint) offset of `line`:`column`.

        Raises:
            ValueError: If `line` is outside `1..number-of-lines`.
        """
        if not 1 <= line <= len(self._line_starts):
            raise ValueError(f"line must be in 1..{len(self._line_starts)}, got {line}")
        return self._line_starts[line - 1] + column
