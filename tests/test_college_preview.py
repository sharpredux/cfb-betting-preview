import argparse
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import context
import team_profiles as profiles


TEAMS = context.membership()["teams"]
SPORT = context.membership()["sport"]
SEASON = context.membership()["season"]
NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)


def game(identifier, start="2026-11-25T16:00:00Z", *, status="STATUS_SCHEDULED",
         team="auburn", neutral=False, confirmed=True, labels=()):
    team_name = TEAMS.get(team, {}).get("name", "North Alabama Lions")
    return {"id": identifier, "start": start, "status": status, "time_confirmed": confirmed,
            "neutral": neutral, "venue": "Site", "week": 0, "labels": labels,
            "teams": [{"team": "alabama", "name": TEAMS["alabama"]["name"]},
                      {"team": team, "name": team_name, "verified_opponent": bool(team_name != "TBD")}]}


def profile(team, refreshed=None, season=SEASON):
    stamp = f"last_refreshed_at: {refreshed:%Y-%m-%dT%H:%M:%SZ}\n" if refreshed else ""
    sections = "\n\n".join(f"{heading}\nEvidence" for heading in profiles.HEADINGS[:-1])
    return f"---\nteam: {team}\nseason: {season}\n{stamp}---\n# Team\n\n{sections}\n\n## Sources\nhttps://example.com/source\n"


class ScheduleTests(unittest.TestCase):
    def test_default_day_uses_manila_midnight_and_dedups(self):
        earlier = game("earlier", "2026-11-24T15:59:59Z")
        first = game("first", "2026-11-24T16:00:00Z", status="STATUS_FINAL")
        last = game("last", "2026-11-25T15:59:59Z")
        later = game("later")
        rows = context.select_games([earlier, first, last, last, later], now=NOW)
        self.assertEqual(["first", "last"], [row["id"] for row in rows])
        self.assertFalse(rows[0]["pregame"])
        self.assertTrue(rows[1]["pregame"])
        self.assertEqual(["2026-11-24", "2026-11-25"], context.slate_window("2026-11-25")["source_dates_et"])

    def test_explicit_date_uses_selected_timezone(self):
        row = game("midnight", "2026-11-25T18:00:00Z")
        self.assertEqual(1, len(context.select_games([row], day=date(2026, 11, 25), zone="UTC", now=NOW)))
        self.assertEqual([], context.select_games([row], day=date(2026, 11, 25), now=NOW))

    def test_mixed_match_requires_both_names(self):
        mixed = game("mixed", team=None, start="2026-11-25T15:30:00Z")
        regular = game("regular")
        self.assertEqual([], context.select_games([mixed], now=NOW))
        self.assertEqual("regular", context.select_games([mixed, regular], names=("alabama",), now=NOW)[0]["id"])
        self.assertEqual("mixed", context.select_games(
            [mixed, regular], names=("alabama", "northalabamalions"), now=NOW,
        )[0]["id"])

    def test_neutral_unknown_time_and_in_progress(self):
        pending = game("pending", neutral=True, confirmed=False)
        live = game("live", status="STATUS_IN_PROGRESS")
        pending, live = context.select_games([pending, live], week=0, now=NOW)[::-1]
        self.assertTrue(pending["neutral"])
        self.assertIsNone(pending["local_start"])
        self.assertFalse(pending["pregame"])
        self.assertFalse(live["pregame"])

    def test_round_label_and_placeholder(self):
        row = game("placeholder", labels=["First Round"], team=None)
        row["teams"][1].update(name="TBD", verified_opponent=False)
        actual = context.select_games([row, game("different")], label="First-Round", now=NOW)
        self.assertEqual(["placeholder"], [game["id"] for game in actual])
        self.assertFalse(actual[0]["pregame"])

    def test_team_alias_ambiguity(self):
        self.assertEqual("miami-fl", context.team_id("Miami (FL)"))
        self.assertNotEqual("miami-fl", context.team_id("Miami (OH)"))
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            context.team_id("Miami")


class ProfileTests(unittest.TestCase):
    def test_freshness_and_season(self):
        at_limit = profile("alabama", NOW - timedelta(minutes=15))
        inside = profile("alabama", NOW - timedelta(minutes=14, seconds=59))
        future = profile("alabama", NOW + timedelta(seconds=1))
        self.assertFalse(profiles.is_fresh(at_limit, "alabama", SEASON, NOW))
        self.assertTrue(profiles.is_fresh(inside, "alabama", SEASON, NOW))
        self.assertFalse(profiles.is_fresh(future, "alabama", SEASON, NOW))
        self.assertFalse(profiles.is_fresh(inside, "alabama", "2023", NOW))

    def test_historical_cutoff_is_strict_and_read_only(self):
        before = profile("alabama", NOW - timedelta(seconds=1))
        at_cutoff = profile("alabama", NOW)
        with patch.object(profiles, "public_profiles", return_value={"alabama": at_cutoff}), \
             patch.object(profiles, "read_local", return_value=before), \
             patch.object(profiles, "save_profiles") as save:
            result = profiles.read_historical(["alabama"], SEASON, NOW)
        self.assertEqual(before, result["teams"]["alabama"]["profile"])
        save.assert_not_called()

    def test_publish_failure_uses_verified_local_draft(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"XDG_CACHE_HOME": directory}), \
             patch.object(profiles, "checkout", return_value=Path(directory)), \
             patch.object(profiles, "push_refreshed", side_effect=OSError("remote unavailable")), \
             patch.object(profiles, "public_profiles", return_value={}), \
             patch.object(profiles, "read_local", return_value=None), \
             patch.object(profiles, "utc_now", return_value=NOW):
            drafts = Path(directory)
            (drafts / "alabama.md").write_text(profile("alabama"), encoding="utf-8")
            args = argparse.Namespace(command="apply", teams=["alabama"], season=SEASON,
                                      publish=True, draft_dir=drafts, historical=False)
            result = profiles.run(args)
            cached = profiles.cached_profiles(["alabama"], SEASON)
        self.assertEqual("local_only", result["teams"]["alabama"]["state"])
        self.assertEqual(result["teams"]["alabama"]["profile"], cached["alabama"])
        self.assertTrue(any("failed" in note for note in result["notes"]))

    def test_bundled_profiles_cover_exact_membership(self):
        self.assertEqual(365 if SPORT == "cbb" else 138, len(TEAMS))
        self.assertEqual(len(TEAMS), len({team["espn_id"] for team in TEAMS.values()}))
        root = context.ROOT / "teams"
        self.assertEqual(set(TEAMS), {row.name for row in root.iterdir() if row.is_dir()})
        for slug in TEAMS:
            with self.subTest(team=slug):
                body = (root / slug / "TEAM.md").read_text(encoding="utf-8")
                self.assertEqual(SEASON, profiles.parse_profile(body, slug)[0])
                self.assertIn("Head coach — ", body)
                self.assertNotIn("Unverified in", body)
                self.assertIn("Usage leaders", body)
                self.assertIn("with both team box scores", body)
                self.assertIn("Official standings", body)


if __name__ == "__main__":
    unittest.main()
