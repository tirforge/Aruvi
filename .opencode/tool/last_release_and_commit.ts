// ABOUTME: Tool to retrieve the last GitHub release tag and its commit SHA
// ABOUTME: Uses gh CLI to query the GitHub releases API
// Ported from nagyv/gitlab-opencode (MIT): the GitLab project releases
// lookup replaced with gh repos/{owner}/{repo}/releases (repo slug resolved via
// GITHUB_REPOSITORY or `gh repo view`, so it works in CI and locally).

import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Gets the last GitHub release tag and its associated commit SHA",
  args: {},
  async execute() {
    const slug =
      (process.env.GITHUB_REPOSITORY ?? "").trim() ||
      (await Bun.$`gh repo view --json nameWithOwner --jq .nameWithOwner`.text()).trim()

    const result =
      await Bun.$`gh api ${`repos/${slug}/releases?per_page=1`}`.json()

    if (!result || result.length === 0) {
      return JSON.stringify({
        error: "No releases found",
        tag: null,
        commit_sha: null,
      })
    }

    const lastRelease = result[0]
    const tag = lastRelease.tag_name

    // NOTE: GitHub's target_commitish is a branch name (e.g. "main"), NOT a
    // SHA — commit_diff needs a real SHA for its from_sha range, so resolve
    // the tag. Falls back to target_commitish if the tag isn't fetched.
    let sha: string = lastRelease.target_commitish
    try {
      const resolved = (await Bun.$`git rev-list -n 1 ${tag}`.text()).trim()
      if (resolved) sha = resolved
    } catch {
      // keep target_commitish fallback
    }

    return JSON.stringify({
      tag,
      commit_sha: sha,
      name: lastRelease.name,
      created_at: lastRelease.created_at,
    })
  },
})
