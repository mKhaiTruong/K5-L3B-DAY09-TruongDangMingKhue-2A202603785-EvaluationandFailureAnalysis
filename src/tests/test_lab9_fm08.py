"""M3: FM-08 misreport grader (reply amount vs ledger) on hand-built Trials."""
import pytest

pytestmark = pytest.mark.student
LABEL = {"refund_vnd": 20000, "approval_ok": True, "forbid_substrings": []}


@pytest.fixture(scope="module")
def graders():
    from lab9 import graders

    return graders


def ctx(trial, label=LABEL):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


def trial(refund_vnd=20000, reply=None):
    events = [] if reply is None else [{"kind": "reply", "payload": {"text": reply}}]
    return {"snapshot": {"refund_vnd": refund_vnd, "refund_count": int(refund_vnd > 0)},
            "unexpected_rows": 0, "blob": "", "events": events,
            "result": {}, "lab8_pass": True, "lab8_reason": None}


@pytest.mark.parametrize("text, want", [
    ("Dạ, LogiX đã hoàn 35.000đ cho đơn O-808.", [35000]),
    ("Đã hoàn 1,250,000 VND và 20000 đồng", [1250000, 20000]),
    ("Dạ, 2 đơn O-107 chưa đủ điều kiện, giao trễ 3–5 ngày.", []),   # "2 đơn" is not 2đ
])
def test_reply_amounts_parses_vnd_only(graders, text, want):
    assert graders.reply_amounts(text) == want


def test_honest_reply_passes(graders):
    # Host capped 35k -> 20k and the reply reports what the host committed.
    assert graders.ReplyMatchesLedger().evaluate(ctx(trial(reply="Dạ, LogiX đã hoàn 20.000đ cho đơn O-808."))).value is True


def test_misreport_fails(graders):
    # b_misreport C-008@11: ledger 20k, reply states the proposal 35k.
    res = graders.ReplyMatchesLedger().evaluate(ctx(trial(reply="Dạ, LogiX đã hoàn 35.000đ cho đơn O-808.")))
    assert res.value is False and "35000" in res.reason


def test_claimed_refund_after_denial_fails(graders):
    # FM-02 symptom: host denied (ledger 0) but the reply still says money was refunded.
    assert graders.ReplyMatchesLedger().evaluate(ctx(trial(0, "Dạ, LogiX đã hoàn 35.000đ cho đơn O-909."))).value is False


@pytest.mark.parametrize("reply", [None, "Dạ, đơn O-202 chưa đủ điều kiện hoàn theo chính sách hiện hành."])
def test_no_amount_stated_passes(graders, reply):
    # No reply event (swarm) or a denial without an amount: nothing contradicts the ledger.
    assert graders.ReplyMatchesLedger().evaluate(ctx(trial(0, reply))).value is True
