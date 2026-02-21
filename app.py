import os
import json
from datetime import date, timedelta
from flask import Flask, render_template, redirect, url_for, request, jsonify
from models import db, PracticeSession, Stats

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    "sqlite:///" + os.path.join(basedir, "hebrew_trainer.db"),
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

# ── Pronunciation reference data ──────────────────────────────────────────────

CONSONANTS = [
    ("א",    "Alef",   "Silent / glottal stop",    "אָב (av)"),
    ("בּ",   "Bet",    "b (as in boy)",             "בַּיִת (bayit)"),
    ("ב",    "Vet",    "v (as in vine)",             "כָּתַב (katav)"),
    ("גּ",   "Gimel",  "g (as in go)",              "גַּן (gan)"),
    ("דּ",   "Dalet",  "d (as in dog)",             "דֶּלֶת (delet)"),
    ("ה",    "He",     "h (as in hat)",              "הַר (har)"),
    ("ו",    "Vav",    "v (as in vine)",             "וָרֹד (varod)"),
    ("ז",    "Zayin",  "z (as in zoo)",              "זְמַן (zman)"),
    ("ח",    "Chet",   "ch (guttural)",              "חַם (cham)"),
    ("ט",    "Tet",    "t (as in top)",              "טוֹב (tov)"),
    ("י",    "Yod",    "y (as in yes)",              "יַד (yad)"),
    ("כּ",   "Kaf",    "k (as in kite)",             "כֶּלֶב (kelev)"),
    ("כ/ך",  "Chaf",   "ch (guttural)",              "לֶחֶם (lechem)"),
    ("ל",    "Lamed",  "l (as in lamp)",             "לֵב (lev)"),
    ("מ/ם",  "Mem",    "m (as in mom)",              "מַיִם (mayim)"),
    ("נ/ן",  "Nun",    "n (as in no)",               "נֵר (ner)"),
    ("ס",    "Samech", "s (as in sun)",              "סֵפֶר (sefer)"),
    ("ע",    "Ayin",   "Silent / glottal",           "עַיִן (ayin)"),
    ("פּ",   "Pe",     "p (as in pen)",              "פֶּה (pe)"),
    ("פ/ף",  "Fe",     "f (as in fan)",              "כָּף (kaf)"),
    ("צ/ץ",  "Tsadi",  "ts (as in cats)",            "צָהֳרַיִם (tsohorayim)"),
    ("ק",    "Qof",    "k (as in kite)",             "קוֹל (kol)"),
    ("ר",    "Resh",   "r (uvular, like French r)",  "רֹאשׁ (rosh)"),
    ("שׁ",   "Shin",   "sh (as in ship)",            "שָׁלוֹם (shalom)"),
    ("שׂ",   "Sin",    "s (as in sun)",              "שָׂדֶה (sade)"),
    ("תּ/ת", "Tav",    "t (as in top)",              "תּוֹרָה (Torah)"),
]

VOWELS = [
    ("בָ",  "Kamatz",       "ah",         "שָׁלוֹם",   "fāther"),
    ("בַ",  "Patach",       "ah",         "יַד",       "fāther"),
    ("בֶ",  "Segol",        "eh",         "מֶלֶךְ",     "bĕd"),
    ("בֵ",  "Tsere",        "ay",         "בֵּית",     "sāy"),
    ("בִ",  "Hiriq",        "ee",         "מִי",       "sēe"),
    ("בֹ",  "Holam",        "oh",         "תּוֹרָה",    "gō"),
    ("בוּ", "Shuruq",       "oo",         "שׁוּב",      "mōn"),
    ("בֻ",  "Qibbuts",      "oo",         "כֻּלָּם",    "mōn"),
    ("בְ",  "Shva",         "e / silent", "בְּרֵאשִׁית", "abōut"),
    ("בֱ",  "Hataf Segol",  "eh",         "אֱלֹהִים",  "bĕd"),
    ("בֲ",  "Hataf Patach", "ah",         "חֲנֻכָּה",  "fāther"),
    ("בֳ",  "Hataf Kamatz", "oh",         "עׇבְדָה",  "gō"),
]

# ── Per-mode metadata (display order, colour key, target minutes) ───────────────────────────
DRILL_META = [
    ("consonants", "rose",   10),
    ("letters",    "indigo", 12),
    ("syllables",  "violet", 15),
    ("phrases",    "sky",    15),
    ("prayer",     "amber",  20),
    ("siddur",     "teal",   15),
]

# ── Per-mode recommended time ──────────────────────────────────────────────────────────────────────────────
MODE_RECOMMENDED = {
    "consonants": "10 min",
    "letters":    "10–15 min",
    "syllables":  "15 min",
    "phrases":    "15 min",
    "prayer":     "20 min",
    "siddur":     "10–20 min",
}

# ── 8-Week Training Plan ────────────────────────────────────────────────────────────
WEEKLY_PLAN = [
    {
        "week": 1,
        "phase": "Month 1 — Automatic Decoding",
        "phase_short": "Month 1",
        "title": "Eliminate Letter & Vowel Lag",
        "weeks_label": "Weeks 1–2",
        "milestone": "No hesitation on individual letters",
        "recommended_modes": ["consonants", "letters", "syllables", "siddur"],
        "daily_minutes": "45–60",
        "structure": [
            {"time": "10 min", "label": "Warm-up",
             "body": "Rapid-fire aleph-bet — forward then random order. Include final letters: ך ם ן ף ץ. Time yourself — aim for smooth, not rushed."},
            {"time": "10–15 min", "label": "Vowel Drills",
             "body": "Every letter with all 8 vowels: Kamatz · Patach · Tzere · Segol · Cholam · Kubutz/Shuruk · Chirik · Sheva. Don’t think — just sound it. Example: בָ בַ בֶ בֵ בִ בֹ בוּ בֻ בְ"},
            {"time": "15 min", "label": "Syllable Blending",
             "body": "Two- and three-letter clusters: בָּר · שֶׁמ · מַלְ · תּוֹר. Train your eye to grab clusters at once — not letter by letter."},
            {"time": "10–15 min", "label": "Slow Siddur Reading",
             "body": "Take 3–5 lines from a siddur. Read slowly but continuously. No translating. No stopping unless you truly freeze."},
        ],
        "tip": "On hard days: 20 minutes and you win. Consistency beats motivation every time.",
    },
    {
        "week": 2,
        "phase": "Month 1 — Automatic Decoding",
        "phase_short": "Month 1",
        "title": "Eliminate Letter & Vowel Lag",
        "weeks_label": "Weeks 1–2",
        "milestone": "No thinking about letters",
        "recommended_modes": ["consonants", "letters", "syllables", "siddur"],
        "daily_minutes": "45–60",
        "structure": [
            {"time": "10 min", "label": "Warm-up — Random Order",
             "body": "Aleph-bet in random order using the shuffle button. Beat yesterday’s smoothness, not speed. The goal is zero lag."},
            {"time": "10–15 min", "label": "Vowel Drills — Scrambled",
             "body": "Use the 🔀 Vowels button to drill vowels in random order. No fixed sequence — force instant recognition without the pattern crutch."},
            {"time": "15 min", "label": "Syllable Blending",
             "body": "Focus on clusters you hesitated on yesterday. Mark them mentally and return to them. Build automaticity."},
            {"time": "10–15 min", "label": "Slow Siddur Reading",
             "body": "Try to read one more line than yesterday without stopping. Eyes and mouth only — no translation happening in your head."},
        ],
        "tip": "If you freeze on a letter — say it slowly once, then move on immediately. Never linger.",
    },
    {
        "week": 3,
        "phase": "Month 1 — Automatic Decoding",
        "phase_short": "Month 1",
        "title": "Increase Speed and Flow",
        "weeks_label": "Weeks 3–4",
        "milestone": "Can read a full paragraph without stopping",
        "recommended_modes": ["syllables", "phrases", "siddur"],
        "daily_minutes": "45–60",
        "structure": [
            {"time": "10–15 min", "label": "Timed Reading",
             "body": "Pick a paragraph from a siddur or Tehillim. Read 5 minutes nonstop. Mark where you end. Try to get further tomorrow."},
            {"time": "10 min", "label": "Sheva & Dagesh Focus",
             "body": "Open vs. closed syllables. Hard/soft letters: בּ vs. ב · פּ vs. פ · כּ vs. כ. Slow drill on anything that still trips you."},
            {"time": "15 min", "label": "Phrase Reading",
             "body": "Read in 3–5 word chunks using the Phrase Flow drill. Your eyes should move ahead of your mouth — practice that gap."},
            {"time": "10 min", "label": "Out-Loud Projection",
             "body": "Read slightly louder than comfortable. Confidence improves fluency. Speak like you mean it."},
        ],
        "tip": "Your eyes should always be one word ahead of your mouth. This is the skill you’re building now.",
    },
    {
        "week": 4,
        "phase": "Month 1 — Automatic Decoding",
        "phase_short": "Month 1",
        "title": "Increase Speed and Flow",
        "weeks_label": "Weeks 3–4",
        "milestone": "Can read Tehillim smoothly at a slow, steady pace",
        "recommended_modes": ["syllables", "phrases", "siddur"],
        "daily_minutes": "45–60",
        "structure": [
            {"time": "10–15 min", "label": "Timed Reading",
             "body": "Increase to 7 minutes nonstop. Track progress line by line — you should be covering more ground than week 3."},
            {"time": "10 min", "label": "Sheva & Dagesh Refinement",
             "body": "Return to any letters or vowels that still cause hesitation. Drill them in isolation until they fire automatically."},
            {"time": "15 min", "label": "Phrase Chunking",
             "body": "Read full phrases without pausing mid-phrase. Flow is more important than perfection at this stage."},
            {"time": "10 min", "label": "Projection + Pace Push",
             "body": "Read at a pace slightly faster than feels comfortable. You are pushing your floor upward."},
        ],
        "tip": "Slow and steady is fine — but never stop mid-phrase. Push through and self-correct on the move.",
    },
    {
        "week": 5,
        "phase": "Month 2 — Siddur Fluency",
        "phase_short": "Month 2",
        "title": "Structured Prayer Fluency",
        "weeks_label": "Weeks 5–6",
        "milestone": "Shema and Ashrei mostly fluid",
        "recommended_modes": ["phrases", "prayer", "siddur"],
        "daily_minutes": "45–60",
        "structure": [
            {"time": "10 min", "label": "Speed Drill",
             "body": "Read one prayer paragraph repeatedly until smooth — Shema, Ashrei, or V’ahavta. No hesitation allowed."},
            {"time": "10 min", "label": "Record Yourself",
             "body": "Read a paragraph aloud and play it back. Notice: hesitations, misread vowels, dropped letters. Don’t judge — observe."},
            {"time": "20 min", "label": "Full Section Run-Through",
             "body": "Read one full prayer start to finish without stopping. Even if imperfect — don’t break rhythm."},
            {"time": "5–10 min", "label": "Cold Read",
             "body": "Open to a random page of a siddur and read. No preparation. This trains true sight reading."},
        ],
        "tip": "Don’t break rhythm even when you make a mistake. Flow over perfection, every time.",
    },
    {
        "week": 6,
        "phase": "Month 2 — Siddur Fluency",
        "phase_short": "Month 2",
        "title": "Structured Prayer Fluency",
        "weeks_label": "Weeks 5–6",
        "milestone": "Shema and Ashrei mostly fluid",
        "recommended_modes": ["phrases", "prayer", "siddur"],
        "daily_minutes": "45–60",
        "structure": [
            {"time": "10 min", "label": "Speed Drill — Amidah",
             "body": "Drill the Amidah opening paragraphs. Repeat until you can read without slowing down."},
            {"time": "10 min", "label": "Record & Compare",
             "body": "Record a longer passage. Compare to week 5 — notice real improvements. You are further than you think."},
            {"time": "20 min", "label": "Shema + Ashrei as One Unit",
             "body": "Read Shema + V’ahavta as one continuous unit, then Ashrei. No gap between them."},
            {"time": "5–10 min", "label": "Cold Read",
             "body": "A different random page each session. Unknown text is the real test."},
        ],
        "tip": "You are building identity here, not just skill. Show up even on hard days — especially then.",
    },
    {
        "week": 7,
        "phase": "Month 2 — Siddur Fluency",
        "phase_short": "Month 2",
        "title": "Simulated Shul Pace",
        "weeks_label": "Weeks 7–8",
        "milestone": "Can keep up in weekday Shacharit",
        "recommended_modes": ["prayer", "siddur"],
        "daily_minutes": "45–60",
        "structure": [
            {"time": "20 min · 3×/week", "label": "Synagogue Simulation",
             "body": "Set a timer for 20 minutes. Read continuously as if you are in synagogue. No pauses, no corrections — keep moving."},
            {"time": "20 min · 2×/week", "label": "Audio Follow-Along",
             "body": "Read along with a recording of the prayer. Stay slightly ahead of the audio — you lead, the recording follows."},
            {"time": "5–10 min · 1×/week", "label": "Rabbi or Fluent Reader",
             "body": "Have a fluent reader listen to you read for 5–10 minutes. This is your weekly accountability check."},
        ],
        "tip": "Minimum viable habit: 20 minutes no matter what. On hard days — 20 minutes and you win.",
    },
    {
        "week": 8,
        "phase": "Month 2 — Siddur Fluency",
        "phase_short": "Month 2",
        "title": "Simulated Shul Pace",
        "weeks_label": "Weeks 7–8",
        "milestone": "Can keep up reasonably in weekday Shacharit",
        "recommended_modes": ["prayer", "siddur"],
        "daily_minutes": "45–60",
        "structure": [
            {"time": "20 min · 3×/week", "label": "Full Shacharit Run-Through",
             "body": "Read the complete weekday morning service start to finish at near-minyan pace."},
            {"time": "20 min · 2×/week", "label": "Audio Pace Challenge",
             "body": "Stay ahead of the audio recording this week. If you can consistently lead it — you are ready."},
            {"time": "10 min · 1×/week", "label": "Rabbi Check-In",
             "body": "Read aloud for your rabbi or study partner. Celebrate how far you have come since week 1."},
        ],
        "tip": "On strong days: 60 minutes. On hard days: 20 minutes and you win. You have built something real.",
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_drills():
    drills_path = os.path.join(basedir, "drills.json")
    with open(drills_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_or_create_stats():
    stats = Stats.query.first()
    if not stats:
        stats = Stats(
            current_streak=0,
            longest_streak=0,
            total_minutes=0,
            last_practice_date=None,
        )
        db.session.add(stats)
        db.session.commit()
    return stats


def get_current_week_info():
    """Returns (current_week_number, start_date, week_data_dict)."""
    first_session = PracticeSession.query.order_by(PracticeSession.date.asc()).first()
    today = date.today()

    if first_session:
        days_elapsed = (today - first_session.date).days
        current_week = min(8, days_elapsed // 7 + 1)
        start_date = first_session.date
    else:
        current_week = 1
        start_date = None

    # Aggregate sessions per week
    sessions_all = PracticeSession.query.all()
    week_data = {}
    if first_session:
        for s in sessions_all:
            wk = min(8, (s.date - first_session.date).days // 7 + 1)
            if wk not in week_data:
                week_data[wk] = {"days": set(), "minutes": 0}
            week_data[wk]["days"].add(s.date)
            week_data[wk]["minutes"] += s.minutes
        for k in week_data:
            week_data[k]["days"] = len(week_data[k]["days"])

    return current_week, start_date, week_data


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    stats = get_or_create_stats()
    recent_sessions = (
        PracticeSession.query
        .order_by(PracticeSession.date.desc(), PracticeSession.id.desc())
        .limit(10)
        .all()
    )
    current_week, start_date, _ = get_current_week_info()
    current_week_plan = WEEKLY_PLAN[current_week - 1]

    today = date.today()
    today_sessions = PracticeSession.query.filter_by(date=today).all()
    today_by_mode = {}
    for s in today_sessions:
        today_by_mode[s.mode] = today_by_mode.get(s.mode, 0) + s.minutes
    today_drill_rows = [
        {
            "mode":   mode,
            "color":  color,
            "done":   today_by_mode.get(mode, 0),
            "target": target,
            "pct":    min(100, round(today_by_mode.get(mode, 0) / target * 100)),
        }
        for mode, color, target in DRILL_META
    ]

    return render_template(
        "dashboard.html",
        stats=stats,
        recent_sessions=recent_sessions,
        current_week=current_week,
        current_week_plan=current_week_plan,
        start_date=start_date,
        today_drill_rows=today_drill_rows,
    )


@app.route("/drill/<mode>")
def drill(mode):
    valid_modes = ["letters", "syllables", "phrases", "prayer", "consonants", "siddur"]
    if mode not in valid_modes:
        return redirect(url_for("dashboard"))
    content = [] if mode == "siddur" else load_drills().get(mode, [])
    recommended_time = MODE_RECOMMENDED.get(mode, "15 min")
    return render_template("drill.html", mode=mode, content=content,
                           recommended_time=recommended_time,
                           vowels=VOWELS if mode == 'letters' else [])


@app.route("/pronunciation")
def pronunciation():
    return render_template(
        "pronunciation.html",
        consonants=CONSONANTS,
        vowels=VOWELS,
    )


@app.route("/complete", methods=["POST"])
def complete_session():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    mode = data.get("mode", "letters")
    minutes = max(1, int(data.get("minutes", 1)))
    today = date.today()
    yesterday = today - timedelta(days=1)

    # Persist session
    new_session = PracticeSession(date=today, mode=mode, minutes=minutes)
    db.session.add(new_session)
    db.session.flush()  # assigns PK without full commit
    session_id = new_session.id

    # Update global stats
    stats = get_or_create_stats()
    stats.total_minutes += minutes

    # Streak logic
    if stats.last_practice_date is None:
        stats.current_streak = 1
    elif stats.last_practice_date == yesterday:
        stats.current_streak += 1
    elif stats.last_practice_date == today:
        pass  # Already practiced today — do nothing
    else:
        stats.current_streak = 1  # Missed at least one day — reset

    stats.last_practice_date = today
    if stats.current_streak > stats.longest_streak:
        stats.longest_streak = stats.current_streak

    db.session.commit()
    return jsonify({"success": True, "session_id": session_id, "redirect": url_for("dashboard")})


@app.route("/guide")
def guide():
    stats = get_or_create_stats()
    current_week, start_date, week_data = get_current_week_info()
    return render_template(
        "guide.html",
        weekly_plan=WEEKLY_PLAN,
        current_week=current_week,
        start_date=start_date,
        week_data=week_data,
        stats=stats,
    )


@app.route("/upload_recording/<int:session_id>", methods=["POST"])
def upload_recording(session_id):
    session_obj = PracticeSession.query.get(session_id)
    if not session_obj:
        return jsonify({"error": "Session not found"}), 404
    audio_file = request.files.get("audio")
    if not audio_file:
        return jsonify({"error": "No audio file"}), 400
    recordings_dir = os.path.join(basedir, "static", "recordings")
    os.makedirs(recordings_dir, exist_ok=True)
    filename = f"session_{session_id}.webm"
    audio_file.save(os.path.join(recordings_dir, filename))
    session_obj.recording_path = f"recordings/{filename}"
    db.session.commit()
    return jsonify({"success": True})


@app.route("/sessions")
def sessions():
    mode_filter = request.args.get("mode", "all")
    query = PracticeSession.query.order_by(
        PracticeSession.date.desc(), PracticeSession.id.desc()
    )
    if mode_filter != "all":
        query = query.filter_by(mode=mode_filter)
    all_sessions = query.all()
    modes = ["consonants", "letters", "syllables", "phrases", "prayer", "siddur"]
    return render_template(
        "sessions.html",
        sessions=all_sessions,
        mode_filter=mode_filter,
        modes=modes,
    )


@app.route("/sessions/<int:session_id>/delete", methods=["POST"])
def delete_session(session_id):
    session_obj = PracticeSession.query.get(session_id)
    if session_obj:
        stats = get_or_create_stats()
        stats.total_minutes = max(0, stats.total_minutes - session_obj.minutes)
        if session_obj.recording_path:
            filepath = os.path.join(basedir, "static", session_obj.recording_path)
            if os.path.exists(filepath):
                os.remove(filepath)
        db.session.delete(session_obj)
        db.session.commit()
    return redirect(request.referrer or url_for("sessions"))


@app.route("/sessions/delete_mode/<mode>", methods=["POST"])
def delete_mode_sessions(mode):
    mode_sessions = PracticeSession.query.filter_by(mode=mode).all()
    stats = get_or_create_stats()
    for s in mode_sessions:
        stats.total_minutes = max(0, stats.total_minutes - s.minutes)
        if s.recording_path:
            filepath = os.path.join(basedir, "static", s.recording_path)
            if os.path.exists(filepath):
                os.remove(filepath)
        db.session.delete(s)
    db.session.commit()
    return redirect(url_for("sessions", mode=mode))


# ── Bootstrap ─────────────────────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()
    # Migrate: add recording_path if column is missing (SQLite-safe)
    from sqlalchemy import inspect as sa_inspect, text as sa_text
    _cols = [c["name"] for c in sa_inspect(db.engine).get_columns("practice_session")]
    if "recording_path" not in _cols:
        with db.engine.connect() as _conn:
            _conn.execute(sa_text(
                "ALTER TABLE practice_session ADD COLUMN recording_path VARCHAR(255)"
            ))
            _conn.commit()
    os.makedirs(os.path.join(basedir, "static", "recordings"), exist_ok=True)

if __name__ == "__main__":
    app.run(debug=True)
