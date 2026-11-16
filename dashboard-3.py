"""Phase 3: Dashboard and Support signals pages. Works on live check-ins or on clearly labeled demo data."""
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
SHORT = {"C01": "Intent to stay", "C02": "Workload", "C03": "Supervisor support", "C04": "Role clarity", "C05": "Time when youth are away",
         "C06": "Emotional support", "C07": "Mission connection"}
SHORT_ORDER = [SHORT[c] for c in CORE]
THEME_SHORT = {"T01": "Time when youth are away", "T02": "Portfolio and workload", "T03": "Hours and boundaries", "T04": "Supervisor and program team",
               "T05": "Role clarity", "T06": "Training and onboarding", "T07": "Pay and career growth", "T08": "Youth and family challenges",
               "T09": "Mission and model fit", "T11": "Team culture and belonging", "T99": "Something else"}


def plot(chart, height=None):
    st.altair_chart(ui.style(chart, height), theme=None, width="stretch")


def _k():
    return int(db.get_setting("min_group", "5"))


# ---------------------------------------------------------------- data
def _mtime(name):
    return os.path.getmtime(os.path.join(HERE, name))


@st.cache_data
def _csv(name, mtime):
    """Cached by file modification time, so a new version of the file is picked up without a reboot."""
    return pd.read_csv(os.path.join(HERE, name))


def demo_checkins():
    return _csv("demo_checkins.csv", _mtime("demo_checkins.csv")).copy()


def demo_exits():
    return _csv("demo_exits.csv", _mtime("demo_exits.csv")).copy()


def demo_tags():
    return _csv("demo_tags.csv", _mtime("demo_tags.csv")).fillna({"quote": ""})


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


def stage_note():
    if db.get_setting("program_stage", "Pilot year") == "Pilot year":
        st.info("Pilot year: this view becomes more useful after several seasons of check-ins. Start with the **Pilot year** page.")


def mean_k(s, k):
    s = s.dropna()
    return float(s.mean()) if len(s) >= k else None


def pick_wave(waves, key):
    if len(waves) < 2:
        st.caption(f"Season shown: {waves[0]}")
        return waves[0]
    # a dropdown, like the other filters beside it; it opens on the latest season
    return st.selectbox("Season", waves, index=len(waves) - 1, key=key)


def order_waves(df):
    return list(df.drop_duplicates("wave").sort_values("t")["wave"])


# ---------------------------------------------------------------- dashboard
NEAR = 0.15      # a fall this big counts toward the "needs attention" rules
ARROW = 0.05     # a change this big gets an arrow
DOT = {"Yes": "🔴", "Watch": "🟠", "No": "🟢"}


def active_areas():
    """The rating questions still being asked (retired questions drop out of every view)."""
    asked = {q["id"] for q in db.get_published("questions")[1] if q.get("active", True)}
    return [c for c in CORE if c in asked] or list(CORE)


def _later_box(items):
    """One plain list of what is not available yet and what unlocks it (replaces the blue 'nothing to show' banners)."""
    if not items:
        return
    with st.container(border=True):
        st.markdown("#### Unlocks later")
        st.markdown("\n\n".join(f"⏳ **{name}**: {need}" for name, need in items))


def _verdicts(v, areas, means, sel, wi, k):
    """For each area: ('Yes' | 'Watch' | 'No' | '—', short reason). The rules are unchanged from before."""
    cur_v = v[v["wave"] == sel]
    out = {}
    for item in areas:
        series = means[item]
        now_v = series[wi]
        if now_v is None:
            out[item] = ("—", "")
            continue
        before = series[wi - 1] if wi > 0 else None
        before2 = series[wi - 2] if wi > 1 else None
        s_ = cur_v[item].dropna()
        low = float((s_ <= 2).mean()) if len(s_) >= k else None
        why_yes, why_watch = [], []
        if now_v < 3.0:
            why_yes.append("average below 3.0")
        if low is not None and low >= 0.25:
            why_yes.append(f"{low * 100:.0f}% rated it low")
        if before is not None and before2 is not None and now_v - before <= -NEAR and before - before2 <= -NEAR:
            why_yes.append("fell two seasons in a row")
        if before is not None and now_v - before <= -NEAR:
            why_watch.append("fell this season")
        if low is not None and low >= 0.15:
            why_watch.append(f"{low * 100:.0f}% rated it low")
        if now_v < 3.3:
            why_watch.append("average below 3.3")
        if why_yes:
            out[item] = ("Yes", "; ".join(why_yes))
        elif why_watch:
            out[item] = ("Watch", "; ".join(why_watch))
        else:
            out[item] = ("No", "")
    return out


def _strip(cur, areas, means, verdicts, wi, prev_label, sel, k):
    """'What changed': a few plain lines built from the real numbers."""
    lines = []
    if prev_label is None:
        lines.append("First season: there is nothing to compare with yet. Next season this box shows what moved.")
    else:
        ch = [(SHORT[i], means[i][wi] - means[i][wi - 1]) for i in areas if means[i][wi] is not None and means[i][wi - 1] is not None]
        if not ch:
            lines.append(f"Not enough answers in both {prev_label} and {sel} to compare.")
        else:
            up = max(ch, key=lambda x: x[1])
            down = min(ch, key=lambda x: x[1])
            if up[1] >= ARROW:
                lines.append(f"▲ **{up[0]}** is up {up[1]:.1f} since {prev_label}.")
            if down[1] <= -ARROW:
                lines.append(f"▼ **{down[0]}** is down {abs(down[1]):.1f} since {prev_label}.")
            if up[1] < ARROW and down[1] > -ARROW:
                lines.append(f"Ratings are steady since {prev_label}.")
    shown = [i for i in areas if verdicts[i][0] != "—"]
    yes = [SHORT[i] for i in shown if verdicts[i][0] == "Yes"]
    watch = [SHORT[i] for i in shown if verdicts[i][0] == "Watch"]
    if yes:
        lines.append(f"🔴 **Needs attention:** {'; '.join(yes)}.")
    if watch:
        lines.append(f"🟠 **Watch:** {'; '.join(watch)}.")
    if shown and not yes and not watch:
        lines.append("🟢 No area needs attention.")
    n = cur["mentor"].nunique()
    if n < k:
        lines.append(f"Fewer than {k} Mentors have a check-in this season, so results are hidden to protect privacy.")
    else:
        flagged = int((cur["band"] != "Low").sum())
        lines.append(f"{n} Mentors with a check-in. {flagged} have a support signal (see Support signals).")
    with st.container(border=True):
        st.markdown(f"#### What changed in {sel}")
        st.markdown("\n\n".join(lines))


def page_dashboard():
    user = require("leader", "admin")
    k = _k()
    st.title("Dashboard")
    st.caption(f"What changed since last season, and where to focus. Groups smaller than {k} are hidden to protect privacy.")
    source, data = pick_source()
    if data.empty:
        st.info("No check-ins yet. Sign in as a Mentor, complete a practice check-in, and come back, or switch to the demo data above.")
        return
    rules, bands = risk.load_rules()
    ev = risk.evaluate(data, rules, bands)
    waves = order_waves(ev)
    has_tb = ev["tb"].notna().any()
    c1, c2 = st.columns([2, 1])
    with c1:
        sel = pick_wave(waves, "dash_wave")
    tb = c2.selectbox("Time as a Mentor", ["Everyone"] + TB) if has_tb else "Everyone"
    v = ev.copy()
    if has_tb and tb != "Everyone":
        v = v[v["tb"] == TB.index(tb)]
    wi = waves.index(sel)
    prev_label = waves[wi - 1] if wi > 0 else None
    cur = v[v["wave"] == sel]
    areas = active_areas()
    means = {item: [mean_k(v[v["wave"] == w][item], k) for w in waves] for item in areas}
    verdicts = _verdicts(v, areas, means, sel, wi, k)

    _strip(cur, areas, means, verdicts, wi, prev_label, sel, k)

    t_trend, t_theme = st.tabs(["Trends", "Themes"])
    with t_trend:
        _trends(v, ev, waves, sel, wi, prev_label, k, has_tb, areas, means, verdicts)
    with t_theme:
        _themes(source, v, waves, sel, k)
    st.caption("Dashboard page version 2. You can delete this line once you have confirmed the update.")


def _trends(v, ev, waves, sel, wi, prev_label, k, has_tb, areas, means, verdicts):
    later = []
    long_order = [LONG[c] for c in areas]
    short_order = [SHORT[c] for c in areas]
    ABBR = {"Winter": "Win", "Spring": "Spr", "Summer": "Sum", "Fall": "Fall"}
    short = lambda lbl: f"{ABBR[seasons.parse(lbl)[0]]} {str(seasons.parse(lbl)[1])[-2:]}"
    heads = [short(w) for w in waves]

    # ---- scorecard: arrows show the change since the season before; the last column gives a one-line reason
    table_rows = []
    for item in areas:
        row = {"What Mentors told us": LONG[item]}
        for i, w in enumerate(waves):
            m = means[item][i]
            p_ = means[item][i - 1] if i > 0 else None
            if m is None:
                row[heads[i]] = "—"
            elif p_ is None:
                row[heads[i]] = f"{m:.1f}"
            elif m - p_ >= ARROW:
                row[heads[i]] = f"▲ {m:.1f}"
            elif m - p_ <= -ARROW:
                row[heads[i]] = f"▼ {m:.1f}"
            else:
                row[heads[i]] = f"– {m:.1f}"
        flag, why = verdicts[item]
        row["Needs attention?"] = "—" if flag == "—" else (f"{DOT[flag]} {why[0].upper() + why[1:]}" if why else f"{DOT[flag]} OK")
        table_rows.append(row)
    sc = pd.DataFrame(table_rows)

    def arrow_color(x):
        x = str(x)
        if x.startswith("▲"):
            return "color:#1B7F3B;font-weight:700"
        if x.startswith("▼"):
            return "color:#C62828;font-weight:700"
        return "color:#555555"

    st.subheader("Scorecard")
    st.caption("Average answer each season, from 1 (low) to 5 (high). ▲ means it rose since the season before, ▼ means it fell.")
    styled = sc.style.map(arrow_color, subset=heads)
    if short(sel) in heads:
        styled = styled.set_properties(subset=[short(sel)], **{"background-color": "#EEF5FB"})
    st.dataframe(styled, hide_index=True, width="stretch", height=int(35.5 * (len(sc) + 1)),
                 column_config={"What Mentors told us": st.column_config.TextColumn(width="large"), "Needs attention?": st.column_config.TextColumn(width="large")})
    with st.popover("How are these decided?"):
        st.markdown("**Numbers:** each box is the average answer that season. ▲ rose and ▼ fell by 0.05 or more since the season before. – means about the same. "
                    f"The first season has no arrow, and a dash means fewer than {k} answers. The shaded column is the season you picked.")
        st.markdown("**🔴 Needs attention:** the average is below 3.0, 1 in 4 Mentors rated it low (1 or 2), or it fell two seasons in a row.")
        st.markdown("**🟠 Watch:** it fell this season, 15% or more rated it low, or the average is below 3.3.")
        st.markdown("**🟢 OK:** none of these.")

    # ---- compare: one place, one choice
    ly = seasons.same_last_year(sel)
    options = []
    if prev_label is not None:
        options.append("Since last season")
    else:
        later.append(("Biggest movers", "needs a second season with 5+ Mentors"))
    if ly in waves:
        options.append("Same season last year")
    else:
        later.append(("Same season, last year", f"needs check-ins from {ly}"))
    if len(waves) >= 2:
        options += ["All seasons", "Areas over time"]
    if options:
        st.subheader("Compare seasons")
        mode = st.radio("Compare", options, horizontal=True, key="dash_cmp", label_visibility="collapsed")
        if mode == "Since last season":
            mv = [{"Area": SHORT[i], "Change": means[i][wi] - means[i][wi - 1]} for i in areas if means[i][wi] is not None and means[i][wi - 1] is not None]
            if not mv:
                st.caption("Not enough answers in both seasons to compare.")
            else:
                mvd = pd.DataFrame(mv)
                mvd["Direction"] = np.where(mvd["Change"] >= 0, "Up", "Down")
                bar = alt.Chart(mvd).mark_bar().encode(
                    x=alt.X("Change:Q", title="Change in average"), y=alt.Y("Area:N", sort=alt.EncodingSortField("Change", order="descending"), title=None),
                    color=alt.Color("Direction:N", scale=alt.Scale(domain=["Up", "Down"], range=[BLUE_, ORANGE_]), legend=None))
                plot(bar + bar.mark_text(align="left", dx=4, color="#282828").encode(text=alt.Text("Change:Q", format="+.2f")), 260)
                st.caption(f"{prev_label} to {sel}. Blue bars rose and orange bars fell. Start with the longest bars.")
        elif mode == "Same season last year":
            recs = []
            for item in areas:
                a, b = mean_k(v[v["wave"] == ly][item], k), mean_k(v[v["wave"] == sel][item], k)
                if a is not None and b is not None:
                    recs.append({"Area": SHORT[item], "Last": a, "This": b})
            if recs:
                dd = pd.DataFrame(recs)
                ysel = alt.Y("Area:N", sort=short_order, title=None, axis=alt.Axis(labelLimit=220))
                xs = alt.Scale(domain=[2.5, 4.5])
                rule = alt.Chart(dd).mark_rule(color="#BDBDBD", strokeWidth=4).encode(y=ysel, x=alt.X("Last:Q", scale=xs, title="Average (1 to 5)"), x2="This:Q")
                p_last = alt.Chart(dd).mark_point(filled=True, size=140, color="#919191").encode(y=ysel, x=alt.X("Last:Q", scale=xs))
                p_this = alt.Chart(dd).mark_point(filled=True, size=140, color=BLUE_).encode(y=ysel, x=alt.X("This:Q", scale=xs))
                plot(rule + p_last + p_this, 260)
                st.caption(f"Grey dot: {ly}. Blue dot: {sel}. A long line is a big change.")
            else:
                st.caption("Not enough answers in both seasons to compare.")
        elif mode == "All seasons":
            recs = [{"Season": w, "Area": LONG[item], "Average": means[item][i]} for item in areas for i, w in enumerate(waves) if means[item][i] is not None]
            if recs:
                base = alt.Chart(pd.DataFrame(recs)).encode(x=alt.X("Season:N", sort=waves, title=None, axis=alt.Axis(labelAngle=0, orient="top")),
                                                           y=alt.Y("Area:N", sort=long_order, title=None))
                rect = base.mark_rect(stroke="white", strokeWidth=2).encode(
                    color=alt.Color("Average:Q", scale=alt.Scale(domain=[2.8, 3.5, 4.2], range=[ORANGE_, "#F3F3F3", BLUE_]), legend=None))
                txt = base.mark_text(fontSize=14, fontWeight="bold", color="#282828").encode(text=alt.Text("Average:Q", format=".1f"))
                plot(rect + txt, 300)
                st.caption("Blue is higher, orange is lower. Look across a row for a lasting concern, and down a column for a season that was hard for everyone.")
            else:
                st.caption("Not enough answers to show.")
        else:
            picks = st.multiselect("Areas to compare", long_order, default=long_order[:3], key="cmp_areas")
            recs = [{"Season": w, "Area": LONG[item], "Average": means[item][i]} for item in areas for i, w in enumerate(waves)
                    if means[item][i] is not None and LONG[item] in picks]
            if recs:
                plot(alt.Chart(pd.DataFrame(recs)).mark_line(point=alt.OverlayMarkDef(size=60), strokeWidth=3).encode(
                    x=alt.X("Season:N", sort=waves, title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("Average:Q", scale=alt.Scale(domain=[1, 5]), title="Average (1 to 5)"),
                    color=alt.Color("Area:N", scale=alt.Scale(range=[BLUE_, ORANGE_, "#282828", "#919191", "#1A74B8", "#F7B89E", "#265A82"]))), 300)
            else:
                st.caption("Pick at least one area.")

    # ---- time as a Mentor: only when that detail has been collected
    if not has_tb:
        later.append(("Answers by time as a Mentor", "needs each Mentor's time in the role to be collected, with 5+ Mentors in each group"))
    else:
        st.subheader("Answers by time as a Mentor")
        st.caption("A gap between first-year and later Mentors may point to onboarding or experience.")
        area = st.selectbox("Area", long_order, key="tb_area")
        item = next(i for i in areas if LONG[i] == area)
        recs = []
        for w in waves:
            for gi, g in enumerate(TB):
                m = mean_k(ev[(ev["wave"] == w) & (ev["tb"] == gi)][item], k)
                if m is not None:
                    recs.append({"Season": w, "Group": g, "Average": m})
        if recs:
            b2 = alt.Chart(pd.DataFrame(recs)).encode(x=alt.X("Season:N", sort=waves, title=None, axis=alt.Axis(labelAngle=0, orient="top")),
                                                      y=alt.Y("Group:N", sort=TB, title=None))
            plot(b2.mark_rect(stroke="white", strokeWidth=2).encode(color=alt.Color("Average:Q", scale=alt.Scale(domain=[2.8, 3.5, 4.2], range=[ORANGE_, "#F3F3F3", BLUE_]), legend=None))
                 + b2.mark_text(fontSize=14, fontWeight="bold", color="#282828").encode(text=alt.Text("Average:Q", format=".1f")), 190)
        else:
            st.caption(f"Each group needs at least {k} answers to be shown.")
    _later_box(later)


def _themes(source, v, waves, sel, k):
    """Theme explorer: what Mentors said in their spoken answers, by season."""
    later = []
    names = {t["id"]: t["name"] for t in db.get_published("codebook")[1]["themes"]}
    tg = demo_tags() if source == "demo" else live_tags()
    if tg.empty:
        st.info("No tagged answers yet. Spoken answers become themes once they are transcribed and tagged. This happens automatically once transcription and tagging are turned on in Settings. "
                "Switch to the demo data above to see how this tab will look.")
        later.append(("Why people left", f"needs {k}+ exit interviews with the same main reason"))
        _why_left(source, names, k, later)
        _later_box(later)
        return
    if source == "demo":
        st.caption("Themes come from synthetic spoken answers tagged for the demo. The quotes are illustrative examples written for the demo, not real Mentors.")
    else:
        st.caption("Themes come from spoken answers tagged automatically by AI. Answers the AI flags for support, or that could not be tagged, go to the Review queue for a person.")
    tw = [w for w in waves if w in set(tg["wave"])]
    den = tg.groupby("wave")["mentor"].nunique()
    mode = st.radio("Show", ["What is hard", "What is working"], horizontal=True, key="theme_mode")
    val = "Negative" if mode == "What is hard" else "Positive"
    sub = tg[(tg["valence"] == val) & (tg["theme"] != "T10")]
    cnt = sub.groupby(["wave", "theme"])["mentor"].nunique().reset_index(name="n")
    BINS = [(0.25, "25% or more"), (0.20, "20-24%"), (0.15, "15-19%"), (0.10, "10-14%"), (0.0, "Under 10%")]
    ORDER = ["Under 10%", "10-14%", "15-19%", "20-24%", "25% or more"]
    PALETTE = (["#FDE8DF", "#F9C3AD", "#F59C78", "#EC6237", "#B8431B"] if val == "Negative"
               else ["#E3F1FB", "#BDDDF5", "#8CC5EE", "#4CA7E8", "#1A74B8"])
    bucket = lambda sh: next(lab for lo, lab in BINS if sh >= lo)
    recs = []
    for w in tw:
        for t_, nm in names.items():
            if t_ == "T10":
                continue
            n_ = cnt[(cnt["wave"] == w) & (cnt["theme"] == t_)]["n"].sum()
            if den.get(w, 0) >= k and n_ >= k:
                recs.append({"Season": w, "Theme": THEME_SHORT.get(t_, nm), "Share": n_ / den[w], "Mentors": int(n_), "Bucket": bucket(n_ / den[w])})
    what = "was hard" if val == "Negative" else "is working"
    if recs:
        st.subheader("Share of Mentors mentioning each theme")
        st.caption(f"Share of Mentors who mentioned the theme when asked what {what} for them that season. Darker means more Mentors. A blank box means fewer than {k}.")
        hm = pd.DataFrame(recs)
        base = alt.Chart(hm).encode(x=alt.X("Season:N", sort=tw, title=None, axis=alt.Axis(labelAngle=0, orient="top")),
                                    y=alt.Y("Theme:N", sort=alt.EncodingSortField("Share", op="sum", order="descending"), title=None, axis=alt.Axis(labelLimit=340)))
        rect = base.mark_rect(stroke="white", strokeWidth=2).encode(
            color=alt.Color("Bucket:N", sort=ORDER, scale=alt.Scale(domain=ORDER, range=PALETTE),
                            legend=alt.Legend(title="Share of Mentors:", orient="bottom", direction="horizontal", symbolType="square", symbolSize=260,
                                              titleFontSize=13, labelFontSize=12)))
        txt = base.mark_text(fontSize=13, fontWeight="bold").encode(
            text=alt.Text("Share:Q", format=".0%"),
            color=alt.condition(alt.datum.Bucket == "25% or more", alt.value("white"), alt.value("#282828")))
        plot(rect + txt, 430)
        st.caption("Life changes outside work are counted in totals only and never shown here.")
    else:
        later.append(("Theme heatmap", f"needs {k}+ Mentors mentioning the same theme in a season"))

    wi = tw.index(sel) if sel in tw else None
    grow = None
    if wi is not None and wi > 0:
        pr = tw[wi - 1]
        ch = []
        for t_, nm in names.items():
            if t_ == "T10":
                continue

            def share(w, t_=t_):
                n_ = cnt[(cnt["wave"] == w) & (cnt["theme"] == t_)]["n"].sum()
                return n_ / den[w] if den.get(w, 0) >= k and n_ >= k else None
            a, b = share(pr), share(sel)
            if a is not None and b is not None:
                ch.append({"Theme": THEME_SHORT.get(t_, nm), "Change": b - a})
        grow = (pr, pd.DataFrame(ch)) if ch else None
    if grow is None:
        later.append(("Themes growing or shrinking", f"needs two seasons of tagged answers with {k}+ Mentors on a theme"))
    else:
        pr, cd = grow
        st.subheader("Concerns growing or shrinking?" if val == "Negative" else "Strengths growing or shrinking?")
        better = (cd["Change"] <= 0) if val == "Negative" else (cd["Change"] >= 0)
        cd["Direction"] = np.where(better, "Moving in a better direction", "Moving in a worse direction")
        bar = alt.Chart(cd).mark_bar().encode(
            x=alt.X("Change:Q", axis=alt.Axis(format="+%"), title="Fewer Mentors mentioned it   <   0   >   More Mentors mentioned it"),
            y=alt.Y("Theme:N", sort=alt.EncodingSortField("Change", order="descending"), title=None, axis=alt.Axis(labelLimit=340)),
            color=alt.Color("Direction:N", scale=alt.Scale(domain=["Moving in a better direction", "Moving in a worse direction"], range=[BLUE_, ORANGE_]),
                            legend=alt.Legend(orient="bottom", direction="horizontal", symbolType="square", symbolSize=260)))
        plot(bar + bar.mark_text(align="left", dx=4, color="#282828").encode(text=alt.Text("Change:Q", format="+.0%")), 380)
        st.caption(f"Change in the share of Mentors mentioning each theme, {pr} to {sel}. "
                   + ("Blue is good news (fewer concerns). Orange is a concern growing." if val == "Negative" else "Blue is good news (a strength growing). Orange is a strength fading."))

    qs = sub[(sub["quote"] != "") & (sub["aggregate_only"].astype(int) == 0)]
    tl = [t_ for t_ in names if t_ != "T10" and (qs["theme"] == t_).any()]
    if not tl:
        later.append(("In their words", "needs tagged answers with quotes"))
    else:
        st.subheader("In their words")
        st.caption("Pick a theme and a season to read excerpts from Mentors' answers.")
        c1, c2 = st.columns(2)
        tsel = c1.selectbox("Theme", tl, format_func=lambda t_: f"{names[t_]} ({int((qs['theme'] == t_).sum())})")
        ssel = c2.selectbox("Season", ["All seasons"] + list(reversed(tw)), index=(1 + list(reversed(tw)).index(sel)) if sel in tw else 0)
        pick = qs[qs["theme"] == tsel]
        if ssel != "All seasons":
            pick = pick[pick["wave"] == ssel]
        if len(pick) and pick["mentor"].nunique() < k:
            st.caption(f"Fewer than {k} Mentors have excerpts here, so they are hidden to protect privacy.")
        else:
            uniq = (pick.sort_values("t", ascending=False).groupby("quote", sort=False)
                    .agg(wave=("wave", "first"), n=("mentor", "nunique")).reset_index().head(8))
            for _, row in uniq.iterrows():
                more = f" · similar answers from {row['n']} Mentors" if row["n"] >= k else ""
                st.markdown(f"> “{row['quote']}”  \n> <span style='color:#555'>{row['wave']}{more}</span>", unsafe_allow_html=True)
        st.caption("Excerpts are copied exactly from answers. Names are never shown. Anything that raised a safety concern is handled by a person outside the dashboard.")

    _why_left(source, names, k, later)
    _later_box(later)


def _why_left(source, names, k, later):
    if source == "demo":
        ex = demo_exits()["top_reason"].map(lambda t_: names.get(t_, t_)).value_counts()
    else:
        resp = pd.DataFrame(db.fetch_responses())
        ex = resp[(resp["qtype"] == "Checklist") & (resp["checklist_top"].fillna("") != "")]["checklist_top"].value_counts() if not resp.empty else pd.Series(dtype=int)
    shown = ex[ex >= k]
    if shown.empty:
        if not any(n == "Why people left" for n, _ in later):
            later.append(("Why people left", f"needs {k}+ exit interviews with the same main reason"))
        return
    st.subheader("Why people left")
    st.caption(f"Main reason chosen by the {int(ex.sum())} Mentors who completed an exit interview. Record what you do about them on the Pilot year page under Our response.")
    bar = shown.rename_axis("Reason").reset_index(name="Mentors")
    ch = alt.Chart(bar).mark_bar(color=ORANGE_).encode(x=alt.X("Mentors:Q", title=None), y=alt.Y("Reason:N", sort="-x", title=None, axis=alt.Axis(labelLimit=340)))
    plot(ch + ch.mark_text(align="left", dx=4, color="#282828").encode(text="Mentors:Q"), 280)
    if int((ex < k).sum()):
        st.caption(f"{int((ex < k).sum())} other reason(s) with fewer than {k} answers are hidden.")


# ---------------------------------------------------------------- support signals
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
    st.title("Support signals")
    stage_note()
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

    ui.section("Across the whole group", "Purpose: see how many Mentors may benefit from a supportive check-in. How to use: use the counts to plan support. These are signals to offer help, not judgments about people.")
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
            ui.section(f"Priority mix in {sel}", "The share of Mentors in each priority group this season.", level=3)
            dn = pd.DataFrame({"Priority": ["High", "Medium", "Low"], "Mentors": [int(counts.get(b, 0)) for b in ("High", "Medium", "Low")]})
            dn = dn[dn["Mentors"] >= k]
            arc = alt.Chart(dn).mark_arc(innerRadius=70, stroke="white", strokeWidth=3).encode(
                theta=alt.Theta("Mentors:Q"), color=alt.Color("Priority:N", scale=alt.Scale(domain=list(ui.BAND), range=list(ui.BAND.values())),
                                                              legend=alt.Legend(orient="bottom", direction="horizontal")))
            plot(arc, 280)
        with d2:
            ui.section("Priority mix by season", "Is the group needing attention growing or shrinking?", level=3)
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
            ui.section("Share of Mentors with a signal, by season", "The line shows the percentage with a High or Medium signal each season.", level=3)
            if len(t):
                plot(alt.Chart(t).mark_line(point=alt.OverlayMarkDef(size=70), color=ORANGE_, strokeWidth=3).encode(
                    x=alt.X("Season:N", sort=waves, title=None, axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("Share with a signal:Q", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, max(0.5, float(t["Share with a signal"].max()) + 0.05)]), title=None)), 280)
        with r_:
            ui.section(f"Which signals show up most in {sel}", "Which indicator rules are triggered most often. Use it to decide what to work on as a team.", level=3)
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
        ui.section("How well do these rules work in the demo data?", "Purpose: show how the rules would have performed. How to use: compare each bar with the dashed line (the overall rate). A bar above the line means that group was more likely to leave. Demo data only.")
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
    ui.section("Mentors who might benefit from a check-in", "Purpose: help the program admin decide who to reach out to. How to use: start with High priority, read what stands out, offer a conversation, then mark it as offered.")
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
