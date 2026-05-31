"""Native rule/token masks must drop exactly the unsubscribed events: a filtered
stream equals the unfiltered stream with non-kept rules/tokens removed."""

from __future__ import annotations

import antlr_pyfacade as ap
from generated.JSONLexer import JSONLexer
from generated.JSONParser import JSONParser

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

    full = _rows(ap.parse_events(pspec, lspec, json_text, RULE_JSON))
    filtered = _rows(
        ap.parse_events(pspec, lspec, json_text, RULE_JSON, rule_mask, token_mask)
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
    raw = ap.parse_events(pspec, lspec, json_text, RULE_JSON, [], [])
    assert _rows(raw) == []
