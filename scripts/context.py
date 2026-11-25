#!/usr/bin/env python3
"""Resolve school names and filter normalized or ESPN game schedules."""

import argparse
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def membership():
    return json.loads((ROOT / "data" / "teams.json").read_text(encoding="utf-8"))


def name_key(value):
    ascii_name = unicodedata.normalize("NFKD", value.casefold()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_name)


def team_id(value):
    teams = membership()["teams"]
    key = name_key(value)
    # Miami without a qualifier can mean either school even when a feed aliases it to Florida.
    if key == "miami":
        raise ValueError("Ambiguous team Miami; specify Miami (FL) or Miami (OH)")
    matches = [slug for slug, team in teams.items()
               if key in {name_key(name) for name in (slug, team["name"], *team["aliases"])}]
    if len(matches) > 1:
        raise ValueError(f"Ambiguous team {value}: {', '.join(matches)}")
    if not matches:
        raise ValueError(f"{value} is absent from the {membership()['season']} membership manifest")
    return matches[0]


def timestamp(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.utcoffset() is None:
        raise ValueError("Event timestamps require an explicit UTC offset")
    return stamp


def valid_season(value):
    if membership()["sport"] == "cfb":
        return bool(re.fullmatch(r"[0-9]{4}", value))
    return bool(re.fullmatch(r"[0-9]{4}-[0-9]{2}", value)) and (
        (int(value[:4]) + 1) % 100 == int(value[-2:])
    )


def normalize_event(event, teams_by_provider):
    game = event["competitions"][0]
    status = (game.get("status") or event["status"])["type"]
    sides = []
    for side in game["competitors"]:
        team = side.get("team", {})
        identifier = str(team.get("id") or side.get("id") or "")
        name = team.get("displayName") or team.get("shortDisplayName") or "TBD"
        sides.append({
            "team": teams_by_provider.get(identifier), "name": name,
            "side": side.get("homeAway"),
            "aliases": [team[key] for key in ("location", "shortDisplayName") if team.get(key)],
            "verified_opponent": bool(identifier) and name.upper() not in {"TBA", "TBD"},
        })
    return {
        "id": str(event["id"]), "start": game.get("date") or event["date"],
        "time_confirmed": game.get("timeValid") is not False,
        "status": status["name"], "teams": sides,
        "neutral": bool(game.get("neutralSite")), "venue": game.get("venue", {}).get("fullName"),
        "week": event.get("week", {}).get("number"),
        "labels": [note["headline"] for note in game.get("notes", []) if note.get("headline")],
    }


def select_games(events, *, day=None, zone="Asia/Manila", names=(), week=None, label=None, now=None):
    """Filter a verified, same-season feed and keep each game ID once."""
    local_zone = ZoneInfo(zone)
    now = now or datetime.now(timezone.utc)
    if day is None and not (names or week is not None or label):
        day = now.astimezone(local_zone).date()
    if len(names) != len(set(names)) or len(names) > 2:
        raise ValueError("Specify one school or two different opponents")
    rows = {}
    for row in events:
        if week is not None and row.get("week") != week:
            continue
        if label and not any(name_key(label) == name_key(item) for item in row.get("labels", [])):
            continue
        sides = row["teams"]
        if len(sides) != 2:
            continue
        keys = [{side["team"]} if side.get("team") else
                {name_key(value) for value in (side["name"], *side.get("aliases", []))}
                for side in sides]
        qualified = sum(bool(side.get("team")) for side in sides)
        if len(names) == 2:
            if not qualified or not any(
                names[0] in keys[index] and names[1] in keys[1 - index] for index in range(2)
            ):
                continue
        elif (qualified != 2 and not (
            (week is not None or label) and qualified == 1
            and any(not side.get("verified_opponent", True) for side in sides)
        )) or not set(names).issubset(keys[0] | keys[1]):
            continue
        kickoff = timestamp(row["start"])
        local = kickoff.astimezone(local_zone)
        if day is not None and local.date() != day:
            continue
        confirmed = row.get("time_confirmed", True)
        status = row["status"]
        if names and day is None and week is None and not label and (
            status != "STATUS_SCHEDULED" or kickoff <= now
        ):
            continue
        rows[str(row["id"])] = {
            **row, "local_start": local.isoformat() if confirmed else None,
            "pregame": confirmed and qualified >= 1
            and all(side.get("verified_opponent", True) for side in sides)
            and status == "STATUS_SCHEDULED" and kickoff > now,
        }
    ordered = sorted(rows.values(), key=lambda row: (timestamp(row["start"]), str(row["id"])))
    return ordered[:1] if names and day is None and week is None and not label else ordered


def slate_window(day, timezone_name="Asia/Manila"):
    local_zone = ZoneInfo(timezone_name)
    selected_date = date.fromisoformat(day) if day else datetime.now(local_zone).date()
    local_start = datetime.combine(selected_date, time.min, tzinfo=local_zone)
    local_end = datetime.combine(
        selected_date + timedelta(days=1), time.min, tzinfo=local_zone
    )
    start_utc = local_start.astimezone(timezone.utc)
    end_utc = local_end.astimezone(timezone.utc)
    first_et_date = start_utc.astimezone(ET).date()
    last_et_date = (end_utc - timedelta(microseconds=1)).astimezone(ET).date()
    et_dates = []
    current_date = first_et_date
    while current_date <= last_et_date:
        et_dates.append(current_date.isoformat())
        current_date += timedelta(days=1)
    return {
        "local_date": selected_date.isoformat(),
        "timezone": timezone_name,
        "start_local": local_start.isoformat(),
        "end_local_exclusive": local_end.isoformat(),
        "start_utc": start_utc.isoformat(),
        "end_utc_exclusive": end_utc.isoformat(),
        "source_dates_et": et_dates,
    }


def great_circle_miles(origin, destination):
    for latitude, longitude in (origin, destination):
        if not (
            math.isfinite(latitude)
            and math.isfinite(longitude)
            and -90 <= latitude <= 90
            and -180 <= longitude <= 180
        ):
            raise ValueError("latitude must be in [-90, 90] and longitude in [-180, 180]")
    lat1, lon1 = map(math.radians, origin)
    lat2, lon2 = map(math.radians, destination)
    haversine = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    angle = 2 * math.asin(math.sqrt(min(1.0, max(0.0, haversine))))
    # IUGG mean Earth radius in km, converted to statute miles.
    return 6371.0088 / 1.609344 * angle



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    window = commands.add_parser("window", help="Find source dates overlapping a local slate")
    window.add_argument("--date")
    window.add_argument("--timezone", default="Asia/Manila")
    miles = commands.add_parser("miles", help="Estimate venue-to-venue great-circle miles")
    miles.add_argument("--origin", type=float, nargs=2, required=True)
    miles.add_argument("--destination", type=float, nargs=2, required=True)
    rest = commands.add_parser("rest", help="Compare two confirmed start times")
    rest.add_argument("previous", type=timestamp)
    rest.add_argument("current", type=timestamp)
    resolve = commands.add_parser("resolve", help="Resolve a school alias to a manifest slug")
    resolve.add_argument("team")
    select = commands.add_parser("select", help="Select games from a downloaded ESPN or normalized JSON feed")
    select.add_argument("feeds", nargs="+", type=Path)
    select.add_argument("--date", type=date.fromisoformat)
    select.add_argument("--timezone", default="Asia/Manila")
    select.add_argument("--season", default=membership()["season"])
    select.add_argument("--as-of", type=timestamp)
    scope = select.add_mutually_exclusive_group()
    scope.add_argument("--team")
    scope.add_argument("--matchup", nargs=2)
    scope.add_argument("--week", type=int)
    scope.add_argument("--label")
    args = parser.parse_args()
    try:
        if args.command == "window":
            result = slate_window(args.date, args.timezone)
        elif args.command == "resolve":
            result = {"team": team_id(args.team)}
        elif args.command == "rest":
            if args.previous >= args.current:
                raise ValueError("The previous game must come before the current game")
            result = {
                "elapsed_hours": round((args.current - args.previous).total_seconds() / 3600, 1),
                "eastern_calendar_days": (args.current.astimezone(ET).date()
                                          - args.previous.astimezone(ET).date()).days,
            }
        elif args.command == "miles":
            result = {"approximate_miles": round(great_circle_miles(args.origin, args.destination), 1)}
        else:
            manifest = membership()
            if not valid_season(args.season):
                raise ValueError("Use YYYY-YY for CBB and YYYY for CFB")
            if args.week is not None and (args.week < 0 or manifest["sport"] != "cfb"):
                raise ValueError("Numbered weeks are available for CFB only")
            if args.date and (args.week is not None or args.label):
                raise ValueError("An official week or round uses its own schedule scope")
            providers = {team["espn_id"]: slug for slug, team in manifest["teams"].items()}
            events = []
            for path in args.feeds:
                feed = json.loads(path.read_text(encoding="utf-8"))
                if "games" in feed and feed.get("season") == args.season:
                    events.extend(feed["games"])
                elif "events" in feed:
                    if args.season != manifest["season"]:
                        raise ValueError("For another season use normalized JSON with season-specific membership")
                    events.extend(
                        normalize_event(event, providers) for event in feed["events"]
                        if event.get("season", feed.get("season", {})).get("year") == manifest["espn_season"]
                    )
                else:
                    raise ValueError(f"{path} has no games for {args.season}")
            historical_names = {}
            if args.season != manifest["season"]:
                for event in events:
                    for side in event["teams"]:
                        if side.get("team"):
                            for alias in (side["name"], side["team"], *side.get("aliases", [])):
                                historical_names.setdefault(name_key(alias), set()).add(side["team"])
            names = []
            for value in args.matchup or ([args.team] if args.team else []):
                if historical_names:
                    candidates = historical_names.get(name_key(value), set())
                    if len(candidates) > 1 or name_key(value) == "miami":
                        raise ValueError(f"Ambiguous team {value}; specify the school")
                    if candidates:
                        names.append(next(iter(candidates)))
                    elif args.matchup:
                        names.append(name_key(value))
                    else:
                        raise ValueError(f"{value} is absent from the season-specific schedule")
                    continue
                try:
                    names.append(team_id(value))
                except ValueError as exc:
                    if not args.matchup or not str(exc).startswith(f"{value} is absent"):
                        raise
                    names.append(name_key(value))
            result = select_games(events, day=args.date, zone=args.timezone, names=names,
                                  week=args.week, label=args.label, now=args.as_of)
    except (KeyError, TypeError, ValueError, OSError, OverflowError, ZoneInfoNotFoundError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
