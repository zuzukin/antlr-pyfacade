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

"""Native rule/token masks must drop exactly the unsubscribed events: a filtered
stream equals the unfiltered stream with non-kept rules/tokens removed."""

from __future__ import annotations

from generated.JSONLexer import JSONLexer
from generated.JSONParser import JSONParser

import antlr_pyfacade as ap

EV_ENTER, EV_EXIT, EV_TERMINAL, EV_ERROR = 0, 1, 2, 3
RULE_JSON = JSONParser.RULE_json
RULE_OBJ = JSONParser.RULE_obj
STRING = 10  # token type, see generated symbolicNames


def _rows(raw) -> list[tuple[int, int, int, int]]:
    mv = memoryview(raw).cast("i")
    return [tuple(mv[i * 4 : i * 4 + 4]) for i in range(len(mv) // 4)]


def test_mask_keeps_only_subscribed(json_text):
    pspec, lspec = ap.load_specs(JSONLexer, JSONParser)
    rule_mask = [RULE_OBJ]
    token_mask = [STRING]

    full = _rows(ap.parse_events(pspec, lspec, json_text, RULE_JSON)[0])
    filtered = _rows(
        ap.parse_events(pspec, lspec, json_text, RULE_JSON, rule_mask, token_mask)[0]
    )

    expected = [
        r
        for r in full
        if (r[0] in (EV_ENTER, EV_EXIT) and r[1] == RULE_OBJ)
        or (r[0] == EV_TERMINAL and r[1] == STRING)
    ]
    assert filtered == expected


def test_empty_mask_drops_everything(json_text):
    pspec, lspec = ap.load_specs(JSONLexer, JSONParser)
    raw, _ = ap.parse_events(pspec, lspec, json_text, RULE_JSON, [], [])
    assert _rows(raw) == []
