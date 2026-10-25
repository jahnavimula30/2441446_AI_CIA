"""AI Quiz Arena: DSC401-6 Artificial Intelligence (Units I & II).

Run locally:  streamlit run app.py
"""
import os
import random
import time
from datetime import datetime

import pandas as pd
import streamlit as st

from questions import POINTS, QUESTIONS, TOPICS

st.set_page_config(page_title="AI Quiz Arena", page_icon="🧠", layout="centered")

BY_ID = {q["id"]: q for q in QUESTIONS}
LB_FILE = os.path.join("data", "leaderboard.csv")
LIFELINES = {"hint": 3, "fifty": 2, "skip": 2}
PICK = "-- select --"
DIFF_ICON = {"Easy": "🟢", "Medium": "🟡", "Hard": "🔴"}


# ───────────────────────────── helpers ─────────────────────────────
def fmt(x):
    return f"{x:g}"


def norm(t):
    return " ".join(str(t).lower().replace("-", " ").replace("_", " ").split()).strip(" .")


def init_state():
    s = st.session_state
    defaults = dict(stage="setup", player="Player", quiz=[], idx=0, results=[], lifelines=dict(LIFELINES),
                    used={}, opts={}, removed={}, submitted=False, warn="", deadline=None, limit=0,
                    streak=0, saved=False, q_start=0.0, last=None, diff="Mixed")
    for k, v in defaults.items():
        if k not in s:
            s[k] = v


def current_q():
    s = st.session_state
    return BY_ID[s.quiz[s.idx]]


def display_options(q):
    """Options in display order (MCQ shuffled once; 50-50 removals applied)."""
    s = st.session_state
    qid = q["id"]
    if qid not in s.opts:
        o = [r for _, r in q["pairs"]] if q["input"] == "match" else list(q["options"])
        if q["input"] in ("mcq", "match"):
            random.shuffle(o)
        s.opts[qid] = o
    return [o for o in s.opts[qid] if o not in s.removed.get(qid, [])]


def correct_text(q):
    if q["input"] in ("mcq", "ar", "tf"):
        return q["options"][q["answer"]]
    if q["input"] == "fill":
        return q["answer"][0]
    return "\n".join(f"- {l} → **{r}**" for l, r in q["pairs"])


def fmt_resp(q, r):
    if r is None:
        return "-"
    if q["input"] == "match":
        return "; ".join(f"{l} → {v}" for l, v in r.items())
    return str(r)


def collect(q):
    s = st.session_state
    k, qid = q["input"], q["id"]
    if k in ("mcq", "ar", "tf"):
        return s.get(f"ans_{qid}")
    if k == "fill":
        return (s.get(f"ans_{qid}") or "").strip() or None
    r = {l: s.get(f"m_{qid}_{i}") for i, (l, _) in enumerate(q["pairs"])}
    return r if all(v and v != PICK for v in r.values()) else None


def is_correct(q, r):
    k = q["input"]
    if k in ("mcq", "ar", "tf"):
        return r == q["options"][q["answer"]]
    if k == "fill":
        return norm(r) in {norm(a) for a in q["answer"]}
    return all(r.get(l) == rt for l, rt in q["pairs"])


# ───────────────────────────── game logic (callbacks) ─────────────────────────────
def new_timer():
    s = st.session_state
    s.q_start = time.time()
    s.deadline = s.q_start + s.limit if s.limit else None


def start_quiz():
    s = st.session_state
    pool = [q for q in QUESTIONS if q["topic"] in s.w_topics and (s.w_diff == "Mixed" or q["difficulty"] == s.w_diff)]
    if not pool:
        s.warn = "No questions match these filters. Choose more topics or another level."
        return
    chosen = random.sample(pool, min(s.w_n, len(pool)))
    s.update(stage="quiz", player=(s.w_name.strip() or "Player"), quiz=[q["id"] for q in chosen], idx=0,
             results=[], lifelines=dict(LIFELINES), used={}, opts={}, removed={}, submitted=False, warn="",
             streak=0, saved=False, last=None, diff=s.w_diff, limit=int(s.w_time))
    new_timer()


def record(q, resp, timed_out=False, skipped=False):
    s = st.session_state
    used = s.used.get(q["id"], set())
    maxp = POINTS[q["difficulty"]]
    correct = bool(not timed_out and not skipped and resp is not None and is_correct(q, resp))
    earned = maxp * (0.5 if used else 1) if correct else 0
    if not skipped:
        s.streak = s.streak + 1 if correct else 0
    s.last = dict(id=q["id"], topic=q["topic"], difficulty=q["difficulty"], format=q["format"], correct=correct,
                  earned=earned, max=0 if skipped else maxp, answer=fmt_resp(q, resp), timed_out=timed_out,
                  skipped=skipped, lifelines=", ".join(sorted(used)) or "-",
                  seconds=round(time.time() - s.q_start, 1))
    s.results.append(s.last)
    s.submitted = True


def submit():
    q = current_q()
    r = collect(q)
    if r is None:
        st.session_state.warn = "Please give an answer before submitting."
        return
    st.session_state.warn = ""
    record(q, r)


def use_lifeline(kind):
    s = st.session_state
    q = current_q()
    if s.lifelines[kind] <= 0:
        return
    s.lifelines[kind] -= 1
    if kind == "skip":
        record(q, None, skipped=True)
        return
    s.used.setdefault(q["id"], set()).add(kind)
    if kind == "fifty":
        correct = q["options"][q["answer"]]
        wrong = [o for o in display_options(q) if o != correct]
        s.removed[q["id"]] = random.sample(wrong, 2)


def next_q():
    s = st.session_state
    s.idx += 1
    s.submitted, s.warn = False, ""
    if s.idx >= len(s.quiz):
        s.stage = "result"
    else:
        new_timer()


def reset_game():
    st.session_state.stage = "setup"
    st.session_state.warn = ""


# ───────────────────────────── leaderboard ─────────────────────────────
def load_lb():
    try:
        return pd.read_csv(LB_FILE)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame(columns=["Name", "Score", "Max", "Percent", "Level", "Questions", "Date"])


def save_score(total, maxp):
    s = st.session_state
    row = dict(Name=s.player, Score=round(total, 1), Max=maxp, Percent=round(100 * total / maxp, 1) if maxp else 0,
               Level=s.diff, Questions=len(s.quiz), Date=datetime.now().strftime("%Y-%m-%d %H:%M"))
    try:
        os.makedirs("data", exist_ok=True)
        pd.concat([load_lb(), pd.DataFrame([row])], ignore_index=True).to_csv(LB_FILE, index=False)
    except OSError:
        st.warning("Could not write the leaderboard file on this host.")


# ───────────────────────────── pages ─────────────────────────────
def render_setup():
    st.title("🧠 AI Quiz Arena")
    st.caption("DSC401-6 Artificial Intelligence · Units I & II · pick your settings and test yourself!")
    if st.session_state.warn:
        st.warning(st.session_state.warn)
    st.text_input("Your name", key="w_name", placeholder="e.g. Asha")
    c1, c2 = st.columns(2)
    c1.selectbox("Difficulty level", ["Mixed", "Easy", "Medium", "Hard"], key="w_diff")
    c2.selectbox("Timer per question", [0, 30, 45, 60, 90], index=2, key="w_time",
                 format_func=lambda x: "No timer" if x == 0 else f"{x} seconds")
    st.multiselect("Topics", TOPICS, default=TOPICS, key="w_topics")
    st.slider("Number of questions (capped by availability)", 5, len(QUESTIONS), 15, key="w_n")
    st.markdown("**Scoring:** Easy = 1 pt · Medium = 2 pts · Hard = 3 pts. Using a **Hint** or **50-50** halves the "
                "points for that question. A **Skip** costs nothing but earns nothing. "
                f"Lifelines per game: 💡 Hint ×{LIFELINES['hint']}, ✂️ 50-50 ×{LIFELINES['fifty']}, "
                f"⏭️ Skip ×{LIFELINES['skip']}.")
    st.button("🚀 Start quiz", type="primary", on_click=start_quiz)


def _timer_tick():
    s = st.session_state
    if s.submitted or s.deadline is None:
        return
    rem = int(s.deadline - time.time() + 0.999)
    if rem <= 0:
        record(current_q(), collect(current_q()), timed_out=True)
        st.rerun()
    st.progress(min(rem / s.limit, 1.0), text=f"⏱️ {rem}s left")


def render_input(q):
    k, qid = q["input"], q["id"]
    if k in ("mcq", "ar", "tf"):
        st.radio("Choose one:", display_options(q), index=None, key=f"ans_{qid}")
    elif k == "fill":
        st.text_input("Your answer:", key=f"ans_{qid}", placeholder="Type the missing word")
    else:
        rights = display_options(q)
        for i, (left, _) in enumerate(q["pairs"]):
            st.selectbox(left, [PICK] + rights, key=f"m_{qid}_{i}")


def render_feedback(q):
    s = st.session_state
    r = s.last
    if r["skipped"]:
        st.info("⏭️ Skipped. No points gained or lost.")
    elif r["timed_out"]:
        st.warning("⏰ Time's up! No points for this question.")
    elif r["correct"]:
        half = " (halved because a lifeline was used)" if r["lifelines"] != "-" else ""
        st.success(f"✅ Correct! +{fmt(r['earned'])} pt{half}")
    else:
        st.error("❌ Not quite.")
    if not r["correct"]:
        if not r["skipped"]:
            st.markdown(f"**Your answer:** {r['answer']}")
        st.markdown("**Correct answer:**  \n" + correct_text(q))
    st.info("💡 " + q["explanation"])
    last = s.idx + 1 >= len(s.quiz)
    st.button("🏁 Finish quiz" if last else "➡️ Next question", type="primary", on_click=next_q)


def render_quiz():
    s = st.session_state
    q, n = current_q(), len(s.quiz)
    st.progress((s.idx + (1 if s.submitted else 0)) / n, text=f"Question {s.idx + 1} of {n}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Score", fmt(sum(r["earned"] for r in s.results)))
    c2.metric("Streak", f"🔥 {s.streak}")
    c3.metric("Answered", f"{len(s.results)}/{n}")
    tags = [q["topic"], q["format"], f"{DIFF_ICON[q['difficulty']]} {q['difficulty']} ({POINTS[q['difficulty']]} pt)"]
    if q["real_world"]:
        tags.append("🌍 Real-world")
    st.caption(" · ".join(tags))
    st.markdown(f"**Q{s.idx + 1}.** {q['question']}")

    if s.submitted:
        render_feedback(q)
        return
    if s.deadline:
        st.fragment(run_every=1)(_timer_tick)()
    render_input(q)
    used = s.used.get(q["id"], set())
    if "hint" in used:
        st.info("💡 Hint: " + q["hint"])
    if s.warn:
        st.warning(s.warn)
    b1, b2, b3, b4 = st.columns(4)
    b1.button("✅ Submit", type="primary", on_click=submit)
    b2.button(f"💡 Hint ({s.lifelines['hint']})", on_click=use_lifeline, args=("hint",),
              disabled=s.lifelines["hint"] <= 0 or "hint" in used)
    b3.button(f"✂️ 50-50 ({s.lifelines['fifty']})", on_click=use_lifeline, args=("fifty",),
              disabled=q["input"] not in ("mcq", "ar") or s.lifelines["fifty"] <= 0 or "fifty" in used)
    b4.button(f"⏭️ Skip ({s.lifelines['skip']})", on_click=use_lifeline, args=("skip",),
              disabled=s.lifelines["skip"] <= 0)


def render_result():
    s = st.session_state
    df = pd.DataFrame(s.results)
    total, maxp = df["earned"].sum(), df["max"].sum()
    pct = 100 * total / maxp if maxp else 0
    if not s.saved:
        save_score(total, maxp)
        s.saved = True
    st.title("🏁 Final result")
    badge = ("AI Grandmaster 🏆" if pct >= 90 else "Search Specialist 🚀" if pct >= 75
             else "Rational Agent 🤖" if pct >= 50 else "Keep exploring 📚")
    st.subheader(f"{s.player}, you are a **{badge}**")
    if pct >= 80:
        st.balloons()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Score", f"{fmt(total)} / {fmt(maxp)}")
    c2.metric("Percentage", f"{pct:.1f}%")
    c3.metric("Correct", f"{int(df['correct'].sum())}/{len(df)}")
    c4.metric("Avg time", f"{df['seconds'].mean():.0f}s")

    st.markdown("#### Performance by topic")
    t = df[df["max"] > 0].groupby("topic").agg(earned=("earned", "sum"), mx=("max", "sum"))
    t["Accuracy %"] = (100 * t["earned"] / t["mx"]).round(1)
    st.bar_chart(t["Accuracy %"], horizontal=True)

    st.markdown("#### Review")
    for i, r in enumerate(s.results, 1):
        q = BY_ID[r["id"]]
        icon = "⏭️" if r["skipped"] else "✅" if r["correct"] else "❌"
        with st.expander(f"{icon} Q{i} · {q['topic']} · {q['difficulty']}"):
            st.markdown(q["question"])
            st.markdown(f"**Your answer:** {r['answer']}")
            st.markdown("**Correct answer:**  \n" + correct_text(q))
            st.info(q["explanation"])
    col1, col2 = st.columns(2)
    col1.download_button("⬇️ Download my results (CSV)", df.to_csv(index=False), "my_quiz_results.csv", "text/csv")
    col2.button("🔄 Play again", on_click=reset_game)


def render_leaderboard():
    st.title("🏆 Leaderboard")
    lb = load_lb()
    if lb.empty:
        st.info("No scores yet. Finish a quiz to appear here!")
        return
    lb = lb.sort_values(["Percent", "Score"], ascending=False).head(10).reset_index(drop=True)
    lb.index += 1
    st.dataframe(lb)
    st.caption("Top 10 by percentage. Note: on free cloud hosting the file may reset when the app restarts.")


def render_bank():
    st.title("📚 Question Bank")
    if st.session_state.stage == "quiz":
        st.warning("The question bank is locked while a quiz is in progress. Finish or quit the quiz first.")
        return
    df = pd.DataFrame(QUESTIONS)
    df["Correct answer"] = [correct_text(q).replace("\n", " ") for q in QUESTIONS]
    c1, c2, c3 = st.columns(3)
    topic = c1.selectbox("Topic", ["All"] + TOPICS)
    kind = c2.selectbox("Format", ["All"] + sorted(df["format"].unique()))
    level = c3.selectbox("Level", ["All", "Easy", "Medium", "Hard"])
    show = st.checkbox("Show correct answers", value=False)
    if topic != "All":
        df = df[df["topic"] == topic]
    if kind != "All":
        df = df[df["format"] == kind]
    if level != "All":
        df = df[df["difficulty"] == level]
    cols = ["id", "topic", "format", "difficulty", "question"] + (["Correct answer", "explanation"] if show else [])
    st.caption(f"{len(df)} question(s) shown · {len(QUESTIONS)} in total · "
               f"{sum(q['real_world'] for q in QUESTIONS)} real-world · {sum(q['search'] for q in QUESTIONS)} search/state-space")
    st.dataframe(df[cols], hide_index=True)


def render_about():
    st.title("ℹ️ About")
    st.markdown(f"""
**AI Quiz Arena** is an interactive quiz for *DSC401-6 Artificial Intelligence, Units I & II*, built with
Python and Streamlit.

- **{len(QUESTIONS)} questions** across {len(TOPICS)} topics, in 7 formats: MCQ, True/False, Assertion-Reason,
  Fill in the Blanks, Match the Following, Scenario and Problem-solving.
- **Features:** random questions, 3 difficulty levels, per-question timer, progress bar, instant feedback with
  explanations, lifelines (Hint, 50-50, Skip), streak counter, topic-wise analysis, leaderboard and CSV export.
- **Scoring:** Easy 1 · Medium 2 · Hard 3. Lifeline use halves the points of that question.
""")


# ───────────────────────────── main ─────────────────────────────
init_state()
st.sidebar.title("🧠 AI Quiz Arena")
page = st.sidebar.radio("Menu", ["🎮 Play", "🏆 Leaderboard", "📚 Question Bank", "ℹ️ About"])
if st.session_state.stage == "quiz":
    st.sidebar.button("🚪 Quit current quiz", on_click=reset_game)

if page == "🎮 Play":
    {"setup": render_setup, "quiz": render_quiz, "result": render_result}[st.session_state.stage]()
elif page == "🏆 Leaderboard":
    render_leaderboard()
elif page == "📚 Question Bank":
    render_bank()
else:
    render_about()
