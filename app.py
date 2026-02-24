import os
import re
import json
from functools import wraps
from datetime import date, timedelta, datetime, timezone
from flask import Flask, render_template, redirect, url_for, request, jsonify, flash, session
from models import db, User, PracticeSession, Stats

# ── Timezone offset ───────────────────────────────────────────────────────────
# Server runs UTC; app records dates in PST (UTC-8).
# Change TZ_OFFSET_HOURS to -7 during daylight saving (PDT) if needed.
TZ_OFFSET_HOURS = -8

def today_local() -> date:
    """Return the current date in the configured local timezone (default PST)."""
    return (datetime.now(timezone.utc) + timedelta(hours=TZ_OFFSET_HOURS)).date()

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    "sqlite:///" + os.path.join(basedir, "hebrew_trainer.db"),
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

@app.template_filter('fmt_duration')
def fmt_duration_filter(total_seconds):
    """Format a total-seconds value into a human-readable duration string."""
    secs = int(total_seconds or 0)
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    if m > 0:
        return f"{m}m {s:02d}s"
    return f"{s}s"

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
    ("בוֹ", "Holam Male",   "oh",         "תּוֹרָה",    "gō"),
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
    ("vowelfire",  "purple", 10),
    ("words",  "violet", 15),
    ("phrases",    "sky",    15),
    ("prayer",     "amber",  20),
    ("siddur",     "teal",   15),
]

# ── Map plan structure block labels → drill modes ────────────────────────────────
LABEL_TO_MODE = {
    "rapid-fire consonants":      "consonants",
    "vowel drills":                "letters",
    "rapid-fire vowels":           "vowelfire",
    "rapid-fire vowels (warm-up)": "vowelfire",
    "warm-up":                     "vowelfire",
    "final warm-up":               "vowelfire",
    "word reading":                "words",
    "phrase flow":                 "phrases",
    "phrase flow (projection)":    "phrases",
    "prayer simulation":           "prayer",
    "siddur reading":              "siddur",
    "siddur reading (4\u00d7/week)": "siddur",
    "fast siddur (2\u00d7/week)":   "siddur",
}

def _plan_targets(week_plan):
    """Return {mode: minutes} derived from week_plan['structure'] blocks."""
    targets = {}
    for block in week_plan.get("structure", []):
        mode = LABEL_TO_MODE.get(block["label"].lower())
        if mode:
            m = re.match(r'(\d+)', block["time"])
            if m:
                targets[mode] = targets.get(mode, 0) + int(m.group(1))
    return targets


def _user_targets(user, week_plan):
    """Apply user's daily_minutes / siddur_minutes overrides to the plan targets.

    Logic:
      - siddur_minutes is a MINIMUM. Actual siddur = max(user.siddur_minutes, plan siddur).
        If the plan calls for more siddur than the user's minimum, the plan wins.
      - remaining = user.daily_minutes - actual_siddur  (if daily_minutes set)
        otherwise remaining = sum of plan's non-siddur block times.
      - remaining is distributed across all non-siddur modes that appear in the
        plan, proportionally to their plan times (minimum 1 min each).
    """
    base = _plan_targets(week_plan)
    daily       = getattr(user, 'daily_minutes',  0) or 0
    siddur_pref = getattr(user, 'siddur_minutes', 0) or 0

    if not daily and not siddur_pref:
        return base

    # siddur_pref is a floor — plan can push it higher
    siddur_mins = max(siddur_pref, base.get('siddur', 0))
    non_siddur  = {k: v for k, v in base.items() if k != 'siddur'}
    ns_total    = sum(non_siddur.values()) or 1

    if daily > 0:
        remaining = max(0, daily - siddur_mins)
    else:
        remaining = ns_total   # only siddur floor set — keep non-siddur proportions

    result = {}
    if siddur_mins > 0:
        result['siddur'] = siddur_mins
    for mode, mins in non_siddur.items():
        result[mode] = max(1, round(mins / ns_total * remaining))
    return result

# ── Per-mode recommended time ──────────────────────────────────────────────────────────────────────────────
MODE_RECOMMENDED = {
    "consonants": "10 min",
    "letters":    "10–15 min",
    "vowelfire":  "10 min",
    "words":  "15 min",
    "phrases":    "15 min",
    "prayer":     "20 min",
    "siddur":     "10–20 min",
}

# ── Rapid-fire vowel combinations ──────────────────────────────────────────────
_VOWELFIRE_CONSONANTS = [
    'א','ב','ג','ד','ה','ז','ח','ט','י','כ','ל','מ','נ','ס','ע','פ','צ','ק','ר','שׁ','ת'
]
_VOWELFIRE_MARKS = [
    '\u05B8',          # kamatz      (āh)
    '\u05B7',          # patach      (ah)
    '\u05B6',          # segol       (eh)
    '\u05B5',          # tsere       (ay)
    '\u05B4',          # hiriq       (ee)
    '\u05B9',          # holam       (oh)
    '\u05D5\u05B9',    # holam male  (oh)  — consonant + vav + holam dot
    '\u05BB',          # qibbuts     (oo)
    '\u05D5\u05BC',    # shuruq      (oo)  — consonant + vav + dagesh
    '\u05B0',          # shva        (silent/e)
]

def generate_vowelfire_content():
    """Return every base consonant paired with every vowel suffix."""
    return [c + v for c in _VOWELFIRE_CONSONANTS for v in _VOWELFIRE_MARKS]

# ── Training Plans (8 / 12 / 16 weeks) ─────────────────────────────────────────────
# Structure per session: Neural Warm-Up → Fluency Building → Liturgical Conditioning
# Siddur is the anchor — everything else supports it.

_PLAN_8 = [
    # ── Weeks 1–2: Stability + Page Familiarity ──────────────────────────────
    {
        "week": 1,
        "phase": "Intensive Fluency — Stability + Page Familiarity",
        "phase_short": "Weeks 1–2",
        "title": "Stability + Page Familiarity",
        "weeks_label": "Weeks 1–2",
        "milestone": "No hesitation on vowels — eyes keep moving even when imperfect",
        "recommended_modes": ["consonants", "letters", "vowelfire", "words", "phrases", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Consonants",
             "body": "Full aleph-bet in random order. Zero lag — just sound. No thinking."},
            {"time": "10 min", "label": "Vowel Drills",
             "body": "Every letter with all 8 vowels: Kamatz · Patach · Segol · Tsere · Hiriq · Holam · Shuruq · Shva. Don't think — just sound it."},
            {"time": "10 min", "label": "Rapid-Fire Vowels",
             "body": "Random consonant + vowel combinations. No pattern — force instant recognition on every card."},
            {"time": "10 min", "label": "Word Reading",
             "body": "Short prayer words: בָּרוּךְ · שָׁלוֹם · יִשְׂרָאֵל. Train your eye to grab whole syllable clusters at once."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Read 3–5 word phrases without stopping mid-phrase. Flow over accuracy at this stage."},
            {"time": "15 min", "label": "Siddur Reading",
             "body": "Open to your practice passage. Read aloud continuously — no pausing to translate. Eyes and mouth only."},
        ],
        "tip": "The Siddur is the goal. Everything else is warm-up.",
    },
    {
        "week": 2,
        "phase": "Intensive Fluency — Stability + Page Familiarity",
        "phase_short": "Weeks 1–2",
        "title": "Stability + Page Familiarity",
        "weeks_label": "Weeks 1–2",
        "milestone": "Eyes moving continuously through full Siddur lines",
        "recommended_modes": ["consonants", "letters", "vowelfire", "words", "phrases", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Consonants",
             "body": "Beat yesterday's smoothness, not your speed. Zero hesitation is the only metric."},
            {"time": "10 min", "label": "Vowel Drills",
             "body": "Vowels in scrambled order — no fixed sequence. Force instant recognition without pattern crutch."},
            {"time": "10 min", "label": "Rapid-Fire Vowels",
             "body": "Focus on any combination that paused you yesterday. Return until it fires automatically."},
            {"time": "10 min", "label": "Word Reading",
             "body": "Focus on words you hesitated on. Mark them mentally and return. Build automaticity."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Increase to 4–6 word phrases without breaking."},
            {"time": "15 min", "label": "Siddur Reading",
             "body": "Try to cover one more line than yesterday without stopping. Push through hesitations — self-correct on the move."},
        ],
        "tip": "If you freeze — say it slowly once, then immediately move on. Never linger.",
    },
    # ── Weeks 3–4: Blending Speed ─────────────────────────────────────────────
    {
        "week": 3,
        "phase": "Intensive Fluency — Blending Speed",
        "phase_short": "Weeks 3–4",
        "title": "Blending Speed",
        "weeks_label": "Weeks 3–4",
        "milestone": "Phrase chunking improves — less backtracking, more forward momentum",
        "recommended_modes": ["consonants", "vowelfire", "words", "phrases", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Consonants",
             "body": "Maintenance warm-up — should be fully automatic at this point."},
            {"time": "10 min", "label": "Rapid-Fire Vowels",
             "body": "Push the pace. You should be recognizing combinations before consciously processing them."},
            {"time": "10 min", "label": "Word Reading",
             "body": "Multi-syllable words. Train your eye to grab whole word shapes."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Read in 3–5 word chunks. Your eyes should move ahead of your mouth — practice that gap."},
            {"time": "10 min", "label": "Prayer Simulation",
             "body": "Read one prayer passage as if you are in shul. No pausing, no backtracking. Rhythm over perfection."},
            {"time": "15 min", "label": "Siddur Reading",
             "body": "Increase to a full paragraph of continuous reading. Note where you stall — that is tomorrow's focus."},
        ],
        "tip": "Your eyes should always be one word ahead of your mouth. Practice that gap deliberately.",
    },
    {
        "week": 4,
        "phase": "Intensive Fluency — Blending Speed",
        "phase_short": "Weeks 3–4",
        "title": "Blending Speed",
        "weeks_label": "Weeks 3–4",
        "milestone": "Full Siddur paragraph read smoothly without stopping",
        "recommended_modes": ["vowelfire", "words", "phrases", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Consonants",
             "body": "Warm-up only — should feel effortless at this point."},
            {"time": "10 min", "label": "Rapid-Fire Vowels",
             "body": "Any combination that still hesitates — drill it to automaticity."},
            {"time": "10 min", "label": "Word Reading",
             "body": "Read slightly faster than comfortable. You are pushing your floor upward."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Full phrases without pausing mid-phrase. Flow is more important than perfection."},
            {"time": "10 min", "label": "Prayer Simulation",
             "body": "Read 2–3 prayer passages back to back. No break — build endurance."},
            {"time": "15 min", "label": "Siddur Reading",
             "body": "Try a full section (Shema or Ashrei) without stopping. Mark your furthest point."},
        ],
        "tip": "Never stop mid-phrase. Push through and self-correct on the move.",
    },
    # ── Weeks 5–6: Prayer Integration ────────────────────────────────────────
    {
        "week": 5,
        "phase": "Intensive Fluency — Prayer Integration",
        "phase_short": "Weeks 5–6",
        "title": "Prayer Integration",
        "weeks_label": "Weeks 5–6",
        "milestone": "Shema and Ashrei read smoothly and continuously",
        "recommended_modes": ["vowelfire", "words", "phrases", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Warm-up — should be automatic now. If not, extend to 10 minutes."},
            {"time": "10 min", "label": "Word Reading",
             "body": "Siddur vocabulary you encounter most. Build a mental library of common prayer words."},
            {"time": "15 min", "label": "Prayer Simulation",
             "body": "Shema + V'ahavta as one continuous unit. No gap between them. Rhythm is everything."},
            {"time": "20 min", "label": "Siddur Reading",
             "body": "Read one full prayer from start to finish without stopping. Even if imperfect — do not break rhythm."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Cold read: open to a random page and read for 10 minutes. No preparation. This is the real training."},
        ],
        "tip": "Don't break rhythm even when you make a mistake. Flow over perfection, every time.",
    },
    {
        "week": 6,
        "phase": "Intensive Fluency — Prayer Integration",
        "phase_short": "Weeks 5–6",
        "title": "Prayer Integration",
        "weeks_label": "Weeks 5–6",
        "milestone": "Two prayers read back to back without stopping",
        "recommended_modes": ["vowelfire", "phrases", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Pure warm-up. Fire through — zero thinking."},
            {"time": "10 min", "label": "Word Reading",
             "body": "Return to any words that still trip you. Drill until automatic."},
            {"time": "15 min", "label": "Prayer Simulation",
             "body": "Amidah opening paragraphs — repeat until smooth. Then Ashrei. Prayer-by-prayer automaticity."},
            {"time": "20 min", "label": "Siddur Reading",
             "body": "Two prayers back to back: Shema + V'ahavta, then Ashrei. No gap. Read like you are in shul."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Cold read on a different page each session. Unknown text is the real test."},
        ],
        "tip": "You are building identity here, not just skill. Show up even on hard days — especially then.",
    },
    # ── Weeks 7–8: Endurance Phase ────────────────────────────────────────────
    {
        "week": 7,
        "phase": "Intensive Fluency — Endurance Phase",
        "phase_short": "Weeks 7–8",
        "title": "Endurance Phase",
        "weeks_label": "Weeks 7–8",
        "milestone": "30 minutes continuous Siddur reading without anxiety",
        "recommended_modes": ["vowelfire", "words", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Warm-up only. Should feel instant."},
            {"time": "15 min", "label": "Prayer Simulation",
             "body": "Full Shacharit opening at near-minyan pace. No stopping. Stay slightly ahead of the congregation."},
            {"time": "30 min", "label": "Siddur Reading",
             "body": "30 minutes continuous — this is your main work. Set a timer. Read. Do not stop. This is endurance training."},
            {"time": "10 min", "label": "Word Reading",
             "body": "Cool-down: words you struggled with today. Reinforce them."},
        ],
        "tip": "Minimum viable habit: 20 minutes no matter what. On hard days — 20 minutes and you win.",
    },
    {
        "week": 8,
        "phase": "Intensive Fluency — Endurance Phase",
        "phase_short": "Weeks 7–8",
        "title": "Endurance Phase",
        "weeks_label": "Weeks 7–8",
        "milestone": "Can keep up in weekday Shacharit at minyan pace",
        "recommended_modes": ["vowelfire", "words", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Final warm-up. Automatic. Instant."},
            {"time": "15 min", "label": "Prayer Simulation",
             "body": "Full weekday Shacharit at pace. If you can stay ahead of the text — you are ready."},
            {"time": "30 min", "label": "Siddur Reading",
             "body": "Complete weekday morning service start to finish at near-minyan pace. This is your graduation test."},
            {"time": "10 min", "label": "Word Reading",
             "body": "Any remaining weak spots. Reinforce them."},
        ],
        "tip": "On strong days: 60 minutes. On hard days: 20 minutes and you win. You have built something real.",
    },
]

_PLAN_12 = [
    # ── Weeks 1–4: Automaticity + Exposure ───────────────────────────────────
    {
        "week": 1,
        "phase": "Balanced Mastery — Automaticity + Exposure",
        "phase_short": "Weeks 1–4",
        "title": "Automaticity + Exposure",
        "weeks_label": "Weeks 1–4",
        "milestone": "Letters and vowels firing automatically — no conscious processing",
        "recommended_modes": ["consonants", "letters", "vowelfire", "words", "phrases", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Consonants",
             "body": "Full aleph-bet in random order. Zero lag — just sound."},
            {"time": "10 min", "label": "Vowel Drills",
             "body": "Every consonant with all 8 vowels. Don't think — sound it."},
            {"time": "10 min", "label": "Rapid-Fire Vowels",
             "body": "Random combinations. Force instant recognition on every card."},
            {"time": "10 min", "label": "Word Reading",
             "body": "Short prayer words — train your eye to grab clusters."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "3–5 word chunks. Flow over accuracy."},
            {"time": "15 min", "label": "Siddur Reading",
             "body": "Open to your passage. Read aloud continuously. No translating."},
        ],
        "tip": "The Siddur is the goal. Everything else is warm-up.",
    },
    {
        "week": 2,
        "phase": "Balanced Mastery — Automaticity + Exposure",
        "phase_short": "Weeks 1–4",
        "title": "Automaticity + Exposure",
        "weeks_label": "Weeks 1–4",
        "milestone": "Eyes moving forward through Siddur lines without hesitation",
        "recommended_modes": ["consonants", "letters", "vowelfire", "words", "phrases", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Consonants",
             "body": "Random order — beat yesterday's smoothness, not speed."},
            {"time": "10 min", "label": "Vowel Drills",
             "body": "Scrambled vowel order. No pattern — force recognition."},
            {"time": "10 min", "label": "Rapid-Fire Vowels",
             "body": "Return to any combination that paused you yesterday."},
            {"time": "10 min", "label": "Word Reading",
             "body": "Hesitation words — drill until automatic."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Increase to 4–6 word phrases without breaking."},
            {"time": "15 min", "label": "Siddur Reading",
             "body": "One more line than yesterday without stopping."},
        ],
        "tip": "If you freeze — say it slowly once, then immediately move on.",
    },
    {
        "week": 3,
        "phase": "Balanced Mastery — Automaticity + Exposure",
        "phase_short": "Weeks 1–4",
        "title": "Automaticity + Exposure",
        "weeks_label": "Weeks 1–4",
        "milestone": "Word shapes recognized instantly — no letter-by-letter scanning",
        "recommended_modes": ["consonants", "vowelfire", "words", "phrases", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Consonants",
             "body": "Maintenance warm-up — should be fully automatic."},
            {"time": "10 min", "label": "Rapid-Fire Vowels",
             "body": "Push the pace — recognize before consciously processing."},
            {"time": "10 min", "label": "Word Reading",
             "body": "Multi-syllable words. Grab whole word shapes."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Eyes ahead of mouth. Practice the gap deliberately."},
            {"time": "10 min", "label": "Phrase Flow (Projection)",
             "body": "Read slightly louder than comfortable. Projection improves rhythm and confidence."},
            {"time": "15 min", "label": "Siddur Reading",
             "body": "A full paragraph without stopping. Note where you stall."},
        ],
        "tip": "Eyes one word ahead of your mouth. Practice that gap every session.",
    },
    {
        "week": 4,
        "phase": "Balanced Mastery — Automaticity + Exposure",
        "phase_short": "Weeks 1–4",
        "title": "Automaticity + Exposure",
        "weeks_label": "Weeks 1–4",
        "milestone": "Full Siddur paragraph read smoothly without stopping",
        "recommended_modes": ["vowelfire", "words", "phrases", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Consonants",
             "body": "Warm-up — effortless at this point."},
            {"time": "10 min", "label": "Rapid-Fire Vowels",
             "body": "Remaining hesitations — drill to automaticity."},
            {"time": "10 min", "label": "Word Reading",
             "body": "Slightly faster than comfortable. Push your floor."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Full phrases — no mid-phrase pausing."},
            {"time": "10 min", "label": "Prayer Simulation",
             "body": "First prayer sim of the plan — Shema or Ashrei. Read as if in shul."},
            {"time": "15 min", "label": "Siddur Reading",
             "body": "Full section (Shema or Ashrei) without stopping."},
        ],
        "tip": "Never stop mid-phrase. Push through and self-correct on the move.",
    },
    # ── Weeks 5–8: Phrase & Prayer Lock-In ───────────────────────────────────
    {
        "week": 5,
        "phase": "Balanced Mastery — Phrase & Prayer Lock-In",
        "phase_short": "Weeks 5–8",
        "title": "Phrase & Prayer Lock-In",
        "weeks_label": "Weeks 5–8",
        "milestone": "Shema and Ashrei read fluidly without hesitation",
        "recommended_modes": ["vowelfire", "words", "phrases", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Automatic warm-up."},
            {"time": "15 min", "label": "Word Reading",
             "body": "Siddur vocabulary. Build a mental library of common prayer words."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "3–5 word chunks — eyes ahead of mouth."},
            {"time": "10 min", "label": "Prayer Simulation",
             "body": "Shema + V'ahavta as one unit. No gap between them."},
            {"time": "20 min", "label": "Siddur Reading",
             "body": "One full prayer start to finish without stopping. Add one 35-minute Siddur session this week."},
        ],
        "tip": "Add one 35-minute Siddur-only session this week. Just reading. Nothing else.",
    },
    {
        "week": 6,
        "phase": "Balanced Mastery — Phrase & Prayer Lock-In",
        "phase_short": "Weeks 5–8",
        "title": "Phrase & Prayer Lock-In",
        "weeks_label": "Weeks 5–8",
        "milestone": "Continuous reading across multiple prayers without stopping",
        "recommended_modes": ["vowelfire", "words", "phrases", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Warm-up."},
            {"time": "15 min", "label": "Word Reading",
             "body": "Any vocabulary still causing hesitation."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Cold read: random page, 10 minutes. No preparation."},
            {"time": "10 min", "label": "Prayer Simulation",
             "body": "Amidah opening paragraphs. Repeat until smooth."},
            {"time": "20 min", "label": "Siddur Reading",
             "body": "Two prayers back to back. No gap. Like you are in shul. Add one 35-minute session this week."},
        ],
        "tip": "Add one 35-minute Siddur-only session this week.",
    },
    {
        "week": 7,
        "phase": "Balanced Mastery — Phrase & Prayer Lock-In",
        "phase_short": "Weeks 5–8",
        "title": "Phrase & Prayer Lock-In",
        "weeks_label": "Weeks 5–8",
        "milestone": "Siddur reading for 20+ minutes without anxiety",
        "recommended_modes": ["vowelfire", "phrases", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Instant warm-up."},
            {"time": "15 min", "label": "Word Reading",
             "body": "Weak spots only — drill to automaticity."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Full phrases, no breaks."},
            {"time": "10 min", "label": "Prayer Simulation",
             "body": "Record yourself. Play it back. Notice — do not judge."},
            {"time": "20 min", "label": "Siddur Reading",
             "body": "20 minutes continuous. No pausing. Forward motion only."},
        ],
        "tip": "Don't break rhythm even when you make a mistake. Flow over perfection, every time.",
    },
    {
        "week": 8,
        "phase": "Balanced Mastery — Phrase & Prayer Lock-In",
        "phase_short": "Weeks 5–8",
        "title": "Phrase & Prayer Lock-In",
        "weeks_label": "Weeks 5–8",
        "milestone": "Shema, Ashrei, V'ahavta read as single continuous units",
        "recommended_modes": ["vowelfire", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Warm-up."},
            {"time": "15 min", "label": "Word Reading",
             "body": "Final vocabulary reinforcement."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Cold read — random page, no preparation."},
            {"time": "10 min", "label": "Prayer Simulation",
             "body": "Shema + V'ahavta + Ashrei as one unit. No gaps."},
            {"time": "20 min", "label": "Siddur Reading",
             "body": "35-minute Siddur session today — endurance training begins."},
        ],
        "tip": "You are building identity here, not just skill. Show up every day.",
    },
    # ── Weeks 9–12: Liturgical Confidence ────────────────────────────────────
    {
        "week": 9,
        "phase": "Balanced Mastery — Liturgical Confidence",
        "phase_short": "Weeks 9–12",
        "title": "Liturgical Confidence",
        "weeks_label": "Weeks 9–12",
        "milestone": "Near-minyan pace through complete prayer sections",
        "recommended_modes": ["vowelfire", "phrases", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Quick automatic warm-up."},
            {"time": "10 min", "label": "Prayer Simulation",
             "body": "Full opening of Shacharit at near-minyan pace. No stopping."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Cold read — different page each session."},
            {"time": "30 min", "label": "Siddur Reading",
             "body": "30 minutes continuous. This is your main conditioning work."},
            {"time": "5 min",  "label": "Word Reading",
             "body": "Cool-down — reinforce anything difficult from today."},
        ],
        "tip": "Measure endurance, not perfection. Sustained calm reading is the goal.",
    },
    {
        "week": 10,
        "phase": "Balanced Mastery — Liturgical Confidence",
        "phase_short": "Weeks 9–12",
        "title": "Liturgical Confidence",
        "weeks_label": "Weeks 9–12",
        "milestone": "30 minutes of continuous Siddur without anxiety",
        "recommended_modes": ["vowelfire", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Warm-up."},
            {"time": "10 min", "label": "Prayer Simulation",
             "body": "Amidah full opening — at pace until smooth."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Cold read. Unknown text is the real test."},
            {"time": "30 min", "label": "Siddur Reading",
             "body": "30 minutes. No stopping. Endurance is building."},
            {"time": "5 min",  "label": "Word Reading",
             "body": "Cool-down — weak spots only."},
        ],
        "tip": "Fluency comes in waves. You will plateau. Then suddenly improve. Stay steady.",
    },
    {
        "week": 11,
        "phase": "Balanced Mastery — Liturgical Confidence",
        "phase_short": "Weeks 9–12",
        "title": "Liturgical Confidence",
        "weeks_label": "Weeks 9–12",
        "milestone": "Shacharit sections at steady minyan-level pace",
        "recommended_modes": ["vowelfire", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Warm-up."},
            {"time": "10 min", "label": "Prayer Simulation",
             "body": "Simulate full minyan pace — stay ahead of the congregation."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Cold read. Record yourself once this week and compare to Week 5."},
            {"time": "30 min", "label": "Siddur Reading",
             "body": "30 minutes continuous. You are building something real."},
            {"time": "5 min",  "label": "Word Reading",
             "body": "Reinforcement only."},
        ],
        "tip": "Read slightly louder than comfortable. Projection builds confidence and rhythm.",
    },
    {
        "week": 12,
        "phase": "Balanced Mastery — Liturgical Confidence",
        "phase_short": "Weeks 9–12",
        "title": "Liturgical Confidence",
        "weeks_label": "Weeks 9–12",
        "milestone": "Minyan-level steadiness — confident weekday davening",
        "recommended_modes": ["vowelfire", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Final warm-up."},
            {"time": "10 min", "label": "Prayer Simulation",
             "body": "Complete Shacharit run-through at minyan pace."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Cold read on a page you have never practiced on."},
            {"time": "30 min", "label": "Siddur Reading",
             "body": "Complete weekday morning service. This is your graduation session."},
            {"time": "5 min",  "label": "Word Reading",
             "body": "Cool-down and reflection."},
        ],
        "tip": "On strong days: 60 minutes. On hard days: 20 minutes and you win. You have built something real.",
    },
]

_PLAN_16 = [
    # ── Phase 1 (Weeks 1–4): Decode + Anchor ─────────────────────────────────
    {
        "week": 1,
        "phase": "Deep Conditioning — Phase 1: Decode + Anchor",
        "phase_short": "Phase 1 (Wks 1–4)",
        "title": "Decode + Anchor",
        "weeks_label": "Weeks 1–4",
        "milestone": "Automatic letter and vowel recognition — zero conscious processing",
        "recommended_modes": ["consonants", "letters", "vowelfire", "words", "phrases", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Consonants",
             "body": "Full aleph-bet random. Zero hesitation."},
            {"time": "10 min", "label": "Vowel Drills",
             "body": "All 8 vowels on every letter. Don't think — sound it."},
            {"time": "10 min", "label": "Rapid-Fire Vowels",
             "body": "Random combinations — instant recognition."},
            {"time": "10 min", "label": "Word Reading",
             "body": "Short prayer words — grab whole clusters."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "3–5 word chunks. Flow over accuracy."},
            {"time": "15 min", "label": "Siddur Reading",
             "body": "Read aloud continuously. No translating."},
        ],
        "tip": "The Siddur is the goal. Everything else is warm-up.",
    },
    {
        "week": 2,
        "phase": "Deep Conditioning — Phase 1: Decode + Anchor",
        "phase_short": "Phase 1 (Wks 1–4)",
        "title": "Decode + Anchor",
        "weeks_label": "Weeks 1–4",
        "milestone": "Eyes moving continuously through Siddur lines",
        "recommended_modes": ["consonants", "letters", "vowelfire", "words", "phrases", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Consonants",
             "body": "Scrambled — beat smoothness, not speed."},
            {"time": "10 min", "label": "Vowel Drills",
             "body": "Scrambled order — no pattern crutch."},
            {"time": "10 min", "label": "Rapid-Fire Vowels",
             "body": "Return to any combination that paused you."},
            {"time": "10 min", "label": "Word Reading",
             "body": "Hesitation words — drill to automaticity."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "4–6 word phrases without breaking."},
            {"time": "15 min", "label": "Siddur Reading",
             "body": "One more line than yesterday."},
        ],
        "tip": "If you freeze — say it once, move on immediately.",
    },
    {
        "week": 3,
        "phase": "Deep Conditioning — Phase 1: Decode + Anchor",
        "phase_short": "Phase 1 (Wks 1–4)",
        "title": "Decode + Anchor",
        "weeks_label": "Weeks 1–4",
        "milestone": "Word shapes recognized as whole units, not letter sequences",
        "recommended_modes": ["consonants", "vowelfire", "words", "phrases", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Consonants",
             "body": "Maintenance — should be effortless."},
            {"time": "10 min", "label": "Rapid-Fire Vowels",
             "body": "Push pace — recognize before consciously processing."},
            {"time": "10 min", "label": "Word Reading",
             "body": "Multi-syllable words. Whole shapes."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Eyes ahead of mouth. Practice the gap."},
            {"time": "10 min", "label": "Phrase Flow (Projection)",
             "body": "Read louder than comfortable. Projection improves rhythm."},
            {"time": "15 min", "label": "Siddur Reading",
             "body": "Full paragraph — note where you stall."},
        ],
        "tip": "Eyes one word ahead of your mouth. Practice that gap deliberately.",
    },
    {
        "week": 4,
        "phase": "Deep Conditioning — Phase 1: Decode + Anchor",
        "phase_short": "Phase 1 (Wks 1–4)",
        "title": "Decode + Anchor",
        "weeks_label": "Weeks 1–4",
        "milestone": "Full Siddur paragraph without stopping",
        "recommended_modes": ["vowelfire", "words", "phrases", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Consonants",
             "body": "Warm-up — effortless."},
            {"time": "10 min", "label": "Rapid-Fire Vowels",
             "body": "Remaining hesitations — drill to automaticity."},
            {"time": "10 min", "label": "Word Reading",
             "body": "Slightly faster than comfortable."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Full phrases — no mid-phrase pausing."},
            {"time": "10 min", "label": "Prayer Simulation",
             "body": "First prayer sim — Shema or Ashrei."},
            {"time": "15 min", "label": "Siddur Reading",
             "body": "Full section (Shema or Ashrei) without stopping."},
        ],
        "tip": "Never stop mid-phrase. Push through, self-correct on the move.",
    },
    # ── Phase 2 (Weeks 5–8): Word-Level Automaticity ─────────────────────────
    {
        "week": 5,
        "phase": "Deep Conditioning — Phase 2: Word-Level Automaticity",
        "phase_short": "Phase 2 (Wks 5–8)",
        "title": "Word-Level Automaticity",
        "weeks_label": "Weeks 5–8",
        "milestone": "Siddur vocabulary recognized instantly — no syllable-by-syllable reading",
        "recommended_modes": ["vowelfire", "words", "phrases", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Automatic warm-up."},
            {"time": "20 min", "label": "Word Reading",
             "body": "Siddur vocabulary — prayer words that appear most frequently. Build a mental library of whole-word shapes."},
            {"time": "10 min", "label": "Prayer Simulation",
             "body": "Shema + V'ahavta as one continuous unit. No gap."},
            {"time": "20 min", "label": "Siddur Reading",
             "body": "Open to passage. Read continuously for 20 minutes. Forward motion only."},
            {"time": "5 min",  "label": "Phrase Flow",
             "body": "Cold read — random page for cool-down."},
        ],
        "tip": "Train in 3–5 word chunks. Avoid word-by-word reading.",
    },
    {
        "week": 6,
        "phase": "Deep Conditioning — Phase 2: Word-Level Automaticity",
        "phase_short": "Phase 2 (Wks 5–8)",
        "title": "Word-Level Automaticity",
        "weeks_label": "Weeks 5–8",
        "milestone": "Reading without sub-vocalizing individual letters",
        "recommended_modes": ["vowelfire", "words", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Warm-up."},
            {"time": "20 min", "label": "Word Reading",
             "body": "Prayer vocabulary — multi-syllable words as whole shapes."},
            {"time": "10 min", "label": "Prayer Simulation",
             "body": "Amidah opening — repeat until smooth."},
            {"time": "20 min", "label": "Siddur Reading",
             "body": "20 minutes continuous — eyes ahead of mouth."},
            {"time": "5 min",  "label": "Phrase Flow",
             "body": "Cold read — different page than yesterday."},
        ],
        "tip": "End every session with Siddur. The Siddur is the goal.",
    },
    {
        "week": 7,
        "phase": "Deep Conditioning — Phase 2: Word-Level Automaticity",
        "phase_short": "Phase 2 (Wks 5–8)",
        "title": "Word-Level Automaticity",
        "weeks_label": "Weeks 5–8",
        "milestone": "20 minutes continuous Siddur reading at steady pace",
        "recommended_modes": ["vowelfire", "words", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Instant warm-up."},
            {"time": "20 min", "label": "Word Reading",
             "body": "Vocabulary reinforcement — focus on what you still hesitate on."},
            {"time": "10 min", "label": "Prayer Simulation",
             "body": "Two prayers back to back. No gap."},
            {"time": "20 min", "label": "Siddur Reading",
             "body": "20 minutes — set a timer and do not stop."},
            {"time": "5 min",  "label": "Phrase Flow",
             "body": "Cold read cool-down."},
        ],
        "tip": "Don't translate. Train decoding. Meaning comes later.",
    },
    {
        "week": 8,
        "phase": "Deep Conditioning — Phase 2: Word-Level Automaticity",
        "phase_short": "Phase 2 (Wks 5–8)",
        "title": "Word-Level Automaticity",
        "weeks_label": "Weeks 5–8",
        "milestone": "Siddur reading feels like reading, not decoding",
        "recommended_modes": ["vowelfire", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Warm-up."},
            {"time": "20 min", "label": "Word Reading",
             "body": "Final word-level conditioning."},
            {"time": "10 min", "label": "Prayer Simulation",
             "body": "Record yourself. Compare to Week 4. You are further than you think."},
            {"time": "20 min", "label": "Siddur Reading",
             "body": "20 minutes — maintain pace regardless of errors."},
            {"time": "5 min",  "label": "Phrase Flow",
             "body": "Cold read."},
        ],
        "tip": "Accept imperfect days. Consistency beats intensity, every time.",
    },
    # ── Phase 3 (Weeks 9–12): Liturgical Rhythm ──────────────────────────────
    {
        "week": 9,
        "phase": "Deep Conditioning — Phase 3: Liturgical Rhythm",
        "phase_short": "Phase 3 (Wks 9–12)",
        "title": "Liturgical Rhythm",
        "weeks_label": "Weeks 9–12",
        "milestone": "Prayer-level reading speed with near-minyan rhythm",
        "recommended_modes": ["vowelfire", "phrases", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Warm-up."},
            {"time": "15 min", "label": "Prayer Simulation",
             "body": "Full Shacharit opening at near-minyan pace. No stopping."},
            {"time": "30 min", "label": "Siddur Reading",
             "body": "30 minutes continuous. Add one 40-minute session this week."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Cold read — unknown text trains true sight reading."},
        ],
        "tip": "Measure endurance, not perfection. Sustained calm reading is the goal.",
    },
    {
        "week": 10,
        "phase": "Deep Conditioning — Phase 3: Liturgical Rhythm",
        "phase_short": "Phase 3 (Wks 9–12)",
        "title": "Liturgical Rhythm",
        "weeks_label": "Weeks 9–12",
        "milestone": "30 minutes continuous reading — no anxiety, steady pace",
        "recommended_modes": ["vowelfire", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Warm-up."},
            {"time": "15 min", "label": "Prayer Simulation",
             "body": "Stay ahead of the congregation pace. You lead."},
            {"time": "30 min", "label": "Siddur Reading",
             "body": "30 minutes. Plus one 40-minute session this week."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Cold read."},
        ],
        "tip": "Fluency comes in waves. Plateau means improvement is near. Stay steady.",
    },
    {
        "week": 11,
        "phase": "Deep Conditioning — Phase 3: Liturgical Rhythm",
        "phase_short": "Phase 3 (Wks 9–12)",
        "title": "Liturgical Rhythm",
        "weeks_label": "Weeks 9–12",
        "milestone": "Complete Shacharit sections at steady pace without hesitation",
        "recommended_modes": ["vowelfire", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Warm-up."},
            {"time": "15 min", "label": "Prayer Simulation",
             "body": "Amidah + Ashrei back to back. No breaks."},
            {"time": "30 min", "label": "Siddur Reading",
             "body": "30 minutes — build toward 40-minute long sessions."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Record yourself once this week. Compare to Week 5."},
        ],
        "tip": "Read slightly louder than comfortable. Projection builds confidence.",
    },
    {
        "week": 12,
        "phase": "Deep Conditioning — Phase 3: Liturgical Rhythm",
        "phase_short": "Phase 3 (Wks 9–12)",
        "title": "Liturgical Rhythm",
        "weeks_label": "Weeks 9–12",
        "milestone": "Liturgical reading feels natural — sustained focus without effort",
        "recommended_modes": ["vowelfire", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",  "label": "Rapid-Fire Vowels",
             "body": "Warm-up."},
            {"time": "15 min", "label": "Prayer Simulation",
             "body": "Full opening at pace. If you can stay ahead — you are close."},
            {"time": "30 min", "label": "Siddur Reading",
             "body": "30 minutes standard + one 40-minute session this week."},
            {"time": "10 min", "label": "Phrase Flow",
             "body": "Cold read. Unknown text, no hesitation."},
        ],
        "tip": "You are building identity here, not just skill. Show up every day.",
    },
    # ── Phase 4 (Weeks 13–16): Minyan Conditioning ───────────────────────────
    {
        "week": 13,
        "phase": "Deep Conditioning — Phase 4: Minyan Conditioning",
        "phase_short": "Phase 4 (Wks 13–16)",
        "title": "Minyan Conditioning",
        "weeks_label": "Weeks 13–16",
        "milestone": "40-minute Siddur sessions at minyan pace without anxiety",
        "recommended_modes": ["vowelfire", "prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",    "label": "Rapid-Fire Vowels (warm-up)",
             "body": "4 training days: quick automatic warm-up before the main session."},
            {"time": "40–45 min","label": "Siddur Reading",
             "body": "4 days/week: 40–45 minutes continuous. This is minyan conditioning."},
            {"time": "10 min",   "label": "Prayer Simulation",
             "body": "4 days/week: final 10 minutes at pace to close the session."},
        ],
        "tip": "6 training days, 1 light day (30 min: 5 warm-up + 25 Siddur). Never zero.",
    },
    {
        "week": 14,
        "phase": "Deep Conditioning — Phase 4: Minyan Conditioning",
        "phase_short": "Phase 4 (Wks 13–16)",
        "title": "Minyan Conditioning",
        "weeks_label": "Weeks 13–16",
        "milestone": "Fast-pace sessions — leading the text, not following",
        "recommended_modes": ["prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",    "label": "Warm-up",
             "body": "4 standard days + 2 speed days."},
            {"time": "40–45 min","label": "Siddur Reading (4×/week)",
             "body": "Standard conditioning: 40–45 minutes continuous at minyan pace."},
            {"time": "35 min",   "label": "Fast Siddur (2×/week)",
             "body": "Speed session: 35 minutes at faster-than-comfortable pace. You lead. The congregation follows."},
        ],
        "tip": "Minimum viable habit: 20 minutes on hard days. Never zero.",
    },
    {
        "week": 15,
        "phase": "Deep Conditioning — Phase 4: Minyan Conditioning",
        "phase_short": "Phase 4 (Wks 13–16)",
        "title": "Minyan Conditioning",
        "weeks_label": "Weeks 13–16",
        "milestone": "Calm, automatic, confident fluency — no anxiety during davening",
        "recommended_modes": ["prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",    "label": "Warm-up",
             "body": "Quick. Automatic."},
            {"time": "40–45 min","label": "Siddur Reading (4×/week)",
             "body": "Long conditioning sessions. Sustained focus. No anxiety."},
            {"time": "35 min",   "label": "Fast Siddur (2×/week)",
             "body": "Push pace. Stay ahead of your own expectations."},
        ],
        "tip": "Your goal is sustained calm reading, not flawless pronunciation.",
    },
    {
        "week": 16,
        "phase": "Deep Conditioning — Phase 4: Minyan Conditioning",
        "phase_short": "Phase 4 (Wks 13–16)",
        "title": "Minyan Conditioning",
        "weeks_label": "Weeks 13–16",
        "milestone": "No anxiety, no hesitation, sustained focus — ready for consistent minyan participation",
        "recommended_modes": ["prayer", "siddur"],
        "daily_minutes": "60",
        "structure": [
            {"time": "5 min",    "label": "Final Warm-up",
             "body": "Automatic. Instant."},
            {"time": "40–45 min","label": "Siddur Reading (4×/week)",
             "body": "Complete weekday Shacharit start to finish. Graduation conditioning."},
            {"time": "35 min",   "label": "Fast Siddur (2×/week)",
             "body": "35 minutes at pace. If you can consistently lead the text — you are ready."},
        ],
        "tip": "On strong days: 60 minutes. On hard days: 20 minutes and you win. You have built something real.",
    },
]

ALL_WEEKLY_PLANS = {
    8:  _PLAN_8,
    12: _PLAN_12,
    16: _PLAN_16,
}

READING_TIPS = [
    {"n": 1,  "title": "Keep Your Eyes Moving",
     "body": "Do not go back unless you completely freeze. Forward motion builds fluency faster than perfection."},
    {"n": 2,  "title": "Don't Translate",
     "body": "This program trains decoding, not comprehension. Let meaning come later."},
    {"n": 3,  "title": "Slightly Louder Than Comfortable",
     "body": "Projection improves rhythm and confidence."},
    {"n": 4,  "title": "Accept Imperfect Days",
     "body": "Some days will feel slow. Consistency beats intensity."},
    {"n": 5,  "title": "Watch for Common Errors",
     "body": "Mixing \u05d1\u05bc / \u05d1 \u00b7 Mixing \u05e4 / \u05e4\u05bc \u00b7 Ignoring vowels under pressure \u00b7 Slowing down at sheva."},
    {"n": 6,  "title": "Train in Chunks",
     "body": "Try to read 3\u20135 words at a time. Avoid word-by-word reading."},
    {"n": 7,  "title": "End Every Session With Siddur",
     "body": "The Siddur is the goal. Always finish there."},
    {"n": 8,  "title": "If Overwhelmed",
     "body": "Do 5 minutes Rapid-Fire Vowels then 10 minutes Siddur. Then stop. That still counts."},
    {"n": 9,  "title": "Measure Endurance, Not Perfection",
     "body": "Your goal is sustained calm reading, not flawless pronunciation."},
    {"n": 10, "title": "Fluency Comes in Waves",
     "body": "You will plateau. Then suddenly improve. Stay steady."},
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_drills():
    drills_path = os.path.join(basedir, "drills.json")
    with open(drills_path, "r", encoding="utf-8") as f:
        return json.load(f)


def current_user():
    """Return the logged-in User object, or None."""
    uid = session.get("user_id")
    if uid is None:
        return None
    return User.query.get(uid)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user() is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        u = current_user()
        if u is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        if u.id != 1:
            flash("Admin access required.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


def get_or_create_stats(user=None):
    if user is None:
        user = current_user()
    stats = Stats.query.filter_by(user_id=user.id).first() if user else Stats.query.filter_by(user_id=None).first()
    if not stats:
        stats = Stats(
            user_id=user.id if user else None,
            current_streak=0,
            longest_streak=0,
            total_minutes=0,
            total_seconds=0,
            last_practice_date=None,
        )
        db.session.add(stats)
        db.session.commit()
    return stats


def get_current_week_info(user=None):
    """Returns (current_week_number, start_date, week_data_dict)."""
    if user is None:
        user = current_user()
    uid = user.id if user else None
    plan_weeks = getattr(user, "plan_weeks", 8) if user else 8
    first_session = (PracticeSession.query
                     .filter_by(user_id=uid)
                     .order_by(PracticeSession.date.asc())
                     .first())
    today = today_local()

    if first_session:
        days_elapsed = (today - first_session.date).days
        current_week = min(plan_weeks, days_elapsed // 7 + 1)
        start_date = first_session.date
    else:
        current_week = 1
        start_date = None

    sessions_all = PracticeSession.query.filter_by(user_id=uid).all()
    week_data = {}
    if first_session:
        for s in sessions_all:
            wk = min(plan_weeks, (s.date - first_session.date).days // 7 + 1)
            if wk not in week_data:
                week_data[wk] = {"days": set(), "minutes": 0}
            week_data[wk]["days"].add(s.date)
            week_data[wk]["minutes"] += s.minutes
        for k in week_data:
            week_data[k]["days"] = len(week_data[k]["days"])

    return current_week, start_date, week_data


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings_page():
    user = current_user()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "password":
            current_pw = request.form.get("current_password", "")
            new_pw = request.form.get("new_password", "")
            confirm_pw = request.form.get("confirm_password", "")
            if not user.check_password(current_pw):
                flash("Current password is incorrect.", "error")
            elif not new_pw:
                flash("New password cannot be empty.", "error")
            elif new_pw != confirm_pw:
                flash("New passwords do not match.", "error")
            else:
                user.set_password(new_pw)
                db.session.commit()
                flash("Password updated.", "success")
        elif action == "plan":
            weeks = request.form.get("plan_weeks", type=int)
            if weeks in (8, 12, 16):
                user.plan_weeks = weeks
                db.session.commit()
                flash("Training plan updated.", "success")
            else:
                flash("Invalid plan length.", "error")
        elif action == "time":
            daily = request.form.get("daily_minutes", type=int, default=0) or 0
            siddur = request.form.get("siddur_minutes", type=int, default=0) or 0
            if daily < 0 or siddur < 0:
                flash("Minutes cannot be negative.", "error")
            elif siddur > daily > 0:
                flash("Siddur time cannot exceed total daily time.", "error")
            else:
                user.daily_minutes = daily
                user.siddur_minutes = siddur
                db.session.commit()
                flash("Practice time updated.", "success")
        return redirect(url_for("settings_page"))
    # Pass current plan defaults so settings page can show helpful placeholders
    plan = ALL_WEEKLY_PLANS.get(user.plan_weeks, _PLAN_8)
    current_week, _, _ = get_current_week_info(user)
    week_plan = plan[min(current_week, len(plan)) - 1]
    base_targets = _plan_targets(week_plan)
    plan_default_total  = sum(base_targets.values())
    plan_default_siddur = base_targets.get('siddur', 0)
    return render_template("settings.html", user=user,
                           plan_default_total=plan_default_total,
                           plan_default_siddur=plan_default_siddur)


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session["user_id"] = user.id
            return redirect(url_for("dashboard"))
        error = "Invalid username or password."
    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            error = "Username and password are required."
        elif User.query.filter_by(username=username).first():
            error = "That username is already taken."
        else:
            u = User(username=username)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            session["user_id"] = u.id
            return redirect(url_for("dashboard"))
    return render_template("register.html", error=error)


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))


@app.context_processor
def inject_user():
    return {"me": current_user()}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def dashboard():
    user = current_user()
    stats = get_or_create_stats(user)
    recent_sessions = (
        PracticeSession.query
        .filter_by(user_id=user.id)
        .order_by(PracticeSession.date.desc(), PracticeSession.id.desc())
        .limit(10)
        .all()
    )
    current_week, start_date, _ = get_current_week_info(user)
    plan = ALL_WEEKLY_PLANS.get(user.plan_weeks, _PLAN_8)
    current_week_plan = plan[min(current_week, len(plan)) - 1]

    today = today_local()
    today_sessions = PracticeSession.query.filter_by(user_id=user.id, date=today).all()
    today_by_mode = {}
    for s in today_sessions:
        today_by_mode[s.mode] = today_by_mode.get(s.mode, 0) + s.minutes

    plan_targets = _user_targets(user, current_week_plan)
    today_drill_rows = [
        {
            "mode":   mode,
            "color":  color,
            "done":   today_by_mode.get(mode, 0),
            "target": plan_targets.get(mode, default_target),
            "pct":    min(100, round(
                today_by_mode.get(mode, 0) / plan_targets.get(mode, default_target) * 100
            )),
        }
        for mode, color, default_target in DRILL_META
    ]

    return render_template(
        "dashboard.html",
        stats=stats,
        recent_sessions=recent_sessions,
        current_week=current_week,
        plan_weeks=user.plan_weeks,
        current_week_plan=current_week_plan,
        start_date=start_date,
        today_drill_rows=today_drill_rows,
    )


@app.route("/drill/<mode>")
@login_required
def drill(mode):
    valid_modes = ["letters", "words", "phrases", "prayer", "consonants", "vowelfire", "siddur"]
    if mode not in valid_modes:
        return redirect(url_for("dashboard"))
    if mode == "siddur":
        content = []
    elif mode == "vowelfire":
        content = generate_vowelfire_content()
    else:
        content = load_drills().get(mode, [])
    recommended_time = MODE_RECOMMENDED.get(mode, "15 min")
    user = current_user()
    plan = ALL_WEEKLY_PLANS.get(user.plan_weeks, _PLAN_8)
    current_week, _, _ = get_current_week_info(user)
    week_plan = plan[min(current_week, len(plan)) - 1]
    targets = _user_targets(user, week_plan)
    # Default fallback: first number from MODE_RECOMMENDED string (e.g. "10–15 min" → 10)
    import re as _re
    fallback = int(_re.search(r'\d+', recommended_time).group()) if _re.search(r'\d+', recommended_time) else 15
    target_minutes = targets.get(mode, fallback)
    saved_interval = getattr(user, f'interval_{mode}', None)
    return render_template("drill.html", mode=mode, content=content,
                           recommended_time=recommended_time,
                           target_minutes=target_minutes,
                           saved_interval=saved_interval,
                           vowels=VOWELS if mode == 'letters' else [],
                           consonants=CONSONANTS if mode == 'consonants' else [])


@app.route("/api/save_interval", methods=["POST"])
@login_required
def save_interval():
    """Save a user's preferred auto-play interval for a given drill mode."""
    user = current_user()
    data = request.get_json(force=True, silent=True) or {}
    mode = data.get("mode", "")
    try:
        seconds = float(data.get("seconds", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid seconds"}), 400
    attr = f"interval_{mode}"
    if not hasattr(user, attr) or seconds <= 0:
        return jsonify({"ok": False, "error": "unknown mode"}), 400
    setattr(user, attr, seconds)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/pronunciation")
@login_required
def pronunciation():
    return render_template(
        "pronunciation.html",
        consonants=CONSONANTS,
        vowels=VOWELS,
    )


@app.route("/complete", methods=["POST"])
@login_required
def complete_session():
    user = current_user()
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    mode = data.get("mode", "letters")
    elapsed_seconds = max(0, int(data.get("seconds", 0)))
    minutes = max(1, int(data.get("minutes", 1)))
    today = today_local()
    yesterday = today - timedelta(days=1)

    # Persist session
    new_session = PracticeSession(date=today, mode=mode, minutes=minutes,
                                  seconds=elapsed_seconds, user_id=user.id)
    db.session.add(new_session)
    db.session.flush()  # assigns PK without full commit
    session_id = new_session.id

    # Update stats for this user
    stats = get_or_create_stats(user)
    stats.total_minutes += minutes
    stats.total_seconds += elapsed_seconds

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
@login_required
def guide():
    user = current_user()
    stats = get_or_create_stats(user)
    current_week, start_date, week_data = get_current_week_info(user)
    plan = ALL_WEEKLY_PLANS.get(user.plan_weeks, _PLAN_8)
    return render_template(
        "guide.html",
        weekly_plan=plan,
        plan_weeks=user.plan_weeks,
        reading_tips=READING_TIPS,
        current_week=current_week,
        start_date=start_date,
        week_data=week_data,
        stats=stats,
    )


@app.route("/upload_recording/<int:session_id>", methods=["POST"])
@login_required
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
@login_required
def sessions():
    user = current_user()
    mode_filter = request.args.get("mode", "all")
    query = PracticeSession.query.filter_by(user_id=user.id).order_by(
        PracticeSession.date.desc(), PracticeSession.id.desc()
    )
    if mode_filter != "all":
        query = query.filter_by(mode=mode_filter)
    all_sessions = query.all()
    modes = ["consonants", "letters", "vowelfire", "words", "phrases", "prayer", "siddur"]
    return render_template(
        "sessions.html",
        sessions=all_sessions,
        mode_filter=mode_filter,
        modes=modes,
    )


@app.route("/sessions/<int:session_id>/delete", methods=["POST"])
@login_required
def delete_session(session_id):
    user = current_user()
    session_obj = PracticeSession.query.filter_by(id=session_id, user_id=user.id).first()
    if session_obj:
        stats = get_or_create_stats(user)
        stats.total_minutes = max(0, stats.total_minutes - session_obj.minutes)
        stats.total_seconds = max(0, stats.total_seconds - session_obj.seconds)
        if session_obj.recording_path:
            filepath = os.path.join(basedir, "static", session_obj.recording_path)
            if os.path.exists(filepath):
                os.remove(filepath)
        db.session.delete(session_obj)
        db.session.commit()
    return redirect(request.referrer or url_for("sessions"))


@app.route("/sessions/delete_mode/<mode>", methods=["POST"])
@login_required
def delete_mode_sessions(mode):
    user = current_user()
    mode_sessions = PracticeSession.query.filter_by(mode=mode, user_id=user.id).all()
    stats = get_or_create_stats(user)
    for s in mode_sessions:
        stats.total_minutes = max(0, stats.total_minutes - s.minutes)
        stats.total_seconds = max(0, stats.total_seconds - s.seconds)
        if s.recording_path:
            filepath = os.path.join(basedir, "static", s.recording_path)
            if os.path.exists(filepath):
                os.remove(filepath)
        db.session.delete(s)
    db.session.commit()
    return redirect(url_for("sessions", mode=mode))


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.route("/admin")
@admin_required
def admin():
    sessions_all = PracticeSession.query.order_by(
        PracticeSession.date.desc(), PracticeSession.id.desc()
    ).all()
    all_users = User.query.order_by(User.id).all()
    users_stats = []
    for u in all_users:
        st = Stats.query.filter_by(user_id=u.id).first()
        if not st:
            st = Stats(user_id=u.id, current_streak=0, longest_streak=0,
                       total_minutes=0, last_practice_date=None)
        users_stats.append({"user": u, "stats": st})
    modes = ["consonants", "letters", "vowelfire", "words", "phrases", "prayer", "siddur"]
    return render_template(
        "admin.html",
        sessions=sessions_all,
        users_stats=users_stats,
        modes=modes,
        users=all_users,
    )


@app.route("/admin/user/<int:user_id>/edit", methods=["POST"])
@admin_required
def admin_edit_user(user_id):
    user = User.query.get_or_404(user_id)
    username = request.form.get("username", "").strip()
    plan_weeks = request.form.get("plan_weeks", type=int)
    daily_minutes = request.form.get("daily_minutes", type=int, default=0) or 0
    siddur_minutes = request.form.get("siddur_minutes", type=int, default=0) or 0

    if not username:
        flash("Username cannot be empty.", "error")
        return redirect(url_for("admin"))
    existing = User.query.filter(User.username == username, User.id != user.id).first()
    if existing:
        flash("That username is already taken.", "error")
        return redirect(url_for("admin"))
    if plan_weeks not in (8, 12, 16):
        flash("Invalid plan length.", "error")
        return redirect(url_for("admin"))
    if daily_minutes < 0 or siddur_minutes < 0:
        flash("Minutes cannot be negative.", "error")
        return redirect(url_for("admin"))
    if siddur_minutes > daily_minutes > 0:
        flash("Siddur time cannot exceed total daily time.", "error")
        return redirect(url_for("admin"))

    user.username = username
    user.plan_weeks = plan_weeks
    user.daily_minutes = daily_minutes
    user.siddur_minutes = siddur_minutes
    db.session.commit()
    flash(f"User {user.username} updated.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/user/<int:user_id>/reset_password", methods=["POST"])
@admin_required
def admin_reset_user_password(user_id):
    user = User.query.get_or_404(user_id)
    user.set_password("password123")
    db.session.commit()
    flash(f"Password reset for {user.username}.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/session/<int:session_id>/edit", methods=["POST"])
@admin_required
def admin_edit_session(session_id):
    s = PracticeSession.query.get_or_404(session_id)
    new_date = request.form.get("date")
    new_mode = request.form.get("mode")
    new_minutes = request.form.get("minutes")
    new_user_id = request.form.get("user_id")
    new_recording = request.form.get("recording_path")
    try:
        if new_date:
            s.date = date.fromisoformat(new_date)
        if new_mode:
            s.mode = new_mode
        if new_minutes:
            s.minutes = max(1, int(new_minutes))
        if new_user_id is not None:
            s.user_id = int(new_user_id) if new_user_id.strip() else None
        if new_recording is not None:
            s.recording_path = new_recording.strip() or None
    except (ValueError, TypeError):
        flash("Invalid value.", "error")
        return redirect(url_for("admin"))
    db.session.commit()
    flash(f"Session #{session_id} updated.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/session/<int:session_id>/delete", methods=["POST"])
@admin_required
def admin_delete_session(session_id):
    s = PracticeSession.query.get_or_404(session_id)
    stats = get_or_create_stats(current_user())
    stats.total_minutes = max(0, stats.total_minutes - s.minutes)
    stats.total_seconds = max(0, stats.total_seconds - s.seconds)
    if s.recording_path:
        filepath = os.path.join(basedir, "static", s.recording_path)
        if os.path.exists(filepath):
            os.remove(filepath)
    db.session.delete(s)
    db.session.commit()
    flash(f"Session #{session_id} deleted.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/stats/edit", methods=["POST"])
@admin_required
def admin_edit_stats():
    uid = request.form.get("user_id", type=int)
    target_user = User.query.get(uid) if uid else current_user()
    stats = get_or_create_stats(target_user)
    streak = request.form.get("current_streak")
    longest = request.form.get("longest_streak")
    total = request.form.get("total_seconds")
    last = request.form.get("last_practice_date")
    try:
        if streak is not None:
            stats.current_streak = max(0, int(streak))
        if longest is not None:
            stats.longest_streak = max(0, int(longest))
        if total is not None:
            stats.total_seconds = max(0, int(total))
            stats.total_minutes = max(0, int(total) // 60)
        if last:
            stats.last_practice_date = date.fromisoformat(last)
        elif last == "":
            stats.last_practice_date = None
    except (ValueError, TypeError):
        flash("Invalid stats value.", "error")
        return redirect(url_for("admin"))
    db.session.commit()
    flash("Stats updated.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/stats/reset", methods=["POST"])
@admin_required
def admin_reset_stats():
    uid = request.form.get("user_id", type=int)
    target_user = User.query.get(uid) if uid else current_user()
    stats = get_or_create_stats(target_user)
    stats.current_streak = 0
    stats.longest_streak = 0
    stats.total_minutes = 0
    stats.total_seconds = 0
    stats.last_practice_date = None
    db.session.commit()
    flash("Stats reset to zero.", "success")
    return redirect(url_for("admin"))



with app.app_context():
    db.create_all()
    from sqlalchemy import inspect as sa_inspect, text as sa_text

    def _add_column_if_missing(table, column, col_def):
        cols = [c["name"] for c in sa_inspect(db.engine).get_columns(table)]
        if column not in cols:
            with db.engine.connect() as _conn:
                _conn.execute(sa_text(f"ALTER TABLE {table} ADD COLUMN {col_def}"))
                _conn.commit()

    _add_column_if_missing("practice_session", "recording_path", "recording_path VARCHAR(255)")
    _add_column_if_missing("practice_session", "user_id", "user_id INTEGER REFERENCES user(id)")
    _add_column_if_missing("stats", "user_id", "user_id INTEGER REFERENCES user(id)")
    _add_column_if_missing("user", "plan_weeks",     "plan_weeks INTEGER NOT NULL DEFAULT 8")
    _add_column_if_missing("user", "daily_minutes",  "daily_minutes INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing("user", "siddur_minutes", "siddur_minutes INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing("practice_session", "seconds", "seconds INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing("stats", "total_seconds", "total_seconds INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing("user", "interval_consonants", "interval_consonants REAL NOT NULL DEFAULT 1.0")
    _add_column_if_missing("user", "interval_vowelfire",  "interval_vowelfire REAL NOT NULL DEFAULT 1.0")
    _add_column_if_missing("user", "interval_letters",    "interval_letters REAL NOT NULL DEFAULT 2.0")
    _add_column_if_missing("user", "interval_words",      "interval_words REAL NOT NULL DEFAULT 2.0")
    _add_column_if_missing("user", "interval_phrases",    "interval_phrases REAL NOT NULL DEFAULT 5.0")
    _add_column_if_missing("user", "interval_prayer",     "interval_prayer REAL NOT NULL DEFAULT 5.0")
    os.makedirs(os.path.join(basedir, "static", "recordings"), exist_ok=True)

if __name__ == "__main__":
    app.run(debug=True)
