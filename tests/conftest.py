"""Make the bundled JSON example importable from the tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
# json's generated parser is imported as the `generated` package; the predicate
# example ships its own `generated` package too, so its modules are added as
# top-level (PredLexer/PredParser) to avoid a package-name collision.
for _dir in (
    _ROOT / "examples" / "json",
    _ROOT / "examples" / "predicate" / "generated",
):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))


# A spread of inputs: scalars, nesting, empties, multibyte UTF-8.
JSON_CASES = [
    "42",
    "true",
    "null",
    '"plain string"',
    "[]",
    "{}",
    '{"a": 1, "b": [2, 3], "c": {"d": null}}',
    '[1, 2.5, -3, 4e10, 5.0e-2, true, false, null, "x"]',
    '{"café": "naïve", "日本語": "テキスト", "emoji": "😀🚀"}',
    '{"nested": {"x": [[], {}], "y": [{"z": 1}]}}',
    '{"escapes": "line\\nbreak\\t\\"quoted\\""}',
]


@pytest.fixture(params=JSON_CASES, ids=[c[:24] for c in JSON_CASES])
def json_text(request) -> str:
    return request.param
