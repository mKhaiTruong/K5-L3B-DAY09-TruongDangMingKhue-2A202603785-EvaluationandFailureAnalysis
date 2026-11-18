"""M7 unit tests for gate.integrity_check on tiny synthetic reports (no agent run)."""
import copy

import pytest

from lab9.gate import integrity_check

pytestmark = pytest.mark.student


def _report():
    rows = [{"item_id": f"I{i}", "seed": s, "slices": ["money_movement"] if i == 0 else [], "pass_rate": True}
            for i in range(2) for s in (1, 2)]
    return {"manifest": {"items": 2, "seeds": [1, 2]}, "rows": rows, "evaluator_failures": [],
            "metrics": {"pass_rate": 1.0}}


def _spec():
    return {"eval_set_version": "v1",
            "metrics": [{"id": "pass_rate", "blocking": True, "threshold": {"min": 0.9}}],
            "slices": [{"name": "money_movement", "metric": "pass_rate", "min": 0.95, "blocking": True}]}


def test_clean_report_has_no_problems():
    assert integrity_check(_report(), _report(), _spec(), _spec()) == []


def test_nan_metric_is_caught():
    pr = _report()
    pr["metrics"]["pass_rate"] = float("nan")
    assert integrity_check(pr, _report(), _spec())


def test_dropped_and_duplicated_rows_are_caught():
    dropped = _report()
    dropped["rows"].pop()
    assert integrity_check(dropped, _report(), _spec())

    dup = _report()
    dup["rows"][-1] = copy.deepcopy(dup["rows"][0])
    assert integrity_check(dup, _report(), _spec())


def test_cherry_picked_seed_is_caught():
    pr = _report()
    pr["rows"][-1]["seed"] = 3
    assert integrity_check(pr, _report(), _spec())


def test_crashed_grader_is_caught():
    none_row = _report()
    none_row["rows"][0]["pass_rate"] = None
    assert integrity_check(none_row, _report(), _spec())

    failures = _report()
    failures["evaluator_failures"] = ["I0@1:Grader:boom"]
    assert integrity_check(failures, _report(), _spec())


def test_slice_relabel_is_caught():
    pr = _report()
    pr["rows"][0]["slices"] = []
    assert integrity_check(pr, _report(), _spec())


@pytest.mark.parametrize("mutate", [
    lambda s: s["metrics"][0]["threshold"].update(min=0.5),
    lambda s: s["metrics"][0].update(blocking=False),
    lambda s: s["metrics"].clear(),
    lambda s: s["slices"].clear(),
    lambda s: s["slices"][0].update(min=0.5),
])
def test_loosened_spec_is_caught_by_ratchet(mutate):
    loose = _spec()
    mutate(loose)
    assert integrity_check(_report(), _report(), loose, _spec())


def test_ratchet_allows_stricter_spec_and_new_eval_set_version():
    strict = _spec()
    strict["metrics"][0]["threshold"]["min"] = 0.95
    assert integrity_check(_report(), _report(), strict, _spec()) == []

    new_version = _spec()
    new_version["eval_set_version"] = "v2"
    new_version["metrics"].clear()
    assert integrity_check(_report(), _report(), new_version, _spec()) == []
