from flask_sqlalchemy import SQLAlchemy
from datetime import date, datetime, timedelta, timezone

db = SQLAlchemy()

_TZ_OFFSET_HOURS = -8  # PST; change to -7 for PDT

def _today_local() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=_TZ_OFFSET_HOURS)).date()


class PracticeSession(db.Model):
    __tablename__ = "practice_session"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=_today_local)
    mode = db.Column(db.String(50), nullable=False)
    minutes = db.Column(db.Integer, nullable=False, default=1)
    recording_path = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f"<PracticeSession {self.date} {self.mode} {self.minutes}min>"


class Stats(db.Model):
    __tablename__ = "stats"

    id = db.Column(db.Integer, primary_key=True)
    current_streak = db.Column(db.Integer, default=0)
    longest_streak = db.Column(db.Integer, default=0)
    total_minutes = db.Column(db.Integer, default=0)
    last_practice_date = db.Column(db.Date, nullable=True)

    def __repr__(self):
        return f"<Stats streak={self.current_streak} total={self.total_minutes}min>"
