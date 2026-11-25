# Shared team profiles

Use `teams/<school-slug>/TEAM.md` and season `2026` for the bundled profiles. See `data/teams.json` for canonical IDs, membership and aliases. Store profiles for FBS programs only. For earlier or later seasons, verify eligibility separately. Research a named mixed matchup’s external opponent directly.

## Check participating teams

```sh
python3 scripts/team_profiles.py check --season 2026 alabama auburn
```

Pass only the teams in the requested game or explicitly requested slate, deduplicated. Read each returned profile. The freshness window is zero to less than 15 minutes by the file's UTC timestamp, with the same season. Exactly 15 minutes, future timestamps and invalid profiles require a refresh.

- **shared_fresh** means a verified shared snapshot is available. Continue the independent schedule, market, venue, and availability checks.
- **refresh_required** means research the team. The returned older text is a starting point. Open its underlying sources and confirm or update claims before relying on them.
- **local_only** means a recent local snapshot met the freshness window. Use the verified evidence and mention that the profile stayed local when relevant to a refresh.
- For a **historical** preview, run `check --historical --before 2026-11-20T01:15:00Z --season 2026 alabama auburn` with the actual pregame cutoff. This reads eligible matching-season bundled and public evidence without writing. Verify each returned claim against material available before that cutoff. The current files may be newer than the game, in which case obtain contemporaneous evidence directly. For a future game whose season data has yet to exist, use verified dated background as applicable and keep the shared current-season profiles intact.

If the helper is unavailable, check the corresponding shipped files and GitHub copies. Follow the same freshness and historical rules, and report any unavailable evidence that affects the preview.

## Research and apply

Check the current coach and observed player usage. Verify the program’s conference, home venue, last four games, season and recent tendencies, and conference standings or postseason context. Use official and date-matched school, conference, schedule, roster and game-book sources. Label unknowns, small samples and source delays. Use direct source links. Keep live odds, picks, and player availability in the matchup preview.

For each completed refresh, save a temporary `<school-slug>.md` draft using the headers below. Keep an earlier timestamp when fresh research could not verify a refresh.

```markdown
---
team: alabama
season: 2026
---
# School name

## Coaching and personnel
Confirmed coach and observed usage, with sample dates.

## Offensive and defensive tendencies
Verified season and recent efficiency context.

## Recent form
Completed games and dated scoring sample.

## Standings and playoff context
Verified standings or playoff status at the cutoff.

## Sources
- Direct links to the inspected evidence.
```

```sh
python3 scripts/team_profiles.py apply --season 2026 --draft-dir /path/to/drafts alabama
```

`apply` stamps the verified profile and checks the shared branch again. With user authorization to publish, add `--publish`. The helper fetches the latest shared branch, uses fresh updates already published by collaborators, commits only submitted teams still due, and retries once if the branch advances during the push. It uses a private Git index and leaves the caller's branch, index, and working files intact. Read the returned profile, which may be a collaborator's newer snapshot. If the publish fails or is unavailable, use the local result and disclose that it stayed local.

Use a Git clone with `sharpredux/cfb-betting-preview` as its origin, a configured Git author, and push access to `main` for publication. The helper looks for the skill root or `~/cfb-betting-preview`. Set `CFB_BETTING_PREVIEW_REPO_ROOT` to an alternate checkout. Public reads do not require credentials. Local refreshes are cached per team and season under `${XDG_CACHE_HOME:-~/.cache}/cfb-betting-preview/` without touching the checkout.

## Maintain the membership and baseline

When updating seasons, reconcile the manifest against NCAA and conference membership for actual competition in the sport. Keep school slugs stable, verify provider IDs and aliases, and update the bundled profile set to match the manifest in one change. Reclassifying programs count when confirmed to be competing in FBS for the season.

The batch seeder uses public roster, schedule and box-score data to draft current-season files. Install `requests` and `beautifulsoup4` separately for this maintainer tool. Supply a dedicated response cache and staging directory for the evidence cutoff. Resume an interrupted run with the same cache and rerun only unresolved teams by passing their slugs. Verify roster, coach, venue and standings details against current official sources whenever the provider data differs or is incomplete. Pass `--overrides` for sourced coaching corrections. Use a JSON object keyed by school slug with `coach` and `source` fields. Review the staged profiles before updating the repo.

```sh
python3 scripts/seed_team_profiles.py --as-of 2026-11-25T08:07:00Z     --cache-dir /tmp/cfb-source --output-dir /tmp/cfb-teams
```
