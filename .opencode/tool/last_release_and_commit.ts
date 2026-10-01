// ABOUTME: Tool to retrieve the last GitHub release tag and its commit SHA
// ABOUTME: Uses gh CLI to query the GitHub releases API
// Ported from nagyv/gitlab-opencode (MIT): the GitLab project releases
// lookup replaced with gh repos/{owner}/{repo}/releases (repo slug resolved via
// GITHUB_REPOSITORY or `gh repo view`, so it works in CI and locally).

import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Gets the last GitHub release tag and its associated commit SHA",
  args: {
    target_tag: tool.schema
      .string()
      .optional()
      .describe(
        "Target release tag to exclude from the baseline lookup (the release being documented)"
      ),
  },
  async execute(args) {
    const targetTag = (args.target_tag ?? "").trim()
    const slug =
      (process.env.GITHUB_REPOSITORY ?? "").trim() ||
      (await Bun.$`gh repo view --json nameWithOwner --jq .nameWithOwner`.text()).trim()

    const result =
      await Bun.$`gh api ${`repos/${slug}/releases?per_page=100`}`.json()

    const releases = Array.isArray(result) ? result : []
    // Exclude the target release itself so a first/only release does not
    // become its own baseline (which would yield an empty commit_diff).
    const candidates = targetTag
      ? releases.filter((r) => r?.tag_name !== targetTag)
      : releases

    if (candidates.length === 0) {
      return JSON.stringify({
        error: "No releases found",
        tag: null,
        commit_sha: null,
      })
    }

    const lastRelease = candidates[0]
    const tag = lastRelease.tag_name

    // NOTE: GitHub's target_commitish is a branch name (e.g. "main"), NOT a
    // SHA — never return it as commit_sha. Resolve the immutable tag commit.
    let sha: string | null = null
    try {
      await Bun.$`git fetch --tags --quiet`.text()
    } catch {
      // offline — try local resolve anyway
    }
    try {
      const resolved = (await Bun.$`git rev-list -n 1 ${tag}`.text()).trim()
      if (/^[0-9a-f]{40}$/i.test(resolved)) sha = resolved
    } catch {
      // fall through to explicit error below
    }
    if (!sha) {
      return JSON.stringify({
        error: `could not resolve tag ${tag} to a commit (not fetched)`,
        tag,
        commit_sha: null,
      })
    }

    return JSON.stringify({
      tag,
      commit_sha: sha,
      name: lastRelease.name,
      created_at: lastRelease.created_at,
    })
  },
})
