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

"""Facade dispatch correctness: the generated JsonEventListener subclass driven
by the bulk event stream must rebuild the document, filtered and unfiltered, with
correct token text (including multibyte UTF-8, which exercises codepoint-indexed
slicing)."""

from __future__ import annotations

import json

from generated.JSONLexer import JSONLexer
from generated.JSONParser import JSONParser
from to_python import JsonValueBuilder


def _parse(text: str, *, filtered: bool):
    builder = JsonValueBuilder()
    builder.walk(text, JSONLexer, JSONParser, filtered=filtered)
    return builder.result


def test_facade_roundtrips_filtered(json_text):
    assert _parse(json_text, filtered=True) == json.loads(json_text)


def test_facade_roundtrips_unfiltered(json_text):
    assert _parse(json_text, filtered=False) == json.loads(json_text)


def test_filtered_and_unfiltered_agree(json_text):
    assert _parse(json_text, filtered=True) == _parse(json_text, filtered=False)
