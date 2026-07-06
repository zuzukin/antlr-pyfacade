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

import pytest
from json_listener import JsonEventListener
from to_python import JsonValueBuilder


def _parse(text: str, *, filtered: bool):
    builder = JsonValueBuilder()
    builder.walk(text, filtered=filtered)
    return builder.result


def test_facade_roundtrips_filtered(json_text):
    assert _parse(json_text, filtered=True) == json.loads(json_text)


def test_facade_roundtrips_unfiltered(json_text):
    assert _parse(json_text, filtered=False) == json.loads(json_text)


def test_filtered_and_unfiltered_agree(json_text):
    assert _parse(json_text, filtered=True) == _parse(json_text, filtered=False)


def test_scope_text_and_name_helpers():
    """depth / rule_stack / current_rule / text track the SUBSCRIBED rules, and the
    name lookups resolve rule and token names."""
    doc = '{"a": [1, [2]], "b": 3}'

    class Listener(JsonEventListener):
        def __init__(self) -> None:
            self.arr_exits: list[tuple[int, str]] = []
            self.obj_exits: list[tuple[int, tuple[str, ...], str]] = []
            self.num_ctx: list[tuple[str | None, int]] = []

        def enterObj(self) -> None: ...
        def enterArr(self) -> None: ...

        def exitArr(self) -> None:
            self.arr_exits.append((self.depth(), self.text()))

        def exitObj(self) -> None:
            self.obj_exits.append((self.depth(), self.rule_stack(), self.text()))

        def visitTerminal(self, token_type: int, text: str) -> None:
            if token_type == self.NUMBER:
                self.num_ctx.append((self.current_rule(), self.depth()))

    listener = Listener().walk(doc)

    # Only obj/arr are subscribed, so depth/rule_stack count just those.
    assert listener.arr_exits == [(3, "[2]"), (2, "[1, [2]]")]
    assert listener.obj_exits == [(1, ("obj",), doc)]
    # current_rule in a terminal callback is the innermost open (subscribed) rule.
    assert listener.num_ctx == [("arr", 2), ("arr", 3), ("obj", 1)]
    # The stack unwinds completely.
    assert listener.depth() == 0

    # Name lookups (classmethods).
    assert Listener.rule_name(0) == "json"
    assert Listener.token_name(Listener.NUMBER) == "NUMBER"
    assert Listener.token_name(1) == "'{'"  # anonymous literal
    assert Listener.token_name(9999) == "9999"  # unknown type -> its number
    # rule_name is strict: out-of-range (including negative) raises IndexError.
    with pytest.raises(IndexError):
        Listener.rule_name(9999)
    with pytest.raises(IndexError):
        Listener.rule_name(-1)


def test_every_rule_hooks_track_full_depth():
    """Overriding enterEveryRule/exitEveryRule subscribes to ALL rules, so depth
    reflects the full parse tree and the hooks stay balanced."""
    doc = "[1, [2, [3]]]"

    class Listener(JsonEventListener):
        def __init__(self) -> None:
            self.entered: list[str] = []
            self.max_depth = 0
            self.balanced = True

        def enterEveryRule(self, rule_index: int) -> None:
            self.entered.append(self.rule_name(rule_index))
            self.max_depth = max(self.max_depth, self.depth())

        def exitEveryRule(self, rule_index: int) -> None:
            # current_rule() is still this rule (popped after the callback).
            if self.current_rule() != self.rule_name(rule_index):
                self.balanced = False

    listener = Listener().walk(doc)

    # All rule kinds in this doc were seen (json/value/arr), proving all-rule
    # subscription even though no specific enter<Rule> was overridden.
    assert set(listener.entered) == {"json", "value", "arr"}
    # json>value>arr>value>arr>value>arr>value at the deepest `3`.
    assert listener.max_depth == 8
    assert listener.balanced
    assert listener.depth() == 0
