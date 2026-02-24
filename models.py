import base64
from flask_sqlalchemy import SQLAlchemy
from datetime import date, datetime, timedelta, timezone

db = SQLAlchemy()

_TZ_OFFSET_HOURS = -8  # PST; change to -7 for PDT

def _today_local() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=_TZ_OFFSET_HOURS)).date()


class User(db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    # Password stored as base64-encoded bytes — simple obfuscation, not cryptographic
    password_b64 = db.Column(db.String(255), nullable=False)
    plan_weeks     = db.Column(db.Integer, default=8,  nullable=False)
    daily_minutes  = db.Column(db.Integer, default=0,  nullable=False)  # 0 = follow plan
    siddur_minutes = db.Column(db.Integer, default=0,  nullable=False)  # 0 = follow plan

    # Auto-play interval (seconds) saved per drill mode
    interval_consonants = db.Column(db.Float, default=1.0, nullable=False)
    interval_vowelfire  = db.Column(db.Float, default=1.0, nullable=False)
    interval_letters    = db.Column(db.Float, default=2.0, nullable=False)
    interval_words      = db.Column(db.Float, default=2.0, nullable=False)
    interval_phrases    = db.Column(db.Float, default=5.0, nullable=False)
    interval_prayer     = db.Column(db.Float, default=5.0, nullable=False)

    sessions = db.relationship("PracticeSession", backref="user", lazy=True, cascade="all, delete-orphan")
    stats = db.relationship("Stats", backref="user", uselist=False, cascade="all, delete-orphan")

    def set_password(self, plaintext: str):
        self.password_b64 = base64.b64encode(plaintext.encode()).decode()

    def check_password(self, plaintext: str) -> bool:
        return self.password_b64 == base64.b64encode(plaintext.encode()).decode()

    def __repr__(self):
        return f"<User {self.username}>"


class PracticeSession(db.Model):
    __tablename__ = "practice_session"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    date = db.Column(db.Date, nullable=False, default=_today_local)
    mode = db.Column(db.String(50), nullable=False)
    minutes = db.Column(db.Integer, nullable=False, default=1)
    seconds = db.Column(db.Integer, nullable=False, default=0)
    recording_path = db.Column(db.String(255), nullable=True)

    @property
    def duration_seconds(self):
        """Total elapsed seconds — falls back to minutes*60 for pre-migration rows."""
        return self.seconds if self.seconds else self.minutes * 60

    def __repr__(self):
        return f"<PracticeSession {self.date} {self.mode} {self.minutes}min>"


class Stats(db.Model):
    __tablename__ = "stats"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    current_streak = db.Column(db.Integer, default=0)
    longest_streak = db.Column(db.Integer, default=0)
    total_minutes = db.Column(db.Integer, default=0)
    total_seconds = db.Column(db.Integer, default=0)
    last_practice_date = db.Column(db.Date, nullable=True)

    @property
    def total_time_seconds(self):
        """Total practice seconds — falls back to total_minutes*60 for pre-migration rows."""
        return self.total_seconds if self.total_seconds else self.total_minutes * 60

    def __repr__(self):
        return f"<Stats streak={self.current_streak} total={self.total_minutes}min>"
