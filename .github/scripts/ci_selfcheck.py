"""CI self-check: structural policy test for the repo's own workflows.

Runs in ci-selfcheck.yml (seconds). Fails the PR if anyone reintroduces a
known-bad pattern: unpinned opencode action, App-token exchange instead of
use_github_token, prompt-only git identity,
job-level matrix gating, COMPLETED wait filter, workflows:write on combo,
missing fixer prompt guards, unparseable YAML, or bash syntax errors in
embedded run scripts.
"""
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
check(full.count("always() && (github.event_name") == 2,
      "fullscan: verdict+artifact gated with always()")

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
