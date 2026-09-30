// ABOUTME: Tool to get commit history and change summary between two commits
// ABOUTME: Provides commit messages and diff stats for release analysis
// Ported from nagyv/gitlab-opencode (MIT): git-based, no forge CLI needed,
// so it works unchanged on GitHub.

import { tool } from "@opencode-ai/plugin"

export default tool({
  description:
    "Gets the commit history and changes between two commits for release analysis",
  args: {
    from_sha: tool.schema
      .string()
      .describe("Starting commit SHA (exclusive, typically the last release commit)"),
    to_sha: tool.schema
      .string()
      .optional()
      .describe("Ending commit SHA (inclusive, defaults to HEAD)"),
  },
  async execute(args) {
    const fromSha = args.from_sha
    const toSha = args.to_sha || "HEAD"

    // Get commit log using a delimiter that won't appear in commit data
    const DELIM = "<<<COMMIT>>>"
    const FIELD_DELIM = "<<<FIELD>>>"
    const commitLog =
      await Bun.$`git log --format=${`%H${FIELD_DELIM}%h${FIELD_DELIM}%s${FIELD_DELIM}%an${DELIM}`} ${fromSha}..${toSha}`.text()

    // Parse commits
    const commits = commitLog
      .trim()
      .split(DELIM)
      .filter((line: string) => line.trim())
      .map((line: string) => {
        const [sha, short_sha, subject, author] = line.trim().split(FIELD_DELIM)
        return { sha, short_sha, subject, author }
      })

    // Get diff stats
    const diffStats = await Bun.$`git diff --stat ${fromSha}..${toSha}`.text()

    return JSON.stringify({
      from_sha: fromSha,
      to_sha: toSha,
      commit_count: commits.length,
      commits: commits.map((c) => ({
        sha: c.short_sha,
        subject: c.subject,
        author: c.author,
      })),
      diff_summary: diffStats.trim(),
    })
  },
})
