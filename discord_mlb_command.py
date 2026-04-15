#!/usr/bin/env python3
"""MLB live scores and upcoming broadcast info for Yankees and Mets."""

from __future__ import annotations

import datetime
import json
import sys
import urllib.request
import urllib.parse

TEAMS = {
    "yankees": {"id": "10", "name": "Yankees", "display": "NYY"},
    "mets":    {"id": "21", "name": "Mets",    "display": "NYM"},
}
TEAM_IDS = {v["id"]: k for k, v in TEAMS.items()}

ESPN_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MLB-bot/1.0)"}


def api_get(url: str) -> dict:
    req = urllib.request.Request(url, headers=ESPN_HEADERS)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_recent(team_id: str, days: int = 2) -> list[dict]:
    """Fetch scoreboard for the last N days, only completed (post) games."""
    all_events = []
    today = datetime.date.today()
    for offset in range(days):
        date = (today - datetime.timedelta(days=offset)).strftime("%Y%m%d")
        url = (
            f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/"
            f"scoreboard?dates={date}&teams={team_id}"
        )
        data = api_get(url)
        events = data.get("events", [])
        # Only include finished games
        filtered = []
        for e in events:
            if not _team_in_event(e, team_id):
                continue
            state = e.get("status", {}).get("type", {}).get("state", "").lower()
            if state == "post":
                filtered.append(e)
        all_events.extend(filtered)
    return all_events


def fetch_today() -> list[dict]:
    today = datetime.date.today().strftime("%Y%m%d")
    url = f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates={today}"
    return api_get(url).get("events", [])


def fetch_upcoming(team_id: str, days: int = 14) -> list[dict]:
    today = datetime.date.today()
    start = today.strftime("%Y%m%d")
    end = (today + datetime.timedelta(days=days)).strftime("%Y%m%d")
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/"
        f"scoreboard?dates={start}-{end}&teams={team_id}"
    )
    data = api_get(url)
    events = data.get("events", [])
    return [e for e in events if _team_in_event(e, team_id)]


def _team_in_event(event: dict, team_id: str) -> bool:
    for comp in event.get("competitions", []):
        for competitor in comp.get("competitors", []):
            if competitor.get("team", {}).get("id") == team_id:
                return True
    return False


def parse_broadcasts(comp: dict) -> list[str]:
    networks = set()
    for b in comp.get("broadcasts", []):
        for name in b.get("names", []):
            if name:
                networks.add(name)
    return sorted(networks)


def parse_game(event: dict, team_id: str) -> dict | None:
    if not _team_in_event(event, team_id):
        return None
    comp = event.get("competitions", [{}])[0]
    status_type = event.get("status", {}).get("type", {})
    state = status_type.get("state", "").lower()
    status_name = status_type.get("name", "")
    detail = status_type.get("detail", "")

    home_away = None
    our_team_name = None
    opponent_name = None
    for competitor in comp.get("competitors", []):
        tid = competitor.get("team", {}).get("id", "")
        tname = competitor.get("team", {}).get("shortDisplayName", "?")
        if tid == team_id:
            home_away = competitor.get("homeAway", "")
            our_team_name = tname
        else:
            opponent_name = tname

    team_key = TEAM_IDS.get(team_id, "?")
    team_display = TEAMS[team_key]["display"]

    scores = {}
    for competitor in comp.get("competitors", []):
        tid = competitor.get("team", {}).get("id", "")
        raw_score = competitor.get("score")
        if isinstance(raw_score, dict):
            score_val = raw_score.get("value", "?")
        else:
            score_val = str(raw_score) if raw_score is not None else "?"
        winner = competitor.get("winner", True)
        scores[tid] = {
            "abbrev": competitor.get("team", {}).get("abbreviation", ""),
            "score": score_val,
            "winner": winner,
        }

    networks = parse_broadcasts(comp)
    broadcast_str = ", ".join(networks) if networks else "Check local listings"

    raw_date = event.get("date", "")
    if raw_date:
        try:
            dt_utc = datetime.datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            dt_local = dt_utc.astimezone(datetime.timezone(datetime.timedelta(hours=-4)))
            time_str = dt_local.strftime("%-I:%M %p ET")
        except Exception:
            time_str = raw_date
    else:
        time_str = detail

    return {
        "team": team_display,
        "team_id": team_id,
        "home_away": home_away,
        "opponent": opponent_name,
        "status": status_name,
        "detail": detail,
        "state": state,
        "time": time_str,
        "broadcast": broadcast_str,
        "scores": scores,
        "event_id": event.get("id", ""),
    }


def format_game(g: dict) -> str:
    state = g["state"]
    team = g["team"]
    opp = g["opponent"]
    loc = "vs" if g["home_away"] == "home" else "@"
    broadcast = g["broadcast"]

    if state == "post" or g["status"] in ("Final", "STATUS_FINAL"):
        our_score = g["scores"].get(g["team_id"], {}).get("score", "?")
        opp_id = [tid for tid in g["scores"] if tid != g["team_id"]]
        opp_score = g["scores"].get(opp_id[0], {}).get("score", "?") if opp_id else "?"
        winner = g["scores"].get(g["team_id"], {}).get("winner", False)
        result = "✅ W" if winner else "❌ L"
        return f"{result} {team} {our_score} - {opp} {opp_score} ({loc} {opp}) | 📺 {broadcast}"

    if state == "pre":
        return f"🕐 {team} {loc} {opp} — {g['time']} | 📺 {broadcast}"

    if state == "in":
        our_score = g["scores"].get(g["team_id"], {}).get("score", "?")
        opp_id = [tid for tid in g["scores"] if tid != g["team_id"]]
        opp_score = g["scores"].get(opp_id[0], {}).get("score", "?") if opp_id else "?"
        return f"⚾ {team} {our_score} @ {opp} {opp_score} | 🔴 IN PROGRESS | 📺 {broadcast}"

    return f"⚾ {team} {loc} {opp} — {g['detail']} | 📺 {broadcast}"


def scores_summary() -> str:
    today_events = fetch_today()
    lines = ["⚾ **MLB Scoreboard — NY Teams**"]
    found = 0
    for team_id, team_key in [(TEAMS["yankees"]["id"], "yankees"), (TEAMS["mets"]["id"], "mets")]:
        # Always check for a completed game from yesterday first
        recent = fetch_recent(team_id, days=2)
        past_game = None
        for e in recent:
            ng = parse_game(e, team_id)
            if ng and ng["state"] == "post":
                past_game = ng
                break

        # Check today's events (skip already-finished games)
        game_found = False
        for event in today_events:
            g = parse_game(event, team_id)
            if g is None:
                continue
            if g["state"] == "post":
                continue  # skip finished games today — we already got past_game
            lines.append(format_game(g))
            found += 1
            game_found = True
            break

        if past_game:
            lines.append(format_game(past_game))
            found += 1

        if not game_found and not past_game:
            # No game today or yesterday — show next upcoming
            upcoming = fetch_upcoming(team_id, days=5)
            next_game = None
            for e in upcoming:
                ng = parse_game(e, team_id)
                if ng and ng["state"] == "pre":
                    next_game = ng
                    break
            if next_game:
                loc = "vs" if next_game["home_away"] == "home" else "@"
                lines.append(
                    f"📅 {next_game['team']} {loc} {next_game['opponent']} — "
                    f"{next_game['time']} | 📺 {next_game['broadcast']}"
                )
            else:
                lines.append(f"⏸️ {TEAMS[team_key]['display']}: No game scheduled (check back soon)")

    if found == 0 and len(lines) == 1:
        lines.append("No NY team games today. See you tomorrow! 🗓️")
    return "\n".join(lines)


def upcoming_games(team_key: str) -> str:
    team = TEAMS.get(team_key)
    if not team:
        return f"Unknown team: {team_key}. Use yankees or mets."
    team_id = team["id"]
    upcoming = fetch_upcoming(team_id, days=7)
    games = [parse_game(e, team_id) for e in upcoming]
    games = [g for g in games if g is not None]

    display_name = team["display"]
    lines = [f"📅 **{display_name} — Upcoming Games (7 days)**"]
    if not games:
        lines.append("No games found in the next 7 days.")
        return "\n".join(lines)

    for g in games[:5]:
        state = g["state"]
        if state == "pre":
            loc = "vs" if g["home_away"] == "home" else "@"
            lines.append(
                f"{g['time']} | {g['team']} {loc} {g['opponent']} | 📺 {g['broadcast']}"
            )
    return "\n".join(lines)


def handle(msg: str) -> str:
    raw = msg.strip().lower()
    if not raw.startswith("!mlb"):
        raise ValueError("Message must start with !mlb")

    parts = raw.split()
    if len(parts) == 1:
        return scores_summary()

    cmd = parts[1] if len(parts) > 1 else ""

    if cmd in {"scores", "score", "today"}:
        return scores_summary()

    if cmd in {"yankees", "mets"}:
        return upcoming_games(cmd)

    if cmd in {"yankees", "mets"}:
        return upcoming_games(cmd)

    if cmd in {"yankees", "mets"}:
        return upcoming_games(cmd)

    if cmd == "help":
        return (
            "MLB commands:\n"
            "- `!mlb` — today's NYY + NYM scores\n"
            "- `!mlb yankees` — upcoming Yankees games\n"
            "- `!mlb mets` — upcoming Mets games\n"
            "- `!mlb help`"
        )

    return scores_summary()


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: discord_mlb_command.py '!mlb'")
        return 2
    msg = " ".join(sys.argv[1:])
    try:
        print(handle(msg))
        return 0
    except Exception as e:
        print(f"MLB command error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
