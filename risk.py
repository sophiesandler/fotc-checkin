"""Transparent, editable indicator rules. Each rule is a plain statement ("intent to stay is 2 or lower") worth some points.
Add the points up and compare them with two cut-offs to get a support-priority band. No hidden model."""
import json

import numpy as np
import pandas as pd

CORE = ["C01", "C02", "C03", "C04", "C05", "C06", "C07"]
LABEL = {"C01": "Intent to stay", "C02": "Workload sustainability", "C03": "Supervisor support", "C04": "Role clarity",
         "C05": "School-day time feels meaningful", "C06": "Emotional support", "C07": "Mission connection"}
KINDS = {"level": "Rated at or below", "drop": "Dropped since last check-in by at least",
         "count_low": "Number of areas rated 2 or lower is at least", "skipped": "Number of questions skipped is at least",
         "first_year": "Mentor is in their first year"}

DEFAULT_RULES = [
    dict(id="intent_low", name="Intent to stay is low", kind="level", item="C01", threshold=2, points=3, enabled=True),
    dict(id="intent_drop", name="Intent to stay dropped sharply", kind="drop", item="C01", threshold=2, points=2, enabled=True),
    dict(id="support_low", name="Supervisor support is low", kind="level", item="C03", threshold=2, points=1, enabled=True),
    dict(id="workload_low", name="Workload does not feel sustainable", kind="level", item="C02", threshold=2, points=1, enabled=True),
    dict(id="emotional_low", name="Emotional support is low", kind="level", item="C06", threshold=2, points=1, enabled=True),
    dict(id="mission_low", name="Mission connection is low", kind="level", item="C07", threshold=2, points=1, enabled=True),
    dict(id="many_low", name="Several areas rated low at once", kind="count_low", item="", threshold=3, points=2, enabled=True),
    dict(id="skipped_many", name="Skipped several questions", kind="skipped", item="", threshold=3, points=1, enabled=True),
    dict(id="first_year", name="In their first year", kind="first_year", item="", threshold=0, points=1, enabled=False),
]
DEFAULT_BANDS = dict(high=4, medium=2)


def load_rules():
    import db
    raw = db.get_setting("risk_rules", "")
    bands = db.get_setting("risk_bands", "")
    try:
        rules = json.loads(raw) if raw else DEFAULT_RULES
        b = json.loads(bands) if bands else DEFAULT_BANDS
    except Exception:
        rules, b = DEFAULT_RULES, DEFAULT_BANDS
    return rules, b


def save_rules(rules, bands, username):
    import db
    db.set_setting("risk_rules", json.dumps(rules))
    db.set_setting("risk_bands", json.dumps(bands))
    db.log(username, "changed risk indicator rules", f"{sum(1 for r in rules if r['enabled'])} rules on; high at {bands['high']}, medium at {bands['medium']}")


def describe(rule):
    if rule["kind"] == "level":
        return f"{LABEL.get(rule['item'], rule['item'])} rated {rule['threshold']} or lower"
    if rule["kind"] == "drop":
        return f"{LABEL.get(rule['item'], rule['item'])} dropped by {rule['threshold']} or more since the last check-in"
    if rule["kind"] == "count_low":
        return f"{rule['threshold']} or more areas rated 2 or lower"
    if rule["kind"] == "skipped":
        return f"{rule['threshold']} or more questions skipped"
    return "In their first year"


def evaluate(df, rules, bands):
    """df columns: mentor, wave, C01..C07, n_skipped, tb. Adds points, band, reasons (and previous values for drops)."""
    d = df.sort_values(["mentor", "wave"]).reset_index(drop=True).copy()
    for c in CORE:
        d["prev_" + c] = d.groupby("mentor")[c].shift(1)
    d["points"] = 0
    hits = {}
    low_n = (d[CORE[1:]] <= 2).sum(axis=1)
    for r in rules:
        if not r.get("enabled"):
            continue
        if r["kind"] == "level":
            mask = d[r["item"]] <= r["threshold"]
        elif r["kind"] == "drop":
            mask = (d["prev_" + r["item"]] - d[r["item"]]) >= r["threshold"]
        elif r["kind"] == "count_low":
            mask = low_n >= r["threshold"]
        elif r["kind"] == "skipped":
            mask = d["n_skipped"].fillna(0) >= r["threshold"]
        elif r["kind"] == "first_year":
            mask = d["tb"] == 0
        else:
            continue
        mask = mask.fillna(False)
        hits[r["id"]] = mask
        d["points"] += mask.astype(int) * int(r["points"])
    d["band"] = np.select([d["points"] >= bands["high"], d["points"] >= bands["medium"]], ["High", "Medium"], default="Low")
    by_id = {r["id"]: r for r in rules}
    reasons = []
    for i in range(len(d)):
        row, txt = d.iloc[i], []
        for rid, m in hits.items():
            if m.iloc[i]:
                r = by_id[rid]
                if r["kind"] == "level":
                    txt.append(f"{LABEL.get(r['item'], r['item'])}: {int(row[r['item']])}")
                elif r["kind"] == "drop":
                    txt.append(f"{LABEL.get(r['item'], r['item'])}: {int(row['prev_' + r['item']])} to {int(row[r['item']])}")
                elif r["kind"] == "count_low":
                    txt.append(f"{int(low_n.iloc[i])} areas rated low")
                elif r["kind"] == "skipped":
                    txt.append(f"{int(row['n_skipped'])} questions skipped")
                else:
                    txt.append("In first year")
        reasons.append(txt)
    d["reasons"] = reasons
    d["hit_ids"] = [[rid for rid, m in hits.items() if m.iloc[i]] for i in range(len(d))]
    return d
