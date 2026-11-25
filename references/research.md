# CFB research guide

## Schedule and venue

Start with the [NCAA scoreboard](https://www.ncaa.com/scoreboard/football/fbs) and official school or conference schedules. Use the [CFP schedule and bracket](https://collegefootballplayoff.com/) or official conference and bowl schedules to verify the season, week, site and round. Provider week numbering or bowl labels can differ. Use official dates and a normalized schedule when needed.

For a local slate, use the date window helper and fetch both overlapping Eastern feed dates when applicable.

```sh
python3 scripts/context.py window --date 2026-11-25
python3 scripts/context.py select scoreboard-1.json scoreboard-2.json --date 2026-11-25 --season 2026
python3 scripts/context.py resolve "alabama"
```

The ESPN event source is `https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=500&dates=YYYYMMDD`. Use both source dates and verify coverage against official schedules. Check for incomplete feeds, false start times and duplicates. Use the season end year for ESPN CBB (2027 for 2026–27), and the season start year for CFB. Use team schedule feeds or official schedules to find the next named game. For non-ESPN inputs or historical membership, write a normalized feed with top-level `season` and `games`. Each game has `id`, offset-aware `start`, `status` (ESPN status vocabulary, with `STATUS_SCHEDULED` for scheduled games), and `teams` (two entries with `name` and `team`, using the canonical slug for in-scope teams or null for others). Optional fields are `time_confirmed`, `neutral`, `venue`, `week` and `labels`. A placeholder team has `verified_opponent: false`. Use `--team`, `--matchup`, `--week` (CFB), or `--label` for those scopes. Supply explicit round or bowl labels as verified on the official schedule.

Count Eastern calendar days between the last played kickoff and the confirmed next kickoff. Flag byes, unusual short weeks and venue changes. Use prior-venue to game-venue great-circle miles and label the estimate. For exposed venues, check kickoff wind, gusts, precipitation and temperature from the [National Weather Service](https://www.weather.gov/) or the local official weather service. Verify roof status. Verify that a previous game actually occurred before computing rest.

## Availability

Use conference reports where applicable, school game notes, depth charts, press conferences and credible team reporting. Check quarterback, line, and high-impact defensive personnel, plus coaching changes, portal departures, suspensions and opt-outs for bowls. Published depth charts can be stale. If a material status is unresolved, evaluate plausible scenarios and recheck the affected price. When no reliable update is published, state the gap. Hold an affected market if confirmed availability could change the direction.

## Form and matchup

Compare scoring for and against, pace, yards/play, success rate or EPA where sourced, opponent quality, explosiveness, turnover variation, and offense/defense strengths. Explain sample and garbage-time treatment for advanced metrics. Separate FCS results when assessing against comparable opposition. Compare line play and pressure, especially when quarterback or protection status is uncertain. Start from the matching-season profiles and confirm the latest significant changes directly. In historical requests, use reports, prices and samples available before the scheduled start.
