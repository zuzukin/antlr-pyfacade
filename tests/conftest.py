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
