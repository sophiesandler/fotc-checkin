"""Phase 3: Dashboard and Risk tracker pages. Works on live check-ins or on clearly labeled demo data."""
import json
import os

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import db
import risk
import seasons
import ui
from auth import require

BLUE_, ORANGE_ = ui.BLUE, ui.ORANGE

HERE = os.path.dirname(os.path.abspath(__file__))
CORE, LABEL = risk.CORE, risk.LABEL
ITEM_THEME = {"C02": "T02", "C03": "T04", "C04": "T05", "C05": "T01", "C06": "T08", "C07": "T09"}
LONG = {"C01": "Likely to still be a Mentor in a year", "C02": "Workload feels sustainable", "C03": "Gets the support needed from their supervisor",
        "C04": "Understands what is expected", "C05": "Time feels meaningful when youth are away", "C06": "Has enough emotional support",
        "C07": "Feels connected to the mission"}
TB = ["First year", "1 to 3 years", "3+ years"]
SOURCES = ["Live check-ins", "Demo data (synthetic)"]
LONG_ORDER = list(LONG.values())
SHORT = risk.LABEL
SHORT_ORDER = [SHORT[c] for c in CORE]


def plot(chart, height=None):
    st.altair_chart(ui.style(chart, height), theme=None, width="stretch")


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
def demo_tags():
    return pd.read_csv(os.path.join(HERE, "demo_tags.csv")).fillna({"quote": ""})


def season_of(row):
    return row.get("season") or seasons.from_ts(row.get("ts"))


def live_checkins():
    cols = ["mentor", "wave", "t", *CORE, "n_skipped", "tb", "restricted", "left_next"]
    rows = db.fetch_responses()
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows)
    df["skipped"] = df["skipped"].astype(int)
    df["wave"] = [season_of(r) for r in rows]
    r = df[(df["qtype"] == "Rating") & df["question_id"].isin(CORE)].copy()
    r["val"] = pd.to_numeric(r["rating"], errors="coerce")
    if r.empty:
        return pd.DataFrame(columns=cols)
    piv = r.pivot_table(index=["participant_code", "session_id", "wave"], columns="question_id", values="val", aggfunc="first").reset_index()
    piv["ts"] = piv["session_id"].map(df.groupby("session_id")["ts"].max())
    piv["n_skipped"] = piv["session_id"].map(df.groupby("session_id")["skipped"].sum())
    for c in CORE:
        if c not in piv:
            piv[c] = np.nan
    piv = piv.sort_values("ts").drop_duplicates(["participant_code", "wave"], keep="last").rename(columns={"participant_code": "mentor"})
    piv["t"] = piv["wave"].map(seasons.key)
    piv["tb"], piv["restricted"], piv["left_next"] = np.nan, np.nan, np.nan
    return piv[cols].reset_index(drop=True)


def live_tags():
    rows = db.get_tags()
    if not rows:
        return pd.DataFrame(columns=["mentor", "wave", "t", "theme", "valence", "question", "quote", "aggregate_only"])
    df = pd.DataFrame(rows)
    df["wave"] = [season_of(r) for r in rows]
    df["t"] = df["wave"].map(seasons.key)
    df = df[~df["escalation"].astype(bool)]
    return df.rename(columns={"participant_code": "mentor", "question_id": "question"})[["mentor", "wave", "t", "theme", "valence", "question", "quote", "aggregate_only"]]


def pick_source():
    k = _k()
    live = live_checkins()
    if "src_choice" not in st.session_state:
        st.session_state.src_choice = SOURCES[0] if live["mentor"].nunique() >= k else SOURCES[1]
    choice = st.radio("Data shown", SOURCES, index=SOURCES.index(st.session_state.src_choice), horizontal=True,
                      key="src_radio", on_change=lambda: st.session_state.update(src_choice=st.session_state.src_radio))
    if choice == SOURCES[1]:
        st.warning("Demo data: 300 synthetic Mentors over six seasons, with illustrative answers written for the demo. Nobody here is real, and the patterns were planted for testing.")
        return "demo", demo_checkins().copy()
    if live["mentor"].nunique() < k:
        st.caption(f"Live check-ins come from {live['mentor'].nunique()} Mentor(s) so far. Groups smaller than {k} stay hidden. You can lower this in Settings while testing.")
    return "live", live


def mean_k(s, k):
    s = s.dropna()
    return float(s.mean()) if len(s) >= k else None


def pick_wave(waves, key):
    if len(waves) < 2:
        st.caption(f"Season shown: {waves[0]}")
        return waves[0]
    return st.select_slider("Season", options=waves, value=waves[-1], key=key)


def order_waves(df):
    return list(df.drop_duplicates("wave").sort_values("t")["wave"])


# ---------------------------------------------------------------- dashboard
def page_dashboard():
    user = require("leader", "admin")
    k = _k()
    st.title("Dashboard")
    st.caption(f"Group results by season. Groups smaller than {k} are hidden to protect privacy.")
    source, data = pick_source()
    if data.empty:
        st.info("No check-ins yet. Sign in as a Mentor, complete a practice check-in, and come back, or switch to the demo data above.")
        return
    rules, bands = risk.load_rules()
    ev = risk.evaluate(data, rules, bands)
    waves = order_waves(ev)
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        sel = pick_wave(waves, "dash_wave")
    has_tb, has_acc = ev["tb"].notna().any(), ev["restricted"].notna().any()
    tb = c2.selectbox("Time as a Mentor", ["Everyone"] + TB, disabled=not has_tb)
    acc = c3.selectbox("School-day access", ["All chapters", "Restricted", "Open"], disabled=not has_acc,
                       help="Only available in the demo data, which includes chapters. Live check-ins are from one chapter.")
    v = ev.copy()
    if has_tb and tb != "Everyone":
        v = v[v["tb"] == TB.index(tb)]
    if has_acc and acc != "All chapters":
        v = v[v["restricted"] == (1 if acc == "Restricted" else 0)]
    wi = waves.index(sel)
    prev_label = waves[wi - 1] if wi > 0 else None
    cur = v[v["wave"] == sel]
    prev = v[v["wave"] == prev_label] if prev_label else v.iloc[0:0]

    n = cur["mentor"].nunique()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Mentors with a check-in", n if n >= k else f"under {k}")
    inten = mean_k(cur["C01"], k)
    pin = mean_k(prev["C01"], k) if len(prev) else None
    dlt = (inten - pin) if inten is not None and pin is not None else None
    m2.metric("Average intent to stay (1 to 5)", f"{inten:.1f}" if inten is not None else f"under {k}",
              delta=(f"{dlt:+.1f}" if dlt is not None and abs(dlt) >= 0.05 else None))
    flagged = (cur["band"] != "Low").sum()
    m3.metric("With a support signal", f"{flagged / len(cur) * 100:.0f}%" if len(cur) >= k else f"under {k}",
              help="Mentors whose answers match the indicator rules set on the Risk tracker page. It is a prompt to offer support, not a judgment.")
    if cur["left_next"].notna().any():
        left = int(cur["left_next"].sum())
        m4.metric("Left before next season", left if left >= k else f"under {k}")
    else:
        m4.metric("Left before next season", "pending")

    t_trend, t_theme = st.tabs(["Trends", "Themes"])
    with t_trend:
        _trends(v, ev, waves, sel, wi, prev_label, k, has_tb, has_acc, acc, tb)
    with t_theme:
        _themes(source, v, waves, sel, k)


def _trends(v, ev, waves, sel, wi, prev_label, k, has_tb, has_acc, acc, tb):
    # ---- the season at a glance
    rows = []
    means = {item: [mean_k(v[v["wave"] == w][item], k) for w in waves] for item in CORE}
    for item in CORE:
        series = means[item]
        now_v = series[wi]
        before = series[wi - 1] if wi > 0 else None
        if wi == 0:
            chg = "first season"
        elif now_v is None or before is None:
            chg = "not enough answers"
        elif abs(now_v - before) < 0.15:
            chg = "about the same"
        else:
            chg = f"{'up' if now_v > before else 'down'} {abs(now_v - before):.1f}"
        rows.append({"What Mentors told us": LONG[item], "Trend by season": series, "Average (1 to 5)": None if now_v is None else round(now_v, 1),
                     "Change since last season": chg})
    st.subheader(f"{sel} at a glance")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"Trend by season": st.column_config.LineChartColumn(y_min=2.5, y_max=4.5, width="medium"),
                                "Average (1 to 5)": st.column_config.NumberColumn(format="%.1f")})
    st.caption("Every trend line runs from 2.5 to 4.5 so lines can be compared. A blank means fewer than the minimum number of answers.")

    # ---- biggest movers and same season last year
    left_, right_ = st.columns(2)
    with left_:
        st.subheader("Biggest movers")
        if prev_label is None:
            st.info("This is the first season, so there is nothing to compare with.")
        else:
            mv = [{"Area": SHORT[i], "Change": means[i][wi] - means[i][wi - 1]} for i in CORE if means[i][wi] is not None and means[i][wi - 1] is not None]
            if not mv:
                st.info(f"Not enough answers in both seasons to compare.")
            else:
                mvd = pd.DataFrame(mv)
                mvd["Direction"] = np.where(mvd["Change"] >= 0, "Up", "Down")
                bar = alt.Chart(mvd).mark_bar().encode(
                    x=alt.X("Change:Q", title="Change in average"), y=alt.Y("Area:N", sort=alt.EncodingSortField("Change", order="descending"), title=None),
                    color=alt.Color("Direction:N", scale=alt.Scale(domain=["Up", "Down"], range=[BLUE_, ORANGE_]), legend=None))
                plot(bar + bar.mark_text(align="left", dx=4, color="#282828").encode(text=alt.Text("Change:Q", format="+.2f")), 300)
                st.caption(f"{prev_label} to {sel}. Blue means higher, orange means lower.")
    with right_:
        st.subheader("Same season, last year")
        ly = seasons.same_last_year(sel)
        if ly not in waves:
            st.info(f"There are no check-ins from {ly} to compare with yet.")
        else:
            recs = []
            for item in CORE:
                a, b = mean_k(v[v["wave"] == ly][item], k), mean_k(v[v["wave"] == sel][item], k)
                if a is not None and b is not None:
                    recs += [{"Area": SHORT[item], "Season": ly, "Average": a}, {"Area": SHORT[item], "Season": sel, "Average": b}]
            if recs:
                plot(alt.Chart(pd.DataFrame(recs)).mark_bar().encode(
                    y=alt.Y("Area:N", sort=SHORT_ORDER, title=None), x=alt.X("Average:Q", scale=alt.Scale(domain=[1, 5]), title="Average (1 to 5)"),
                    yOffset="Season:N", color=alt.Color("Season:N", sort=[ly, sel], scale=alt.Scale(domain=[ly, sel], range=["#BDBDBD", BLUE_]),
                                                        legend=alt.Legend(orient="bottom", direction="horizontal"))), 300)
            else:
                st.info("Not enough answers in both seasons to compare.")

    # ---- heatmap: area by season
    st.subheader("Averages by season")
    recs = [{"Season": w, "Area": LONG[item], "Average": means[item][i]} for item in CORE for i, w in enumerate(waves) if means[item][i] is not None]
    hm = pd.DataFrame(recs)
    if not hm.empty:
        base = alt.Chart(hm).encode(x=alt.X("Season:N", sort=waves, title=None, axis=alt.Axis(labelAngle=0, orient="top")),
                                    y=alt.Y("Area:N", sort=LONG_ORDER, title=None))
        rect = base.mark_rect(stroke="white", strokeWidth=2).encode(
            color=alt.Color("Average:Q", scale=alt.Scale(domain=[2.8, 3.5, 4.2], range=[ORANGE_, "#F3F3F3", BLUE_]), legend=None))
        txt = base.mark_text(fontSize=14, fontWeight="bold", color="#282828").encode(text=alt.Text("Average:Q", format=".1f"))
        plot(rect + txt, 300)
        st.caption("Blue is higher, orange is lower, grey is in the middle. Colors compare areas and seasons with each other, so a small color change is a small difference.")

    # ---- heatmap: time as a Mentor by season
    st.subheader("By time as a Mentor")
    if not has_tb:
        st.info("Live check-ins do not record how long each Mentor has been in the role yet, so this view uses the demo data.")
    else:
        area = st.selectbox("Area", LONG_ORDER, key="tb_area")
        item = next(i for i, name in LONG.items() if name == area)
        base_df = ev if not has_acc or acc == "All chapters" else ev[ev["restricted"] == (1 if acc == "Restricted" else 0)]
        recs = []
        for w in waves:
            for gi, g in enumerate(TB):
                m = mean_k(base_df[(base_df["wave"] == w) & (base_df["tb"] == gi)][item], k)
                if m is not None:
                    recs.append({"Season": w, "Group": g, "Average": m})
        if recs:
            b2 = alt.Chart(pd.DataFrame(recs)).encode(x=alt.X("Season:N", sort=waves, title=None, axis=alt.Axis(labelAngle=0, orient="top")),
                                                      y=alt.Y("Group:N", sort=TB, title=None))
            plot(b2.mark_rect(stroke="white", strokeWidth=2).encode(color=alt.Color("Average:Q", scale=alt.Scale(domain=[2.8, 3.5, 4.2], range=[ORANGE_, "#F3F3F3", BLUE_]), legend=None))
                 + b2.mark_text(fontSize=14, fontWeight="bold", color="#282828").encode(text=alt.Text("Average:Q", format=".1f")), 190)
        else:
            st.info(f"Each group needs at least {k} answers to be shown.")

    # ---- more detail, tucked away
    with st.expander("Compare areas over time"):
        picks = st.multiselect("Areas to compare", LONG_ORDER, default=[LONG["C01"], LONG["C02"], LONG["C03"]], key="cmp_areas")
        recs = [{"Season": w, "Area": LONG[item], "Average": means[item][i]} for item in CORE for i, w in enumerate(waves)
                if means[item][i] is not None and LONG[item] in picks]
        if recs:
            plot(alt.Chart(pd.DataFrame(recs)).mark_line(point=alt.OverlayMarkDef(size=60), strokeWidth=3).encode(
                x=alt.X("Season:N", sort=waves, title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("Average:Q", scale=alt.Scale(domain=[1, 5]), title="Average (1 to 5)"),
                color=alt.Color("Area:N", scale=alt.Scale(range=[BLUE_, ORANGE_, "#282828", "#919191", "#1A74B8", "#F7B89E", "#265A82"]))), 300)
        else:
            st.info("Pick at least one area.")
    with st.expander(f"How answers were spread in {sel}"):
        cur_ = v[v["wave"] == sel]
        mix = []
        for item in CORE:
            sr = cur_[item].dropna()
            if len(sr) >= k:
                for score in range(1, 6):
                    mix.append({"Area": LONG[item], "Score": str(score), "Share": float((sr == score).mean())})
        if mix:
            plot(alt.Chart(pd.DataFrame(mix)).mark_bar().encode(
                x=alt.X("Share:Q", axis=alt.Axis(format="%"), title=None, stack="zero"), y=alt.Y("Area:N", sort=LONG_ORDER, title=None),
                color=alt.Color("Score:N", scale=alt.Scale(domain=["1", "2", "3", "4", "5"], range=[ui.SCALE[i] for i in range(1, 6)]),
                                legend=alt.Legend(title="Score (1 low, 5 high)", orient="bottom", direction="horizontal")), order=alt.Order("Score:N")), 300)


def _themes(source, v, waves, sel, k):
    """Theme explorer: what Mentors said in their spoken answers, by season."""
    names = {t["id"]: t["name"] for t in db.get_published("codebook")[1]["themes"]}
    tg = demo_tags() if source == "demo" else live_tags()
    if tg.empty:
        st.info("No tagged answers yet. Spoken answers become themes once they are transcribed and tagged. The program admin does this on the **Tag answers** page. "
                "Switch to the demo data above to see how this tab will look.")
    else:
        if source == "demo":
            st.caption("Themes come from synthetic spoken answers tagged for the demo. The quotes are illustrative examples written for the demo, not real Mentors.")
        else:
            st.caption("Themes come from spoken answers tagged by Claude and checked by a person.")
        tw = [w for w in waves if w in set(tg["wave"])]
        den = tg.groupby("wave")["mentor"].nunique()
        mode = st.radio("Show", ["What is hard", "What is working"], horizontal=True, key="theme_mode")
        val = "Negative" if mode == "What is hard" else "Positive"
        scale_range = ["#FFFFFF", ORANGE_] if val == "Negative" else ["#FFFFFF", BLUE_]
        sub = tg[(tg["valence"] == val) & (tg["theme"] != "T10")]
        cnt = sub.groupby(["wave", "theme"])["mentor"].nunique().reset_index(name="n")
        recs = []
        for w in tw:
            for t_, nm in names.items():
                if t_ == "T10":
                    continue
                n_ = cnt[(cnt["wave"] == w) & (cnt["theme"] == t_)]["n"].sum()
                if den.get(w, 0) >= k and n_ >= k:
                    recs.append({"Season": w, "Theme": nm, "Share": n_ / den[w], "Mentors": int(n_)})
        st.subheader("Share of Mentors mentioning each theme")
        if recs:
            hm = pd.DataFrame(recs)
            base = alt.Chart(hm).encode(x=alt.X("Season:N", sort=tw, title=None, axis=alt.Axis(labelAngle=0, orient="top")),
                                        y=alt.Y("Theme:N", sort=alt.EncodingSortField("Share", op="sum", order="descending"), title=None, axis=alt.Axis(labelLimit=340)))
            rect = base.mark_rect(stroke="white", strokeWidth=2).encode(color=alt.Color("Share:Q", scale=alt.Scale(range=scale_range), legend=None))
            txt = base.mark_text(fontSize=13, fontWeight="bold", color="#282828").encode(text=alt.Text("Share:Q", format=".0%"))
            plot(rect + txt, 420)
            st.caption(f"Share of Mentors with a spoken answer that season. A theme with fewer than {k} Mentors in a season is left blank, and life changes outside work are counted only in totals, never shown.")
        else:
            st.info(f"No theme was mentioned by {k} or more Mentors yet.")

        st.subheader(f"What is new in {sel}")
        wi = tw.index(sel) if sel in tw else None
        if wi is None or wi == 0:
            st.info("A comparison needs this season and an earlier season with tagged answers.")
        else:
            pr = tw[wi - 1]
            ch = []
            for t_, nm in names.items():
                if t_ == "T10":
                    continue
                def share(w):
                    n_ = cnt[(cnt["wave"] == w) & (cnt["theme"] == t_)]["n"].sum()
                    return n_ / den[w] if den.get(w, 0) >= k and n_ >= k else None
                a, b = share(pr), share(sel)
                if a is not None and b is not None:
                    ch.append({"Theme": nm, "Change": b - a})
            if ch:
                cd = pd.DataFrame(ch)
                more_good = val == "Positive"
                cd["Direction"] = np.where(cd["Change"] >= 0, "More mentions", "Fewer mentions")
                up_color, down_color = (BLUE_, ORANGE_) if more_good else (ORANGE_, BLUE_)
                bar = alt.Chart(cd).mark_bar().encode(
                    x=alt.X("Change:Q", axis=alt.Axis(format="+%"), title=f"Change in share of Mentors, {pr} to {sel}"),
                    y=alt.Y("Theme:N", sort=alt.EncodingSortField("Change", order="descending"), title=None, axis=alt.Axis(labelLimit=340)),
                    color=alt.Color("Direction:N", scale=alt.Scale(domain=["More mentions", "Fewer mentions"], range=[up_color, down_color]),
                                    legend=alt.Legend(orient="bottom", direction="horizontal")))
                plot(bar + bar.mark_text(align="left", dx=4, color="#282828").encode(text=alt.Text("Change:Q", format="+.0%")), 380)
            else:
                st.info("Not enough answers on both seasons to compare themes.")

        st.subheader("In their words")
        qs = sub[(sub["quote"] != "") & (sub["aggregate_only"].astype(int) == 0)]
        c1, c2 = st.columns(2)
        tl = [t_ for t_ in names if t_ != "T10" and (qs["theme"] == t_).any()]
        if not tl:
            st.info("No excerpts to show yet.")
        else:
            tsel = c1.selectbox("Theme", tl, format_func=lambda t_: f"{names[t_]} ({int((qs['theme'] == t_).sum())})")
            ssel = c2.selectbox("Season", ["All seasons"] + list(reversed(tw)), index=(1 + list(reversed(tw)).index(sel)) if sel in tw else 0)
            pick = qs[qs["theme"] == tsel]
            if ssel != "All seasons":
                pick = pick[pick["wave"] == ssel]
            if len(pick) and pick["mentor"].nunique() < k:
                st.info(f"Fewer than {k} Mentors have excerpts here, so they are hidden to protect privacy.")
            else:
                uniq = (pick.sort_values("t", ascending=False).groupby("quote", sort=False)
                        .agg(wave=("wave", "first"), n=("mentor", "nunique")).reset_index().head(8))
                for _, row in uniq.iterrows():
                    more = f" · similar answers from {row['n']} Mentors" if row["n"] >= k else ""
                    st.markdown(f"> “{row['quote']}”  \n> <span style='color:#555'>{row['wave']}{more}</span>", unsafe_allow_html=True)
            st.caption("Excerpts are copied exactly from answers. Names are never shown. Anything that raised a safety concern is handled by a person outside the dashboard.")

    st.subheader("Why people left")
    if source == "demo":
        ex = demo_exits()["top_reason"].map(lambda t_: names.get(t_, t_)).value_counts()
        st.caption(f"Main reason chosen by the {int(ex.sum())} Mentors who completed an exit interview.")
    else:
        resp = pd.DataFrame(db.fetch_responses())
        ex = resp[(resp["qtype"] == "Checklist") & (resp["checklist_top"].fillna("") != "")]["checklist_top"].value_counts() if not resp.empty else pd.Series(dtype=int)
        st.caption(f"Main reason chosen in {int(ex.sum())} exit interview(s).")
    shown = ex[ex >= k]
    if shown.empty:
        st.info(f"No reason has {k} or more answers yet.")
    else:
        bar = shown.rename_axis("Reason").reset_index(name="Mentors")
        ch = alt.Chart(bar).mark_bar(color=ORANGE_).encode(x=alt.X("Mentors:Q", title=None), y=alt.Y("Reason:N", sort="-x", title=None, axis=alt.Axis(labelLimit=340)))
        plot(ch + ch.mark_text(align="left", dx=4, color="#282828").encode(text="Mentors:Q"), 280)
    if int((ex < k).sum()):
        st.caption(f"{int((ex < k).sum())} other reason(s) with fewer than {k} answers are hidden.")


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
    waves = order_waves(ev)
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
            col.metric(f"{b} priority" + (f" ({x / n * 100:.0f}%)" if x >= k else ""), x if x >= k else f"under {k}")
        trend = []
        for w in waves:
            sw = ev[ev["wave"] == w]
            trend.append({"Season": w, "Share with a signal": (float((sw["band"] != "Low").mean()) if len(sw) >= k else None)})
        t = pd.DataFrame(trend).dropna()
        d1, d2 = st.columns(2)
        with d1:
            st.markdown(f"**Priority mix in {sel}**")
            dn = pd.DataFrame({"Priority": ["High", "Medium", "Low"], "Mentors": [int(counts.get(b, 0)) for b in ("High", "Medium", "Low")]})
            dn = dn[dn["Mentors"] >= k]
            arc = alt.Chart(dn).mark_arc(innerRadius=70, stroke="white", strokeWidth=3).encode(
                theta=alt.Theta("Mentors:Q"), color=alt.Color("Priority:N", scale=alt.Scale(domain=list(ui.BAND), range=list(ui.BAND.values())),
                                                              legend=alt.Legend(orient="bottom", direction="horizontal")))
            plot(arc, 280)
        with d2:
            st.markdown("**Priority mix by season**")
            rows_ = []
            for w in waves:
                sw = ev[ev["wave"] == w]
                if len(sw) >= k:
                    for b in ("High", "Medium", "Low"):
                        c_ = int((sw["band"] == b).sum())
                        if c_ >= k:
                            rows_.append({"Season": w, "Priority": b, "Share": c_ / len(sw)})
            if rows_:
                plot(alt.Chart(pd.DataFrame(rows_)).mark_bar().encode(
                    x=alt.X("Season:N", sort=waves, title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("Share:Q", axis=alt.Axis(format="%"), title=None, stack="zero"),
                    color=alt.Color("Priority:N", scale=alt.Scale(domain=list(ui.BAND), range=list(ui.BAND.values())),
                                    legend=alt.Legend(orient="bottom", direction="horizontal")),
                    order=alt.Order("order:Q") if False else alt.Order("Priority:N", sort="descending")), 280)
                st.caption(f"Groups with fewer than {k} Mentors are left out.")
        l, r_ = st.columns(2)
        with l:
            st.markdown("**Share of Mentors with a signal, by season**")
            if len(t):
                plot(alt.Chart(t).mark_line(point=alt.OverlayMarkDef(size=70), color=ORANGE_, strokeWidth=3).encode(
                    x=alt.X("Season:N", sort=waves, title=None, axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("Share with a signal:Q", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, max(0.5, float(t["Share with a signal"].max()) + 0.05)]), title=None)), 280)
        with r_:
            st.markdown(f"**Which signals show up most in {sel}**")
            names = {x["id"]: x["name"] for x in rules}
            cnt = pd.Series([h for hs in cur["hit_ids"] for h in hs], dtype="object").map(names).value_counts()
            cnt = cnt[cnt >= k]
            if cnt.empty:
                st.caption(f"No single signal appears {k} or more times.")
            else:
                bar = cnt.rename_axis("Signal").reset_index(name="Mentors")
                bb = alt.Chart(bar).mark_bar(color=BLUE_).encode(x=alt.X("Mentors:Q", title=None), y=alt.Y("Signal:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320)))
                plot(bb + bb.mark_text(align="left", dx=4, color="#282828").encode(text="Mentors:Q"), 280)

    if source == "demo":
        lab = ev[ev["left_next"].notna()]
        st.subheader("How well do these rules work in the demo data?")
        rows = []
        for b in ("High", "Medium", "Low"):
            s = lab[lab["band"] == b]
            rows.append({"Priority": b, "Check-ins": len(s), "Share of all check-ins": len(s) / len(lab), "Left before the next season": float(s["left_next"].mean()) if len(s) else None})
        ev_df = pd.DataFrame(rows)
        base_rate = float(lab["left_next"].mean())
        dep = alt.Chart(ev_df).mark_bar().encode(
            x=alt.X("Priority:N", sort=["High", "Medium", "Low"], title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Left before the next season:Q", axis=alt.Axis(format="%"), title="Left before the next season"),
            color=alt.Color("Priority:N", scale=alt.Scale(domain=list(ui.BAND), range=list(ui.BAND.values())), legend=None))
        avg = alt.Chart(pd.DataFrame({"y": [base_rate]})).mark_rule(color="#282828", strokeDash=[6, 4], strokeWidth=2).encode(y="y:Q")
        lbl = alt.Chart(ev_df).mark_text(dy=-9, color="#282828", fontWeight="bold").encode(
            x=alt.X("Priority:N", sort=["High", "Medium", "Low"]), y="Left before the next season:Q",
            text=alt.Text("Left before the next season:Q", format=".0%"))
        plot(dep + avg + lbl, 260)
        st.caption(f"The dashed line is the overall rate ({base_rate * 100:.0f}%).")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"Share of all check-ins": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent"),
                                    "Left before the next season": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent")})
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
        st.info("No Mentors match in this season.")
    else:
        table = pd.DataFrame({
            "Mentor": lst["mentor"], "Priority": lst["band"], "Points": lst["points"],
            "What stands out": ["; ".join(dict.fromkeys(rs)) or "—" for rs in lst["reasons"]],
            "Intent to stay (last)": [("skipped" if pd.isna(a) else str(int(a))) for a in lst["C01"]],
            "Time as a Mentor": [("not recorded" if pd.isna(t) else TB[int(t)]) for t in lst["tb"]],
            "Check-in offered": ["Yes" if m in done else "" for m in lst["mentor"]]})
        colors = {"High": "background-color:#EC6237;color:white;font-weight:bold", "Medium": "background-color:#F7B89E;color:#282828;font-weight:bold"}
        styled = table.style.map(lambda x: colors.get(x, ""), subset=["Priority"])
        st.dataframe(styled, hide_index=True, width="stretch",
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
