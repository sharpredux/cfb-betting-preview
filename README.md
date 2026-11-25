# CFB Betting Preview

A standalone Agent Skill for sourced NCAA FBS football previews and full-game spread, total and moneyline analysis. Name a game for a matchup preview, or omit the game and team for the full local-day slate. Timezone defaults to Asia/Manila.

## Install for Codex

```sh
git clone https://github.com/sharpredux/cfb-betting-preview.git ~/.codex/skills/cfb-betting-preview
```

Codex can select the skill automatically or you can invoke `$cfb-betting-preview` explicitly. Try “Preview Alabama at Auburn” or “Cover FBS Week 0 in 2026.”

## Data and helpers

- This release includes 138 researched profiles for the 2026 season, with one Markdown profile per FBS team.
- [Preview workflow](SKILL.md), [research guide](references/research.md), [market comparison](references/edges.md), and [profile refresh and maintenance](references/team-profiles.md).
- Current previews require accessible live sources. The standard-library runtime helpers require Python 3.9 or later and IANA timezone data. Git is used for shared updates and the batch seeder additionally requires `requests` and `beautifulsoup4`.

Run `python3 -m unittest discover -s tests` from the repository root.

[MIT license](LICENSE).
