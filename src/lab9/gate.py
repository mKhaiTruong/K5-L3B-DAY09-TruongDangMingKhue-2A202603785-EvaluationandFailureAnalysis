"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item


def _looser(label: str, old: dict, new: dict, old_blocking: bool, new_blocking: bool) -> list[str]:
    """Return ratchet violations where `new` thresholds are looser than `old`."""
    out = []

    if old_blocking and not new_blocking:
        out.append(f"ratchet: {label} is no longer blocking")

    for key in ("max", "max_increase"):
        if key in old and (key not in new or new[key] > old[key]):
            out.append(f"ratchet: {label} {key} loosened {old[key]} -> {new.get(key)}")

    if "min" in old and ("min" not in new or new["min"] < old["min"]):
        out.append(f"ratchet: {label} min loosened {old['min']} -> {new.get('min')}")

    if old.get("no_significant_drop") and not new.get("no_significant_drop"):
        out.append(f"ratchet: {label} dropped no_significant_drop")

    return out


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """Return reasons the PR report cannot be trusted (empty list = trustworthy).

    Args:
        pr: Eval report of the PR.
        base: Eval report of main, the source of truth for items, seeds and slice tags.
        spec: Metric spec of the PR.
        base_spec: Metric spec of main; enables the ratchet check when given.

    Returns:
        List of problem strings, e.g. ["metric pass_rate is nan"].
    """
    problems: list[str] = []

    # 1. NaN / inf in aggregated metrics
    for k, v in pr["metrics"].items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v}")

    # 2. Row count: compare with the BASELINE manifest (the PR manifest can be forged)
    bm       = base["manifest"]
    expected = bm["items"] * len(bm["seeds"])
    if len(pr["rows"]) != expected:
        problems.append(f"rows {len(pr['rows'])} != expected {expected}")

    # 3. Duplicate rows + (item_id, seed) set must equal the baseline's
    pr_keys = [(r["item_id"], r["seed"]) for r in pr["rows"]]
    b_keys  = {(r["item_id"], r["seed"]) for r in base["rows"]}
    if len(set(pr_keys)) != len(pr_keys):
        problems.append("duplicate (item_id, seed) rows")
    if set(pr_keys) != b_keys:
        problems.append(f"(item, seed) set differs from baseline: "
                        f"missing {len(b_keys - set(pr_keys))}, extra {len(set(pr_keys) - b_keys)}")

    # 4. Crashed graders: evaluator_failures or None values on graded metrics
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s)")
    graded = [m["id"] for m in spec["metrics"] if base["rows"] and m["id"] in base["rows"][0]]
    for m in graded:
        n_none = sum(1 for r in pr["rows"] if r.get(m) is None)
        if n_none:
            problems.append(f"{n_none} row(s) with {m}=None")

    # 5. Slice tags must match the baseline's (no relabelling out of a slice)
    b_tags = {r["item_id"]: sorted(r.get("slices") or []) for r in base["rows"]}
    moved  = {r["item_id"] for r in pr["rows"]
              if r["item_id"] in b_tags and sorted(r.get("slices") or []) != b_tags[r["item_id"]]}
    if moved:
        problems.append(f"slice tags changed for: {', '.join(sorted(moved))}")

    # 6. Aggregates the report claims must be reproducible from its rows
    #    (a hand-edited `metrics` block lies). Only claimed keys are compared.
    if not problems:
        row_metrics = [m["id"] for m in spec["metrics"] if m["id"] in base["rows"][0]]
        rows = [{"cost": 0.0, **r} for r in pr["rows"]]
        try:
            fresh = aggregate(rows, row_metrics, k_values=spec.get("pass_k", []))
        except (KeyError, TypeError) as exc:
            problems.append(f"cannot recompute metrics from rows: {exc!r}")
        else:
            for k, v in fresh.items():
                if k not in pr["metrics"]:
                    continue
                got = pr["metrics"][k]
                if (v is None) != (got is None) or (v is not None and abs(v - got) > 1e-6):
                    problems.append(f"metric {k}: report says {got}, rows give {v}")

    # 7. Ratchet: only when the eval-set version is unchanged
    if base_spec and base_spec.get("eval_set_version") == spec.get("eval_set_version"):
        new_m = {m["id"]: m for m in spec["metrics"]}
        for om in base_spec["metrics"]:
            nm = new_m.get(om["id"])
            if nm is None:
                problems.append(f"ratchet: metric {om['id']} removed")
                continue
            problems += _looser(f"metric {om['id']}", om.get("threshold", {}), nm.get("threshold", {}),
                                om.get("blocking", False), nm.get("blocking", False))

        new_s = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
        for os_ in base_spec.get("slices") or []:
            key = (os_["name"], os_["metric"])
            ns  = new_s.get(key)
            if ns is None:
                problems.append(f"ratchet: slice {key[0]}/{key[1]} removed")
                continue
            problems += _looser(f"slice {key[0]}/{key[1]}", os_, ns,
                                os_.get("blocking", False), ns.get("blocking", False))

    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            # An empty slice cannot vouch for anything: relabelled or dropped items must not pass.
            verdict = "missing"
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in s and val < s["min"]:
                verdict = "fail"
            if s.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        th = {k: s[k] for k in ("min", "no_significant_drop") if k in s}
        lines.append(f"  {sid:<40} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
