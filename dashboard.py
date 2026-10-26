"""Phase 3: Dashboard and Risk tracker pages. Works on live check-ins or on clearly labeled demo data."""
import json
import os

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import db
import risk
from auth import require

HERE = os.path.dirname(os.path.abspath(__file__))
CORE, LABEL = risk.CORE, risk.LABEL
ITEM_THEME = {"C02": "T02", "C03": "T04", "C04": "T05", "C05": "T01", "C06": "T08", "C07": "T09"}
LONG = {"C01": "Likely to still be a Mentor in a year", "C02": "Workload feels sustainable", "C03": "Gets the support needed from their supervisor",
        "C04": "Understands what is expected", "C05": "School-day time feels meaningful", "C06": "Has enough emotional support",
        "C07": "Feels connected to the mission"}
TB = ["First year", "1 to 3 years", "3+ years"]
SOURCES = ["Live check-ins", "Demo data (synthetic)"]


def _k():
    return int(db.get_setting("min_group", "5"))


# ---------------------------------------------------------------- data
@st.cache_data
def demo_checkins():
    return pd.read_csv(os.path.join(HERE, "demo_checkins.csv"))


@st.cache_data
def demo_exits():
    return pd.read_csv(os.path.join(HERE, "demo_exits.csv"))


@st.cache_data
def demo_quotes():
    return json.load(open(os.path.join(HERE, "demo_quotes.json"), encoding="utf-8"))


def live_checkins():
    cols = ["mentor", "wave", *CORE, "n_skipped", "tb", "restricted", "left_next"]
    rows = db.fetch_responses()
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows)
    df["skipped"] = df["skipped"].astype(int)
    df["wave"] = df["ts"].str[:4] + " Q" + df["quarter"].astype(str)
    r = df[(df["qtype"] == "Rating") & df["question_id"].isin(CORE)].copy()
    r["val"] = pd.to_numeric(r["rating"], errors="coerce")
    if r.empty:
        return pd.DataFrame(columns=cols)
    piv = r.pivot_table(index=["participant_code", "session_id", "wave"], columns="question_id", values="val", aggfunc="first").reset_index()
    last_ts = df.groupby("session_id")["ts"].max()
    piv["ts"] = piv["session_id"].map(last_ts)
    piv["n_skipped"] = piv["session_id"].map(df.groupby("session_id")["skipped"].sum())
    for c in CORE:
        if c not in piv:
            piv[c] = np.nan
    piv = piv.sort_values("ts").drop_duplicates(["participant_code", "wave"], keep="last")
    piv = piv.rename(columns={"participant_code": "mentor"})
    piv["tb"], piv["restricted"], piv["left_next"] = np.nan, np.nan, np.nan
    return piv[cols].reset_index(drop=True)


def pick_source():
    k = _k()
    live = live_checkins()
    if "src_choice" not in st.session_state:
        st.session_state.src_choice = SOURCES[0] if live["mentor"].nunique() >= k else SOURCES[1]
    choice = st.radio("Data shown", SOURCES, index=SOURCES.index(st.session_state.src_choice), horizontal=True,
                      key="src_radio", on_change=lambda: st.session_state.update(src_choice=st.session_state.src_radio))
    if choice == SOURCES[1]:
        st.warning("Demo data: 300 synthetic Mentors over six quarters. Nobody here is real, and the patterns were planted for testing.")
        return "demo", demo_checkins().copy()
    if live["mentor"].nunique() < k:
        st.caption(f"Live check-ins come from {live['mentor'].nunique()} Mentor(s) so far. Groups smaller than {k} stay hidden. You can lower this in Settings while testing.")
    return "live", live


def mean_k(s, k):
    s = s.dropna()
    return float(s.mean()) if len(s) >= k else None


def pick_wave(waves, key):
    if len(waves) < 2:
        st.caption(f"Quarter shown: {waves[0]}")
        return waves[0]
    return st.select_slider("Quarter", options=waves, value=waves[-1], key=key)


# ---------------------------------------------------------------- dashboard
def page_dashboard():
    user = require("leader", "admin")
    k = _k()
    st.title("Dashboard")
    st.caption(f"Group results only. Groups smaller than {k} are hidden to protect privacy.")
    source, data = pick_source()
    if data.empty:
        st.info("No check-ins yet. Sign in as a Mentor, complete a practice check-in, and come back, or switch to the demo data above.")
        return
    rules, bands = risk.load_rules()
    ev = risk.evaluate(data, rules, bands)
    waves = sorted(ev["wave"].unique())
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        sel = pick_wave(waves, "dash_wave")
    has_tb, has_acc = ev["tb"].notna().any(), ev["restricted"].notna().any()
    tb = c2.selectbox("Time as a Mentor", ["Everyone"] + TB, disabled=not has_tb)
    acc = c3.selectbox("School-day access", ["All chapters", "Restricted", "Open"], disabled=not has_acc)
    v = ev.copy()
    if has_tb and tb != "Everyone":
        v = v[v["tb"] == TB.index(tb)]
    if has_acc and acc != "All chapters":
        v = v[v["restricted"] == (1 if acc == "Restricted" else 0)]
    wi = waves.index(sel)
    cur, prev = v[v["wave"] == sel], (v[v["wave"] == waves[wi - 1]] if wi > 0 else v.iloc[0:0])

    n = cur["mentor"].nunique()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Mentors with a check-in", n if n >= k else f"under {k}")
    inten = mean_k(cur["C01"], k)
    pin = mean_k(prev["C01"], k) if len(prev) else None
    dlt = (inten - pin) if inten is not None and pin is not None else None
    m2.metric("Average intent to stay (1 to 5)", f"{inten:.1f}" if inten is not None else f"under {k}",
              delta=(f"{dlt:+.1f}" if dlt is not None and abs(dlt) >= 0.05 else None))
    flagged = (cur["band"] != "Low").sum()
    m3.metric("Share with a support signal", f"{flagged / len(cur) * 100:.0f}%" if len(cur) >= k else f"under {k}",
              help="Mentors whose answers match the indicator rules set on the Risk tracker page. It is a prompt to offer support, not a judgment.")
    if cur["left_next"].notna().any():
        left = int(cur["left_next"].sum())
        m4.metric("Left before the next quarter", left if left >= k else f"under {k}")
    else:
        m4.metric("Left before the next quarter", "pending")

    t_trend, t_theme, t_school = st.tabs(["Trends", "Themes", "School-day time"])
    with t_trend:
        rows = []
        for item in CORE:
            series = [mean_k(v[v["wave"] == w][item], k) for w in waves]
            now_v = series[wi]
            before = series[wi - 1] if wi > 0 else None
            if wi == 0:
                chg = "first quarter"
            elif now_v is None or before is None:
                chg = "not enough answers"
            elif abs(now_v - before) < 0.15:
                chg = "about the same"
            else:
                chg = f"{'up' if now_v > before else 'down'} {abs(now_v - before):.1f}"
            rows.append({"What Mentors told us": LONG[item], "Six-quarter trend": series, "Average (1 to 5)": None if now_v is None else round(now_v, 1),
                         "Change since last quarter": chg})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"Six-quarter trend": st.column_config.LineChartColumn(y_min=2.5, y_max=4.5, width="medium"),
                                    "Average (1 to 5)": st.column_config.NumberColumn(format="%.1f")})
        st.caption("Every trend line runs from 2.5 to 4.5 so lines can be compared. A blank means fewer than the minimum number of answers.")

    with t_theme:
        names = {t["id"]: t["name"] for t in db.get_published("codebook")[1]["themes"]}
        l, r_ = st.columns(2)
        with l:
            st.subheader("Why people left")
            if source == "demo":
                ex = demo_exits()["top_reason"].map(lambda t: names.get(t, t)).value_counts()
                tot = int(ex.sum())
                st.caption(f"Main reason chosen by the {tot} Mentors who completed an exit interview.")
            else:
                resp = pd.DataFrame(db.fetch_responses())
                ex = resp[(resp["qtype"] == "Checklist") & (resp["checklist_top"].fillna("") != "")]["checklist_top"].value_counts() if not resp.empty else pd.Series(dtype=int)
                tot = int(ex.sum())
                st.caption(f"Main reason chosen in {tot} exit interview(s).")
            shown = ex[ex >= k]
            if shown.empty:
                st.info(f"No reason has {k} or more answers yet.")
            else:
                bar = shown.rename_axis("Reason").reset_index(name="Mentors")
                ch = alt.Chart(bar).mark_bar(color="#1E7F74").encode(x=alt.X("Mentors:Q", title=None), y=alt.Y("Reason:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320)))
                st.altair_chart(ch, width="stretch")
            hidden = int((ex < k).sum())
            if hidden:
                st.caption(f"{hidden} other reason(s) with fewer than {k} answers are hidden.")
        with r_:
            st.subheader("Where Mentors rate things low")
            st.caption(f"Share scoring 1 or 2 in {sel}.")
            lows = []
            for item, th in ITEM_THEME.items():
                s = cur[item].dropna()
                lows.append({"Area": LABEL[item], "Share rating low": (float((s <= 2).mean()) if len(s) >= k else None)})
            lows = pd.DataFrame(lows).sort_values("Share rating low", ascending=False, na_position="last")
            st.dataframe(lows, hide_index=True, width="stretch",
                         column_config={"Share rating low": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent")})
        st.subheader("In their words")
        if source == "demo":
            q = demo_quotes()
            themes = [t for t in q if t in names]
            tsel = st.selectbox("Theme", themes, format_func=lambda t: f"{names[t]} ({len(q[t])})")
            st.caption("Excerpts copied exactly from mock transcripts tagged by Claude. Excerpts about life changes outside work are counted but never shown, and any answer that raised a safety concern is handled by a person outside the dashboard.")
            for item in q[tsel]:
                tag = {"Positive": "A reason to stay", "Negative": "A concern"}.get(item["v"], "Mixed")
                st.markdown(f"> “{item['q']}”  \n> <span style='color:gray'>{tag}</span>", unsafe_allow_html=True)
        else:
            st.info("Excerpts and theme counts from live answers appear here once spoken answers have been transcribed and tagged. That is the next phase.")

    with t_school:
        st.subheader("Does school-day time feel meaningful?")
        base = ev if tb == "Everyone" or not has_tb else ev[ev["tb"] == TB.index(tb)]
        if has_acc:
            recs = []
            for w in waves:
                for g, flag in (("Restricted access", 1), ("Open access", 0)):
                    s = base[(base["wave"] == w) & (base["restricted"] == flag)]["C05"].dropna()
                    recs.append({"Quarter": w, "Group": g, "Average": float(s.mean()) if len(s) >= k else None})
            df_ = pd.DataFrame(recs).dropna()
            if df_.empty:
                st.info(f"Each group needs at least {k} answers to be shown.")
            else:
                ch = alt.Chart(df_).mark_line(point=True).encode(
                    x=alt.X("Quarter:N", title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("Average:Q", scale=alt.Scale(domain=[1, 5]), title="Average (1 to 5)"),
                    color=alt.Color("Group:N", scale=alt.Scale(range=["#B5463B", "#1E7F74"]), legend=alt.Legend(title=None, orient="bottom")))
                st.altair_chart(ch, width="stretch")
            st.warning("In the demo data, restricted access was set to lower this score, and the link to intent to stay is partly built in. "
                       "With real data the gap could be larger, smaller, or absent, and a lower score does not prove it causes people to leave.")
        else:
            recs = [{"Quarter": w, "Average": mean_k(base[base["wave"] == w]["C05"], k)} for w in waves]
            df_ = pd.DataFrame(recs).dropna()
            if df_.empty:
                st.info(f"At least {k} answers are needed to show a trend.")
            else:
                st.altair_chart(alt.Chart(df_).mark_line(point=True, color="#1E7F74").encode(
                    x=alt.X("Quarter:N", title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("Average:Q", scale=alt.Scale(domain=[1, 5]))), width="stretch")
            st.caption("A comparison of restricted and open chapters needs chapter information, which live check-ins do not collect yet.")


# ---------------------------------------------------------------- risk tracker
def _rule_editor(rules, bands, user):
    stamp = st.session_state.setdefault("rstamp", 0)
    work = st.session_state.setdefault("rwork", [dict(r) for r in rules])
    st.caption("Each rule is worth some points. Add the points up for each Mentor and compare with the two cut-offs below.")
    for r in work:
        k = f"{stamp}_{r['id']}_"
        with st.expander(f"{'On ' if st.session_state.get(k + 'on', r['enabled']) else 'Off'} | {risk.describe(r)}  ({r['points']} point(s))"):
            st.text_input("Rule name", r["name"], key=k + "name")
            kind = st.selectbox("Kind of rule", list(risk.KINDS), index=list(risk.KINDS).index(r["kind"]), format_func=risk.KINDS.get, key=k + "kind")
            if kind in ("level", "drop"):
                st.selectbox("Question", CORE, index=CORE.index(r["item"]) if r["item"] in CORE else 0, format_func=lambda c: LABEL[c], key=k + "item")
            if kind != "first_year":
                st.number_input("Threshold", 0, 10, int(r["threshold"]), key=k + "thr",
                                help="Rated at or below: the highest score that counts. Dropped: the smallest fall that counts. Counts: the smallest number that counts.")
            st.number_input("Points", 0, 10, int(r["points"]), key=k + "pts")
            st.checkbox("Rule is on", r["enabled"], key=k + "on")
            st.checkbox("Delete this rule", False, key=k + "del")
    with st.expander("Add a rule"):
        nk = st.selectbox("Kind of rule", list(risk.KINDS), format_func=risk.KINDS.get, key="nr_kind")
        ni = st.selectbox("Question (for rated-at-or-below and dropped rules)", CORE, format_func=lambda c: LABEL[c], key="nr_item")
        nt = st.number_input("Threshold", 0, 10, 2, key="nr_thr")
        npts = st.number_input("Points", 0, 10, 1, key="nr_pts")
        nname = st.text_input("Rule name", key="nr_name")
        if st.button("Add rule"):
            if not nname.strip():
                st.error("Give the rule a name.")
            else:
                cur = _gather_rules(work, stamp)
                cur.append(dict(id=f"rule_{len(cur) + 1}_{abs(hash(nname)) % 1000}", name=nname.strip(), kind=nk, item=ni if nk in ("level", "drop") else "",
                                threshold=int(nt), points=int(npts), enabled=True))
                st.session_state.rwork = cur
                st.session_state.rstamp = stamp + 1
                st.rerun()
    c1, c2 = st.columns(2)
    hi = c1.number_input("High priority at this many points or more", 1, 30, int(bands["high"]), key=f"{stamp}_hi")
    me = c2.number_input("Medium priority at this many points or more", 1, 30, int(bands["medium"]), key=f"{stamp}_me")
    b1, b2 = st.columns(2)
    if b1.button("Save rules", type="primary"):
        if me > hi:
            st.error("The medium cut-off cannot be higher than the high cut-off.")
        else:
            risk.save_rules(_gather_rules(work, stamp), dict(high=int(hi), medium=int(me)), user["username"])
            st.session_state.pop("rwork", None)
            st.session_state.flash = "Rules saved. Results below use them now."
            st.rerun()
    if b2.button("Reset to the starting rules"):
        risk.save_rules([dict(r) for r in risk.DEFAULT_RULES], dict(risk.DEFAULT_BANDS), user["username"])
        st.session_state.pop("rwork", None)
        st.session_state.rstamp = stamp + 1
        st.session_state.flash = "Back to the starting rules."
        st.rerun()


def _gather_rules(work, stamp):
    out = []
    for r in work:
        k = f"{stamp}_{r['id']}_"
        if st.session_state.get(k + "del", False):
            continue
        kind = st.session_state.get(k + "kind", r["kind"])
        out.append(dict(id=r["id"], name=st.session_state.get(k + "name", r["name"]).strip(), kind=kind,
                        item=(st.session_state.get(k + "item", r["item"]) if kind in ("level", "drop") else ""),
                        threshold=int(st.session_state.get(k + "thr", r["threshold"])), points=int(st.session_state.get(k + "pts", r["points"])),
                        enabled=bool(st.session_state.get(k + "on", r["enabled"]))))
    return out


def page_risk():
    user = require("leader", "admin")
    k = _k()
    st.title("Risk tracker")
    msg = st.session_state.pop("flash", None)
    if msg:
        st.success(msg)
    st.caption("Support signals, not judgments. A signal means a Mentor's answers match one or more of the indicator rules below, and is a prompt to offer support.")
    source, data = pick_source()
    rules, bands = risk.load_rules()
    if data.empty:
        st.info("No check-ins yet. Switch to the demo data above, or complete a practice check-in.")
        return
    ev = risk.evaluate(data, rules, bands)
    waves = sorted(ev["wave"].unique())
    sel = pick_wave(waves, "risk_wave")
    cur = ev[ev["wave"] == sel]
    n = len(cur)

    st.subheader("Across the whole group")
    if n < k:
        st.info(f"Fewer than {k} Mentors have a check-in in {sel}, so group results are hidden.")
    else:
        counts = cur["band"].value_counts()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Mentors with a check-in", n)
        for col, b in zip((c2, c3, c4), ("High", "Medium", "Low")):
            x = int(counts.get(b, 0))
            col.metric(f"{b} priority", f"{x} ({x / n * 100:.0f}%)" if x >= k else f"under {k}")
        trend = []
        for w in waves:
            s = ev[ev["wave"] == w]
            trend.append({"Quarter": w, "Share with a signal": (float((s["band"] != "Low").mean()) if len(s) >= k else None)})
        t = pd.DataFrame(trend).dropna()
        l, r_ = st.columns(2)
        with l:
            st.markdown("**Share of Mentors with a signal, by quarter**")
            if len(t):
                st.altair_chart(alt.Chart(t).mark_line(point=True, color="#B5463B").encode(
                    x=alt.X("Quarter:N", title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("Share with a signal:Q", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, max(0.5, float(t["Share with a signal"].max()) + 0.05)]), title=None)),
                    width="stretch")
        with r_:
            st.markdown(f"**Which signals show up most in {sel}**")
            names = {x["id"]: x["name"] for x in rules}
            cnt = pd.Series([h for hs in cur["hit_ids"] for h in hs]).map(names).value_counts()
            cnt = cnt[cnt >= k]
            if cnt.empty:
                st.caption(f"No single signal appears {k} or more times.")
            else:
                bar = cnt.rename_axis("Signal").reset_index(name="Mentors")
                st.altair_chart(alt.Chart(bar).mark_bar(color="#1E7F74").encode(
                    x=alt.X("Mentors:Q", title=None), y=alt.Y("Signal:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320))), width="stretch")

    if source == "demo":
        lab = ev[ev["left_next"].notna()]
        st.subheader("How well do these rules work in the demo data?")
        rows = []
        for b in ("High", "Medium", "Low"):
            s = lab[lab["band"] == b]
            rows.append({"Priority": b, "Check-ins": len(s), "Share of all check-ins": len(s) / len(lab), "Left before the next quarter": float(s["left_next"].mean()) if len(s) else None})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"Share of all check-ins": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent"),
                                    "Left before the next quarter": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent")})
        got = lab[lab["band"] != "Low"]["left_next"].sum() / max(1, lab["left_next"].sum())
        st.caption(f"Overall, {lab['left_next'].mean() * 100:.0f}% of check-ins were followed by a departure. High and medium together held {got * 100:.0f}% of the departures, so about "
                   f"{(1 - got) * 100:.0f}% left without a signal, and most flagged Mentors stayed. The patterns in the demo data were planted, so treat this as a demonstration of how to read the table, not as evidence.")

    if user["role"] != "admin":
        st.info("Individual Mentors are visible only to the program admin. Leadership sees group results.")
        return

    st.divider()
    st.subheader("Mentors who might benefit from a check-in")
    st.warning("For the program admin only. Do not share this list with supervisors. Use it to offer support, such as a conversation about portfolio size or supervision, never to evaluate anyone.")
    flag = f"viewed_{source}"
    if not st.session_state.get(flag):
        db.log(user["username"], "viewed support list", source)
        st.session_state[flag] = True
    show = st.radio("Show", ["High priority", "High and medium"], horizontal=True, index=1)
    lst = cur[cur["band"].isin(["High"] if show == "High priority" else ["High", "Medium"])].sort_values(["points", "mentor"], ascending=[False, True])
    done = {a["mentor"] for a in db.support_actions(source) if a["wave"] == sel}
    if lst.empty:
        st.info("No Mentors match in this quarter.")
    else:
        table = pd.DataFrame({
            "Mentor": lst["mentor"], "Priority": lst["band"], "Points": lst["points"],
            "What stands out": ["; ".join(dict.fromkeys(rs)) or "—" for rs in lst["reasons"]],
            "Intent to stay (last)": [("skipped" if pd.isna(a) else str(int(a))) for a in lst["C01"]],
            "Time as a Mentor": [("not recorded" if pd.isna(t) else TB[int(t)]) for t in lst["tb"]],
            "Check-in offered": ["Yes" if m in done else "" for m in lst["mentor"]]})
        st.dataframe(table, hide_index=True, width="stretch",
                     column_config={"What stands out": st.column_config.TextColumn(width="large")})
        pick = st.multiselect("Mark check-in offered for", [m for m in lst["mentor"] if m not in done])
        note = st.text_input("Note (optional, for the admin only)", key="act_note")
        if st.button("Save as offered") and pick:
            db.add_support_actions(source, pick, sel, user["username"], note)
            db.log(user["username"], "marked check-in offered", f"{len(pick)} Mentor(s), {source}, {sel}")
            st.session_state.flash = f"Saved for {len(pick)} Mentor(s)."
            st.rerun()
    with st.expander("Change the indicator rules"):
        _rule_editor(rules, bands, user)
