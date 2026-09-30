# Aruvi Pipeline — autonomous review → fix → merge → release

Five workflows, one maintainer loop. Every finding ships fix code; humans
handle only what the bot flags `needs-human`. Dogfooded daily on this repo.

## The loop

| Workflow | Trigger | Job |
|---|---|---|
| `review-combo` | PR opened/sync (path-filtered) | opencode review → wait Sonar/CodeQL → harvest → dedupe → opencode fix + push |
| `opencode-commands` | PR comment `/fix /retest /merge /close /sweep` | chat-ops router (collaborators only) |
| `merge-agent` | manual dispatch | verify green → merge, or close with reason. Never bypasses protection |
| `merge-sweep` | every 6h + `/sweep` | merge green bot PRs, digest the rest. Human PRs untouched |
| `opencode-fullscan` | weekly + manual | full-tree audit per area, opens fix PRs |
| `pr-hygiene` | weekly + manual | nudge stale PRs; auto-close stale *bot* PRs only — humans never |
| `scorecard` | monthly + manual | green rate + loop pressure on a pinned issue |
| `opencode-release-notes` | tag push | harvest commits since last tag → GitHub Release |
| `opencode-smoke` | manual + CI | pipeline self-test |

## Consume it (one `uses:` line)

See `docs/combo-caller.example.yml`. Reusable entry: `review-combo`
(`workflow_call`). Path filtering lives in YOUR caller. Secrets: same-org
uses `secrets: inherit`; cross-org maps each key explicitly.

## Secrets

| Secret | Required | What |
|---|---|---|
| `GITHUB_TOKEN` | automatic | PR ops, pushes, dispatches |
| `SONAR_TOKEN` | if you use Sonar | harvests SonarCloud issues (empty on dependabot → CLEAN fallback) |
| `OPENCODE_API_KEY` | if `model: opencode/*` (paid Zen) | default free model needs nothing |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` | if `model:` needs them | only the selected provider's key is routed |

## Inputs (`with:`)

| Input | Default | What |
|---|---|---|
| `model` | free contributor model | any opencode model id |
| `variant` | `xhigh` | effort tier |
| `sonar_project_key` | `tirforge_Aruvi` | your SonarCloud component key |
| `enable_coderabbit` | `true` | third signal (needs the CodeRabbit app) |
| `skills_path` | `.opencode/skills` | your agent skill files; absent = built-in rigor |
| `verify_commands` | ruff + tsc + vite | **how YOUR stack verifies — set this per language** |

Repo Variables: `COMBO_MAX_ROUNDS` (default `3`) caps fixer rounds.

## Safety model

- Minimal `permissions:` per job; all third-party actions SHA-pinned (selfcheck fails floating refs).
- Fork PRs: review runs read-only; fix pass skips (read-only token can't push).
- `gh` reads get one bounded retry; writes are never retried blind.
- Harvest is scrubbed for credential-shaped literals before summary/artifacts.
- Findings merge deterministically (same file:line = one entry, sources tagged).
- Dead fixer → logs link + `needs-human` label; dirty-but-unfixable (dependabot) → same label.
- Concurrency: one combo per PR (superseded runs cancel); sweeps serialize.

## Costs

Free-tier friendly: default model costs nothing; paid models burn on
review + up to `COMBO_MAX_ROUNDS` fix rounds. Lockfile-only PRs skip the
review burn automatically; `/fix` reruns failed jobs only, never the full pass.
