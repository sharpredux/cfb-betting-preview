#!/usr/bin/env python3
"""Build researched TEAM.md snapshots from the official manifest and public ESPN data."""

import argparse
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean
from threading import Lock
from zoneinfo import ZoneInfo
from time import sleep
from urllib.parse import urlencode

from bs4 import BeautifulSoup
import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://site.api.espn.com/apis/site/v2/sports"
SPORTS = {
    "cbb": ("basketball/mens-college-basketball", "mens-college-basketball", 5),
    "cfb": ("football/college-football", "college-football", 4),
}


class Source:
    def __init__(self, endpoint, cache_dir):
        self.endpoint = f"{BASE}/{endpoint}"
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
        self.requests = {}

    def url(self, path, **params):
        return f"{self.endpoint}/{path}?{urlencode(params)}"

    def read(self, path, **params):
        url = self.url(path, **params)
        with self.lock:
            future = self.requests.get(url)
            owner = future is None
            if owner:
                future = self.requests[url] = Future()
        if owner:
            try:
                future.set_result(self.download(url))
            except Exception as error:
                future.set_exception(error)
        return future.result()

    def download(self, url):
        cache = self.cache_dir / f"{sha256(url.encode()).hexdigest()}.json"
        if cache.is_file():
            return json.loads(cache.read_text(encoding="utf-8"))
        for attempt in range(3):
            try:
                response = requests.get(url, timeout=15)
                response.raise_for_status()
                data = response.json()
                draft = cache.with_suffix(".tmp")
                draft.write_text(json.dumps(data), encoding="utf-8")
                draft.replace(cache)
                return data
            except (requests.RequestException, ValueError) as error:
                response = getattr(error, "response", None)
                if attempt == 2 or response is not None and response.status_code in (403, 404):
                    raise
                delay = response.headers.get("Retry-After", "") if response is not None else ""
                sleep(int(delay) if delay.isdigit() else 2 ** attempt)


def stamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("Timestamps require a timezone")
    return parsed.astimezone(timezone.utc)


def completed_games(schedule, cutoff, team):
    games = []
    for event in schedule["events"]:
        game = event["competitions"][0]
        status = game["status"]["type"]
        kickoff = stamp(game.get("date") or event["date"])
        if status["name"] not in {"STATUS_FINAL", "STATUS_FULL_TIME", "STATUS_FINAL_OVERTIME"} or kickoff >= cutoff:
            continue
        own, opponent = sorted(game["competitors"], key=lambda side: side["id"] != team)
        if own["id"] != team or not all("score" in side for side in (own, opponent)):
            continue
        scores = [side["score"] for side in (own, opponent)]
        points, allowed = [int(float(score["value"] if isinstance(score, dict) else score)) for score in scores]
        games.append((kickoff, game, own, opponent, points, allowed))
    return sorted(games, key=lambda game: game[0])


def ratio(value, separator):
    left, right = value.split(separator, maxsplit=1)
    return int(left), int(right)


def value_line(boxes, metrics):
    lines = []
    for label, key, kind in metrics:
        raw = [box[key] for box in boxes if key in box and box[key] not in {"", "--", "N/A"}]
        if not raw:
            continue
        if kind in {"-", "/"}:
            made, tried = map(sum, zip(*(ratio(value, kind) for value in raw)))
            if tried:
                lines.append(f"{label} {made}/{tried} ({100 * made / tried:.1f}%)")
        else:
            lines.append(f"{label} {mean(map(float, raw)):.1f}")
    return ", ".join(lines) or "advanced box-score measures unavailable"


def leaders(group, key, leader, per_game=False):
    totals, games = Counter(), Counter()
    for box in group:
        for category in box:
            if key not in category.get("keys", []):
                continue
            index = category["keys"].index(key)
            for row in category["athletes"]:
                if row.get("didNotPlay") or len(row.get("stats", [])) <= index:
                    continue
                name = row["athlete"]["displayName"]
                value = row["stats"][index]
                try:
                    if key == "completions/passingAttempts":
                        number = ratio(value, "/")[1]
                    else:
                        number = float(value)
                except ValueError:
                    continue
                totals[name] += number
                games[name] += 1
    if not totals:
        return ""
    return ", ".join(
        f"{name} ({number / games[name]:.1f} per appearance)" if per_game else f"{name} ({number:g})"
        for name, number in totals.most_common(leader)
    )


def box_context(sport, boxes, own_id):
    paired = []
    for summary in boxes.values():
        box = summary.get("boxscore", {})
        teams = box.get("teams", [])
        if len(teams) == 2 and any(row["team"]["id"] == own_id for row in teams):
            paired.append(sorted(teams, key=lambda row: row["team"]["id"] != own_id))
    own_stats, opp_stats = [], []
    for own, opp in paired:
        own_stats.append({item["name"]: item["displayValue"] for item in own["statistics"]})
        opp_stats.append({item["name"]: item["displayValue"] for item in opp["statistics"]})
    metrics = (
        [("3-point shooting", "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "-"),
         ("free-throw shooting", "freeThrowsMade-freeThrowsAttempted", "-"),
         ("offensive rebounds/game", "offensiveRebounds", "avg"),
         ("turnovers/game", "totalTurnovers", "avg")]
        if sport == "cbb" else
        [("net pass yards/game", "netPassingYards", "avg"),
         ("rush yards/game", "rushingYards", "avg"),
         ("third-down conversions", "thirdDownEff", "-"),
         ("turnovers/game", "turnovers", "avg")]
    )
    if not paired:
        return ""
    return (
        f"Across {len(paired)} recent games with both team box scores, offense recorded "
        f"{value_line(own_stats, metrics)}. Opponents recorded {value_line(opp_stats, metrics)}. "
        "These are unadjusted box-score measures."
    )


def personnel_context(sport, boxes, own_id):
    group = [player["statistics"] for summary in boxes.values()
             for player in summary.get("boxscore", {}).get("players", [])
             if player["team"]["id"] == own_id]
    metrics = (
        [("Total minutes", "minutes"), ("Points", "points"), ("Assists", "assists")]
        if sport == "cbb" else
        [("Pass attempts", "completions/passingAttempts"), ("Carries", "rushingAttempts"),
         ("Receptions", "receptions"), ("Tackles", "totalTackles"), ("Sacks", "sacks")]
    )
    paragraphs = [f"{label} — {players}" for label, key in metrics
                  if (players := leaders(group, key, 3 if key == "minutes" else 2))]
    if not paragraphs:
        return ""
    return f"Usage leaders across {len(group)} recent player box scores:\n\n" + "\n".join(
        f"- {paragraph}" for paragraph in paragraphs
    )


def official_records(url, cache_dir, cutoff, sport, season):
    cache = cache_dir / "standings.html"
    if not cache.exists():
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        cache.write_text(response.text, encoding="utf-8")
    standings = BeautifulSoup(cache.read_text(encoding="utf-8"), "html.parser")
    updated = next(value.strip() for value in standings.stripped_strings if value.startswith("Last Updated "))
    eastern = ZoneInfo("America/New_York")
    # The standings page prints an Eastern wall time with an EDT suffix even after DST ends.
    published = datetime.strptime(updated.rsplit(" ", 1)[0], "Last Updated %b %d, %Y %I:%M %p").replace(tzinfo=eastern)
    standings_year = published.year - (published.month < 7)
    if published > cutoff or standings_year != int(season[:4]):
        raise ValueError("Official standings must match the season and be published before the cutoff")
    records = {}
    for row in standings.select("tbody tr"):
        logo = row.select_one("td.standings-team img")
        if not logo:
            continue
        slug = logo["src"].rsplit("/", 1)[-1].removesuffix(".svg")
        cells = [cell.get_text(strip=True) for cell in row.find_all("td")]
        overall_start = 4 if sport == "cbb" else 3
        records[slug] = (cells[1:3], cells[overall_start:overall_start + 2])
    return published.date(), records


def build_profile(sport, season, source, slug, team, cutoff, published, record, overrides):
    _, page, recent_count = SPORTS[sport]
    provider_season = int(season[:4]) + (sport == "cbb")
    team_id = team["espn_id"]
    schedule_path, roster_path = f"teams/{team_id}/schedule", f"teams/{team_id}/roster"
    schedule = source.read(schedule_path, season=provider_season)
    roster = None
    try:
        roster = source.read(roster_path, season=provider_season)
    except requests.RequestException:
        if not overrides.get("coach") or not overrides.get("source"):
            raise
    for item in filter(None, (schedule, roster)):
        if item.get("season", {}).get("year") != provider_season:
            raise ValueError("provider returned a different season")
        if item["team"]["id"] != team_id:
            raise ValueError("provider returned a different team")
    games = completed_games(schedule, cutoff, team_id)
    if not games:
        raise ValueError("no completed games before the cutoff")
    coaches = [" ".join((coach["firstName"], coach["lastName"])) for coach in (roster or {}).get("coach", [])]
    homes = Counter(
        game["venue"]["fullName"] for _, game, own, _, _, _ in games
        if own["homeAway"] == "home" and not game.get("neutralSite") and game.get("venue", {}).get("fullName")
    )
    if not homes:
        homes.update(event["competitions"][0]["venue"]["fullName"] for event in schedule["events"]
                     if not event["competitions"][0].get("neutralSite")
                     and event["competitions"][0].get("venue", {}).get("fullName")
                     and any(side["id"] == team_id and side["homeAway"] == "home"
                             for side in event["competitions"][0]["competitors"]))
    coach = overrides.get("coach") or ", ".join(coaches) or "Unverified in provider roster"
    extra_sources = ""
    if roster:
        extra_sources += f"- [Season roster and coaching staff]({source.url(roster_path, season=provider_season)})\n"
    if overrides.get("source"):
        extra_sources += f"- [Official team confirmation]({overrides['source']})\n"
    venue = homes.most_common(1)[0][0] if homes else "Unverified in schedule"
    recent = games[-recent_count:]
    boxes = {}
    for _, game, _, _, _, _ in recent:
        if game.get("boxscoreAvailable") is False:
            continue
        try:
            summary = source.read("summary", event=game["id"])
        except (ValueError, OSError):
            continue
        boxes[game["id"]] = summary
    personnel = personnel_context(sport, boxes, team_id) or "Recent player-level usage could not be verified from box scores."
    tendencies = box_context(sport, boxes, team_id) or "Recent advanced tendencies could not be verified from box scores."
    season_wins = sum(points > against for _, _, _, _, points, against in games)
    form_wins = sum(points > against for _, _, _, _, points, against in recent)
    other: list[str] = []
    for when, game, own, opponent, points, allowed in reversed(recent):
        name = opponent["team"].get("displayName") or opponent["team"].get("shortDisplayName", "Opponent")
        marker = "vs." if own["homeAway"] == "home" else "at"
        if game.get("neutralSite"):
            marker = "vs. (neutral)"
        result = "W" if points > allowed else "L"
        other.append(f"- {when.date()} {marker} [{name}](https://www.espn.com/{page}/game/_/gameId/{game['id']}) — {result} {points}–{allowed}")
    scored = mean(game[4] for game in games)
    conceded = mean(game[5] for game in games)
    recent_scored = mean(game[4] for game in recent)
    recent_conceded = mean(game[5] for game in recent)
    league, overall = record
    conference_record = "independent" if team["conference"] == "FBS Independent" else f"{'–'.join(league)} in conference"
    refreshed = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"""---
team: {slug}
season: {season}
last_refreshed_at: {refreshed}
---
# {team['name']}

{team['conference']} · Home venue (from schedule) — {venue}. Results through {games[-1][0].date()} UTC. Research cutoff {cutoff.strftime('%Y-%m-%d %H:%M UTC')}.

## Coaching and personnel

Head coach — {coach}.

{personnel}

## Offensive and defensive tendencies

Season ({len(games)} games) — {scored:.1f} points scored and {conceded:.1f} allowed per game.

{tendencies}

## Recent form

Last {len(recent)} completed games — {form_wins}–{len(recent) - form_wins}, {recent_scored:.1f} scored and {recent_conceded:.1f} allowed per game. Dates are UTC.

{chr(10).join(other)}

## Standings and playoff context

{team['conference']} · {conference_record}, {'–'.join(overall)} overall in the NCAA standings published {published} ET. Completed-game sample through the cutoff is {season_wins}–{len(games) - season_wins}.

## Sources

- [NCAA school directory]({team['ncaa_school']})
- [Season schedule]({source.url(schedule_path, season=provider_season)})
{extra_sources}- Game links above provide the source box scores for the recent sample.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, type=stamp, help="Evidence cutoff with UTC offset")
    parser.add_argument("--output-dir", required=True, type=Path, help="Staging directory for team folders")
    parser.add_argument("--cache-dir", required=True, type=Path, help="Dedicated response cache for this cutoff")
    parser.add_argument("--workers", type=int, default=6, choices=range(1, 17))
    parser.add_argument("teams", nargs="*", help="Optional canonical team slugs")
    parser.add_argument("--overrides", type=Path, help="JSON keyed by school slug with sourced coaching corrections")
    args = parser.parse_args()
    if args.as_of > datetime.now(timezone.utc):
        parser.error("--as-of must not be in the future")
    manifest = json.loads((ROOT / "data" / "teams.json").read_text(encoding="utf-8"))
    sport, season, teams = (manifest[key] for key in ("sport", "season", "teams"))
    source = Source(SPORTS[sport][0], args.cache_dir)
    selected = dict.fromkeys(args.teams or teams)
    if selected.keys() - teams.keys():
        parser.error("One or more team slugs are absent from the membership manifest")
    try:
        published, records = official_records(manifest["standings"], args.cache_dir, args.as_of, sport, season)
        if records.keys() != teams.keys():
            raise ValueError("reconcile the manifest with official standings before seeding")
    except (OSError, ValueError, StopIteration) as error:
        parser.error(f"Could not verify standings: {error}")
    overrides = json.loads(args.overrides.read_text(encoding="utf-8")) if args.overrides else {}
    failures, done = [], 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(build_profile, sport, season, source, slug, teams[slug], args.as_of,
                            published, records[slug], overrides.get(slug, {})): slug
                for slug in selected}
        for future in as_completed(jobs):
            slug = jobs[future]
            try:
                body = future.result()
                body += f"- [Official standings]({manifest['standings']})\n"
                folder = args.output_dir / slug
                folder.mkdir(parents=True, exist_ok=True)
                draft = folder / "TEAM.tmp"
                draft.write_text(body, encoding="utf-8")
                draft.replace(folder / "TEAM.md")
                done += 1
                if done % 25 == 0 or done == len(selected):
                    print(f"{sport}: {done}/{len(selected)} profiles", flush=True)
            except (KeyError, ValueError, TypeError, OSError) as error:
                print(f"{slug}: {error}", flush=True)
                failures.append(slug)
    if failures:
        raise SystemExit(f"{len(failures)} profiles need follow-up: {' '.join(sorted(failures))}")


if __name__ == "__main__":
    main()
