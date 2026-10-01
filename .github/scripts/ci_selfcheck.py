"""CI self-check: structural policy test for the repo's own workflows.

Runs in ci-selfcheck.yml (seconds). Fails the PR if anyone reintroduces a
known-bad pattern: unpinned opencode action, floating actions/* refs,
App-token exchange instead of use_github_token, prompt-only git identity,
job-level matrix gating, COMPLETED wait filter, workflows:write on combo,
missing fixer prompt guards, missing combo concurrency/timeouts/fork-guard/
error-comment, unretried gh reads, unredacted harvest, unparseable YAML,
or bash syntax errors in embedded run scripts.
"""
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
W = ROOT / ".github" / "workflows"
fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


full = (W / "opencode-fullscan.yml").read_text()
combo = (W / "review-combo.yml").read_text()
agent = (W / "merge-agent.yml").read_text()
sweep = (W / "merge-sweep.yml").read_text()

for name, txt in [("fullscan", full), ("combo", combo),
                   ("agent", agent), ("sweep", sweep)]:
    check("anomalyco/opencode/github@latest" not in txt,
          f"{name}: no @latest pin")

# App-token exchange backend is unreliable (502s for days); every opencode
# step must use the repo GITHUB_TOKEN directly or the job silently no-ops
# (sweep burned 6+ runs green-but-dead before this was caught).
import glob as _glob
for _f in ["opencode-fullscan.yml", "review-combo.yml",
           "merge-agent.yml", "merge-sweep.yml"]:
    _y = yaml.safe_load((W / _f).read_text())
    _steps = [s for _j in _y.get("jobs", {}).values()
              for s in ( _j.get("steps", []) if isinstance(_j, dict) else [])
              if isinstance(s, dict)
              and str(s.get("uses", "")).startswith("anomalyco/opencode")]
    check(len(_steps) >= 1 and all(
        (s.get("with") or {}).get("use_github_token") is True
        for s in _steps),
        f"{_f}: all opencode steps use_github_token (no App exchange)")

check("timeout-minutes: 300" in full, "fullscan: 300min timeout")
check("Configure git identity" in full
      and 'git config user.name "Aruvi bot"' in full,
      "fullscan: real git identity step (not prompt-only)")
check("git -c user.name" not in full,
      "fullscan: no prompt-only git -c identity")
# matrix is NOT available in jobs.<job>.if -> gating must be step-level
full_y = yaml.safe_load(full)
check("if" not in full_y["jobs"]["scan"],
      "fullscan: no job-level if (matrix unavailable there)")
scan_step = [s for s in full_y["jobs"]["scan"]["steps"]
             if isinstance(s, dict)
             and str(s.get("uses", "")).startswith("anomalyco/opencode")]
check(len(scan_step) == 1
      and "inputs.area" in str(scan_step[0].get("if", ""))
      and "matrix.area" in str(scan_step[0].get("if", "")),
      "fullscan: step-level area gate")
check(full.count("always() && (github.event_name") == 4,
      "fullscan: verdict+artifact+backstop+delivery gated with always()")
check("Verify delivery" in full and "Fix PR:" in full,
      "fullscan: deterministic delivery gate + PR-URL contract")
check("Open fix PR (workflow-owned delivery backstop)" in full
      and "gh pr create --base main" in full,
      "fullscan: workflow-owned PR backstop (agent gh may hang)")
check("show-ref --verify" in full and "pushed agent's local branch" in full,
      "fullscan: backstop pushes agent's unpushed local branch (503 rescue)")
check("BEFORE final verification" in full,
      "fullscan: prompt orders commit+push before verification")
import json as _json
_oc = _json.loads((ROOT / "opencode.json").read_text())
check(_oc.get("permission", {}).get("*") == "allow",
      "opencode.json: full permission (no ask-prompts stall agents)")

check("Configure git identity" in combo, "combo: git identity step")
check("workflows: write" not in combo,
      "combo: NO workflows:write (suppresses PR runs)")
check("Never touch .github" in combo,
      "combo: prompt guard keeps fixer off .github")
check("Never commit findings/" in combo,
      "combo: prompt guard keeps findings/ out of commits")
gi = (ROOT / ".gitignore").read_text()
check("/findings/" in gi, "gitignore: findings/ is workspace-only")
check('select(.state!="COMPLETED")' not in combo,
      "combo: wait filter not comparing COMPLETED")
check('select(.state!="SUCCESS"' in combo,
      "combo: wait filter uses terminal states")
check("exit 1" in combo, "combo: wait loop fails loud on timeout")
combo_y = yaml.safe_load(combo)
fixer = [s for s in combo_y["jobs"]["fix"]["steps"]
         if isinstance(s, dict)
         and str(s.get("uses", "")).startswith("anomalyco/opencode")]
check(len(fixer) == 1 and fixer[0].get("continue-on-error") is not True,
      "combo: fixer has no continue-on-error")
check("concurrency:" in agent and "timeout-minutes: 120" in agent,
      "agent: concurrency + cap")
check("concurrency:" in sweep, "sweep: serialization")
check("timeout-minutes: 120" in sweep, "sweep: 120min cap")

# Supply-chain: every third-party action pinned to a full commit SHA.
# A floating @vN/@main/@latest tag is a mutable ref — a compromised tag
# poisons all runs. SHA pins (40 hex) never match this pattern.
FLOATING = re.compile(r"^\s*-\s*uses:\s*\S+@(v\d+|latest|main|master)([\s\"']|$)",
                        re.MULTILINE)
for _wf in sorted((W).glob("*.yml")):
    _txt = _wf.read_text()
    check(not FLOATING.search(_txt), f"{_wf.name}: no floating action refs")

# review-combo hardening (cloned from smooth-ai-report-review patterns)
check("review-combo-pr-" in combo and "cancel-in-progress: true" in combo,
      "combo: per-PR concurrency cancels superseded runs")
check("timeout-minutes: 60" in combo and "timeout-minutes: 180" in combo,
      "combo: review(60)/fix(180) timeouts")
check("head.repo.full_name == github.repository" in combo,
      "combo: fix skips fork PRs (read-only token can't push)")
check("Post Error Comment" in combo and "if: failure()" in combo,
      "combo: failure posts logs link to the PR")
check("gh-retry.sh" in combo, "combo: gh reads retried (bounded, once)")
check("redact-secrets.py" in combo, "combo: harvest scrubbed for secrets")
_scripts = ROOT / ".github" / "scripts"
r = subprocess.run(["bash", "-n", str(_scripts / "gh-retry.sh")],
                   capture_output=True, text=True)
check(r.returncode == 0, "gh-retry.sh: bash -n OK")
r = subprocess.run([sys.executable, "-m", "py_compile",
                    str(_scripts / "redact-secrets.py")],
                   capture_output=True, text=True)
check(r.returncode == 0, "redact-secrets.py: py_compile OK")

# Gitleaks toml must EXTEND the default ruleset, not replace it: a config
# without [extend] loads zero rules and every scan passes vacuously.
_toml = (ROOT / ".gitleaks.toml").read_text()
check("useDefault = true" in _toml, "gitleaks: extend/useDefault present")
# The allowlist regex must still match the live curl line in
# harvest-findings.sh — semantic check, not string presence, so the two
# can't drift apart (the stale `$SONAR_TOKEN:` shape once did).
import re as _re
_harvest = (ROOT / ".github" / "scripts" / "harvest-findings.sh").read_text()
_curl_lines = [ln for ln in _harvest.splitlines() if "curl " in ln and "SONAR_TOKEN" in ln]
_allow = _re.findall(r"'''(.+?)'''", _toml.split("[allowlist]", 1)[1])
check(bool(_curl_lines) and any(
    _re.search(rx, ln) for rx in _allow for ln in _curl_lines),
    "gitleaks: allowlist regex matches live SONAR_TOKEN curl line")
_gitleaks = (ROOT / ".gitleaks.toml").read_text()
check("SONAR_TOKEN" in _gitleaks and "curl -sf -u" in _gitleaks,
      "gitleaks: allowlist covers SONAR_TOKEN env-reference line shape")

# Chat-ops + hygiene + scorecard + reusable packaging + spend guard
cmds = (W / "opencode-commands.yml").read_text()
check("'/fix'" in cmds and "'/merge'" in cmds
      and "'/close'" in cmds and "'/sweep'" in cmds,
      "commands: all four chat-ops routed")
check("'/retest'" in cmds and "run rerun --failed" in cmds,
      "commands: /retest reruns failed non-combo runs")
check("needs-human" in combo, "combo: needs-human escalation wired")
check("OWNER" in cmds and "COLLABORATOR" in cmds
      and "author_association" in cmds,
      "commands: collaborator-only gate")
check("run rerun --failed" in cmds, "commands: /fix reruns failed jobs only")
check("trivial" in combo and "lockfile" in combo.lower(),
      "combo: trivial-PR fast path")
check("workflow_call:" in combo and "sonar_project_key" in combo,
      "combo: reusable packaging (workflow_call + sonar key)")
check("inputs.model ||" in combo and "inputs.variant ||" in combo,
      "combo: model/variant parameterized with fallbacks")
check("skills_path" in combo and "verify_commands" in combo,
      "combo: language-agnostic (skills_path + verify_commands)")
check("OPENCODE_API_KEY" in combo and "ANTHROPIC_API_KEY" in combo,
      "combo: model key passthrough declared + mapped")
check("COMBO_MAX_ROUNDS" in combo, "combo: spend guard in fixer prompt")
hy = (W / "pr-hygiene.yml").read_text()
check("auto-close" in hy.lower() and "NEVER auto-closed" in hy,
      "hygiene: bot-only close, humans never")
sc = (W / "scorecard.yml").read_text()
check("scorecard" in sc and "scorecard.py" in sc,
      "scorecard: monthly pinned-issue report")
for _py in ["pr-hygiene.py", "scorecard.py"]:
    r = subprocess.run([sys.executable, "-m", "py_compile",
                        str(_scripts / _py)],
                       capture_output=True, text=True)
    check(r.returncode == 0, f"{_py}: py_compile OK")

# Harvest -> merge chain: one script, fixture-tested, merged-first fixer
check("harvest-findings.sh" in combo, "combo: harvest via shared script")
check("merge-findings.py" in combo and "merged.md" in combo,
      "combo: deduped merged.md wired (merge + summary + fixer)")
r = subprocess.run([sys.executable, "-m", "py_compile",
                    str(_scripts / "merge-findings.py")],
                   capture_output=True, text=True)
check(r.returncode == 0, "merge-findings.py: py_compile OK")
r = subprocess.run(["bash", "-n", str(_scripts / "harvest-findings.sh")],
                   capture_output=True, text=True)
check(r.returncode == 0, "harvest-findings.sh: bash -n OK")
r = subprocess.run(["bash", str(ROOT / ".github/tests/test-harvest.sh")],
                   capture_output=True, text=True, cwd=ROOT)
check(r.returncode == 0 and "HARVEST-FIXTURE-PASS" in r.stdout,
      "harvest fixture test passes (no network)")
r = subprocess.run(["bash", "-n", str(_scripts / "process_opencode_output.sh")],
                   capture_output=True, text=True)
check(r.returncode == 0, "process_opencode_output.sh: bash -n OK")
for f in ["opencode-fullscan.yml", "review-combo.yml",
          "merge-agent.yml", "merge-sweep.yml", "ci-selfcheck.yml"]:
    yaml.safe_load((W / f).read_text())
print("yamls parse OK")
# bash syntax of embedded run scripts
for f, key in [("opencode-fullscan.yml", None),
               ("review-combo.yml", "Wait for Sonar"),
               ("ci-selfcheck.yml", None)]:
    y = yaml.safe_load((W / f).read_text())
    for jn, j in y["jobs"].items():
        for s in j.get("steps", []):
            if isinstance(s, dict) and "run" in s and (
                    key is None or key in str(s.get("name", ""))):
                r = subprocess.run(["bash", "-n"], input=s["run"],
                                   capture_output=True, text=True)
                check(r.returncode == 0,
                      f"{f}/{jn}/{s.get('name', 'run')}: bash -n OK")
print(f"\n{len(fails)} FAILURES" if fails else "\nALL GREEN")
sys.exit(1 if fails else 0)
