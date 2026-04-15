#!/usr/bin/env python3
"""MLB daily digest: NY scores + league-wide transactions + top headlines."""

from __future__ import annotations

import datetime
import json
import random
import sys
import urllib.request

ESPN_HEADERS = {"User-Agent": "Mozilla/5.0"}

TEAMS = {
    "yankees": {"id": "10", "display": "NYY"},
    "mets":    {"id": "21", "display": "NYM"},
}


def api_get(url: str) -> dict:
    req = urllib.request.Request(url, headers=ESPN_HEADERS)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_today_scores() -> list[dict]:
    today = datetime.date.today().strftime("%Y%m%d")
    url = f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates={today}"
    return api_get(url).get("events", [])


def fetch_transactions(days: int = 3) -> list[dict]:
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days)
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/transactions"
        f"?limit=30&dates={start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"
    )
    return api_get(url).get("transactions", [])


def fetch_news(limit: int = 12) -> list[dict]:
    url = f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/news?limit={limit}"
    return api_get(url).get("articles", [])


def ny_games_today(events: list[dict]) -> list[dict]:
    results = []
    for team_key, team_info in TEAMS.items():
        tid = team_info["id"]
        for event in events:
            comp = event.get("competitions", [{}])[0]
            for competitor in comp.get("competitors", []):
                if competitor.get("team", {}).get("id") == tid:
                    results.append(_parse_game(event, tid))
                    break
    return results


def _parse_game(event: dict, team_id: str) -> dict:
    comp = event.get("competitions", [{}])[0]
    status_type = event.get("status", {}).get("type", {})
    state = status_type.get("state", "").lower()
    status_name = status_type.get("name", "")

    home_away = None
    opponent = None
    scores = {}
    for competitor in comp.get("competitors", []):
        tid = competitor.get("team", {}).get("id", "")
        raw = competitor.get("score")
        score = raw.get("value") if isinstance(raw, dict) else (raw if raw is not None else "?")
        scores[tid] = score
        if tid == team_id:
            home_away = competitor.get("homeAway", "")
            opponent = competitor.get("team", {}).get("shortDisplayName", "?")
        winner = competitor.get("winner", True)

    networks = set()
    for b in comp.get("broadcasts", []):
        for name in b.get("names", []):
            if name:
                networks.add(name)
    broadcast = ", ".join(sorted(networks)) if networks else "Check local listings"

    raw_date = event.get("date", "")
    if raw_date:
        try:
            dt_utc = datetime.datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            dt_local = dt_utc.astimezone(datetime.timezone(datetime.timedelta(hours=-4)))
            time_str = dt_local.strftime("%-I:%M %p ET")
        except Exception:
            time_str = status_name
    else:
        time_str = status_name

    team_disp = TEAMS[_tid_to_key(team_id)]["display"]
    loc = "vs" if home_away == "home" else "@"

    if state == "post" or status_name in ("Final", "STATUS_FINAL"):
        opp_tid = [t for t in scores if t != team_id][0] if len(scores) > 1 else "?"
        our_score = scores.get(team_id, "?")
        opp_score = scores.get(opp_tid, "?")
        result = "✅ W" if winner else "❌ L"
        return {"text": f"{result} {team_disp} {our_score} - {opponent} {opp_score} ({loc} {opponent}) | 📺 {broadcast}"}

    if state == "in":
        opp_tid = [t for t in scores if t != team_id][0] if len(scores) > 1 else "?"
        our_score = scores.get(team_id, "?")
        opp_score = scores.get(opp_tid, "?")
        return {"text": f"⚾ {team_disp} {our_score} @ {opponent} {opp_score} | 🔴 IN PROGRESS | 📺 {broadcast}"}

    return {"text": f"🕐 {team_disp} {loc} {opponent} — {time_str} | 📺 {broadcast}"}


def _tid_to_key(tid: str) -> str:
    for k, v in TEAMS.items():
        if v["id"] == tid:
            return k
    return "yankees"


def format_scores(games: list[dict]) -> str:
    if not games:
        return "No NY team games today."
    return "\n".join(g["text"] for g in games)


def format_transactions(trans: list[dict], limit: int = 10) -> str:
    lines = ["📋 **MLB Transactions (3-day rollup)**"]
    shown = 0
    for t in trans:
        desc = t.get("description", "").strip()
        if not desc:
            continue
        team_name = t.get("team", {}).get("displayName", "?")
        date_str = t.get("date", "")[:10]
        lines.append(f"• **{team_name}** ({date_str}): {desc[:120]}")
        shown += 1
        if shown >= limit:
            break
    if shown == 0:
        lines.append("No major transactions in the last 3 days.")
    return "\n".join(lines)


def format_news(articles: list[dict], limit: int = 6) -> str:
    lines = ["📰 **MLB Headlines**"]
    shown = 0
    for a in articles:
        if a.get("type") != "Story":
            continue
        headline = a.get("headline", "")
        if not headline:
            continue
        lines.append(f"• {headline[:130]}")
        shown += 1
        if shown >= limit:
            break
    if shown == 0:
        lines.append("No headlines available.")
    return "\n".join(lines)


def build_digest() -> str:
    events = fetch_today_scores()
    ny_games = ny_games_today(events)
    trans = fetch_transactions(days=3)
    news = fetch_news(limit=15)

    sections = [
        "⚾ **MLB Daily Digest — NY Teams**",
        "",
        format_scores(ny_games),
        "",
        format_transactions(trans, limit=8),
        "",
        format_news(news, limit=5),
    ]
    return "\n".join(sections)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--news-only":
        news = fetch_news(limit=15)
        print(format_news(news, limit=8))
    else:
        print(build_digest())
