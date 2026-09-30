---
description: Write the release notes
agent: plan
---

Write release notes for version $ARGUMENTS.

Ported from nagyv/gitlab-opencode (MIT) `opencode-configs/release-management`:
GitLab CLI calls replaced with `gh`, GitLab releases with GitHub releases.
Read-only command: never edit code, never push, never open PRs.

## Process

1. **Get previous release**: Use the `last_release_and_commit` tool to retrieve
   the most recent release tag and its commit SHA. If no release exists yet
   (tool returns an error with commit_sha null), do NOT use the root commit
   as exclusive from_sha (a `root..TAG` range drops the initial commit).
   Run `git log --format=... $ARGUMENTS` to list all commits reachable from
   $ARGUMENTS. Run `git diff --stat $(git hash-object -t tree /dev/null)
   $ARGUMENTS` to compare the release tree against the empty tree. Do not pass
   the empty-tree SHA to `commit_diff` (it runs `git log from..to`, which
   needs commits, not a tree object).

2. **Get changes**: Use the `commit_diff` tool with the previous release's
   commit SHA as `from_sha` and the git ref for version $ARGUMENTS as `to_sha`
   to retrieve all commits and changes included in this release.

3. **Analyze changes**: Review the commit subjects, authors, and diff summary
   to understand what changed.

4. **Write release notes**: Generate concise, user-focused release notes in
   markdown format that:
   - Summarize the key changes in plain language
   - Group related changes together (e.g., "Features", "Bug Fixes", "Improvements")
   - Highlight breaking changes prominently if any
   - Credit contributors where appropriate
   - Keep technical jargon minimal - focus on what users care about

## Output Format

The release notes should follow this structure:

```markdown
## What's New

Brief summary of the most important changes.

### Features
- Feature descriptions (if any)

### Improvements
- Improvement descriptions (if any)

### Bug Fixes
- Bug fix descriptions (if any)

### Breaking Changes
- Breaking change descriptions (if any)

---
Contributors: @author1, @author2
```

Only include sections that have content. Omit empty sections.

ONLY RETURN THE RELEASE NOTES WITHOUT ANY WRAPPING TEXT.
