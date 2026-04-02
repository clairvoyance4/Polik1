"""
Sports data source — TheSportsDB (free public API, no key needed for basic queries).
Covers football, basketball, baseball, hockey, tennis, cricket, and more.

TheSportsDB free tier uses API key "3" (public).
"""

import requests

_BASE = "https://www.thesportsdb.com/api/v1/json/3"
_HEADERS = {"User-Agent": "PolyMarket-Research-Bot/1.0", "Accept": "application/json"}


def _get(path: str, params: dict | None = None) -> dict:
    try:
        r = requests.get(f"{_BASE}{path}", params=params, headers=_HEADERS, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}


def _team_summary(t: dict) -> dict:
    return {
        "id": t.get("idTeam"),
        "name": t.get("strTeam"),
        "league": t.get("strLeague"),
        "country": t.get("strCountry"),
        "sport": t.get("strSport"),
        "stadium": t.get("strStadium"),
        "description_snippet": (t.get("strDescriptionEN") or "")[:300],
    }


def _event_summary(e: dict) -> dict:
    return {
        "id": e.get("idEvent"),
        "name": e.get("strEvent"),
        "date": e.get("dateEvent"),
        "time": e.get("strTime"),
        "home_team": e.get("strHomeTeam"),
        "away_team": e.get("strAwayTeam"),
        "home_score": e.get("intHomeScore"),
        "away_score": e.get("intAwayScore"),
        "league": e.get("strLeague"),
        "season": e.get("strSeason"),
        "status": e.get("strStatus"),
        "venue": e.get("strVenue"),
    }


def search_team(team_name: str) -> dict:
    """
    Search for a sports team by name.
    Returns team info including league, country, sport, and stadium.
    """
    data = _get("/searchteams.php", {"t": team_name})
    teams = data.get("teams") or []
    return {
        "query": team_name,
        "count": len(teams),
        "teams": [_team_summary(t) for t in teams[:5]],
    }


def get_team_last_results(team_id: str) -> dict:
    """
    Last 5 results for a team (by TheSportsDB team ID).
    Get team_id from search_team().
    Returns scores, dates, opponents — useful for assessing form.
    """
    data = _get("/eventslast5.php", {"id": team_id})
    events = data.get("results") or []
    return {
        "team_id": team_id,
        "count": len(events),
        "last_results": [_event_summary(e) for e in events],
    }


def get_team_next_fixtures(team_id: str) -> dict:
    """
    Next 5 upcoming fixtures for a team (by TheSportsDB team ID).
    Get team_id from search_team().
    Useful for predicting match outcomes.
    """
    data = _get("/eventsnext5.php", {"id": team_id})
    events = data.get("events") or []
    return {
        "team_id": team_id,
        "count": len(events),
        "next_fixtures": [_event_summary(e) for e in events],
    }


def get_league_table(league_id: str, season: str | None = None) -> dict:
    """
    Current league standings table.
    Common league IDs:
      4328 = English Premier League
      4335 = La Liga
      4331 = Bundesliga
      4332 = Serie A
      4334 = Ligue 1
      4480 = NBA
      4424 = NFL
    season format: '2023-2024' or '2024'
    """
    params: dict = {"l": league_id}
    if season:
        params["s"] = season
    data = _get("/lookuptable.php", params)
    table = data.get("table") or []
    return {
        "league_id": league_id,
        "season": season,
        "standings": [
            {
                "rank": t.get("intRank"),
                "team": t.get("strTeam"),
                "played": t.get("intPlayed"),
                "won": t.get("intWin"),
                "drawn": t.get("intDraw"),
                "lost": t.get("intLoss"),
                "goals_for": t.get("intGoalsFor"),
                "goals_against": t.get("intGoalsAgainst"),
                "goal_diff": t.get("intGoalDifference"),
                "points": t.get("intPoints"),
            }
            for t in table[:20]
        ],
    }


def search_event(event_name: str) -> dict:
    """
    Search for a specific sporting event by name.
    Examples: 'Champions League Final 2024', 'Super Bowl', 'Wimbledon 2024'
    """
    data = _get("/searchevents.php", {"e": event_name})
    events = data.get("event") or []
    return {
        "query": event_name,
        "count": len(events),
        "events": [_event_summary(e) for e in events[:10]],
    }
