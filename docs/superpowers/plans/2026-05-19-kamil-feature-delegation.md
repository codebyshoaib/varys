# Kamil Feature Delegation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `kamil-task-interceptor.py` hook run `/feature <slug>` as a blocking subprocess before Kamil wakes up, so delegation is mechanical rather than instructional.

**Architecture:** Add a `run_feature(slug)` function that calls `claude --dangerously-skip-permissions -p "/feature <slug>"` in taleemabad-core via `subprocess.run`. The hook calls this after git setup, blocks until it completes, then injects a confirmatory (not directive) system message telling Kamil to review the output.

**Tech Stack:** Python 3, subprocess, existing hook structure in `kamil-task-interceptor.py`

---

### Task 1: Add `run_feature` function

**Files:**
- Modify: `/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-task-interceptor.py`

- [ ] **Step 1: Read the current file to know the exact insertion point**

  The function should be added after the existing `git_setup` function (ends around line 161) and before `def main()` (line 163).

- [ ] **Step 2: Add the `run_feature` function**

  Insert this block between `git_setup` and `main`:

  ```python
  def run_feature(slug):
      """Run /feature <slug> as a blocking subprocess in taleemabad-core.
      Returns dict: {ok: bool, output: str, folder: str|None}
      """
      import glob as _glob
      try:
          result = subprocess.run(
              ["claude", "--dangerously-skip-permissions", "-p", f"/feature {slug}"],
              cwd=TALEEMABAD_CORE,
              timeout=1800,
              capture_output=True,
              text=True
          )
          # Find the feature folder that was created
          pattern = os.path.join(TALEEMABAD_CORE, ".claude", "features", f"*{slug}*")
          matches = sorted(_glob.glob(pattern))
          folder = matches[-1] if matches else None
          return {
              "ok": result.returncode == 0,
              "output": result.stdout[-2000:] if result.stdout else result.stderr[-1000:],
              "folder": folder,
              "returncode": result.returncode,
          }
      except subprocess.TimeoutExpired:
          return {"ok": False, "output": "timed out after 30 minutes", "folder": None, "returncode": -1}
      except FileNotFoundError:
          return {"ok": False, "output": "claude binary not found in PATH", "folder": None, "returncode": -2}
      except Exception as e:
          return {"ok": False, "output": str(e), "folder": None, "returncode": -3}
  ```

- [ ] **Step 3: Verify the function is syntactically valid**

  ```bash
  python3 -c "import ast; ast.parse(open('/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-task-interceptor.py').read()); print('OK')"
  ```

  Expected: `OK`

---

### Task 2: Call `run_feature` in `main()` and update the Slack DM

**Files:**
- Modify: `/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-task-interceptor.py`

- [ ] **Step 1: Add the `run_feature` call after git setup in `main()`**

  Find this block in `main()`:

  ```python
      # Step 2: Git setup
      git_ok, git_msg = git_setup(branch_name)
      git_status = f"✅ {git_msg}" if git_ok else f"⚠️ Git: {git_msg}"

      # Step 3: Slack DM
      slack_token = get_slack_token()
      slack_msg = f"🔍 Kamil starting: *{task_description[:100]}*\nBranch: `{branch_name}` | Notion: {notion_url or 'pending'}"
      send_slack_dm(slack_msg, slack_token)
  ```

  Replace with:

  ```python
      # Step 2: Git setup
      git_ok, git_msg = git_setup(branch_name)
      git_status = f"✅ {git_msg}" if git_ok else f"⚠️ Git: {git_msg}"

      # Step 3: Run /feature as blocking subprocess
      feature_result = run_feature(task_slug)
      if feature_result["ok"]:
          feature_status = f"✅ /feature {task_slug} completed"
      elif feature_result["returncode"] == -2:
          feature_status = f"⚠️ claude binary not found — /feature skipped"
      else:
          feature_status = f"⚠️ /feature {task_slug} may have failed (exit {feature_result['returncode']})"

      # Step 4: Slack DM (now includes feature folder)
      slack_token = get_slack_token()
      folder_note = f"\nFeature folder: `{feature_result['folder']}`" if feature_result.get("folder") else ""
      slack_msg = (
          f"🔍 Kamil task ready: *{task_description[:100]}*\n"
          f"Branch: `{branch_name}` | Notion: {notion_url or 'pending'}"
          f"{folder_note}"
      )
      send_slack_dm(slack_msg, slack_token)
  ```

- [ ] **Step 2: Verify syntax**

  ```bash
  python3 -c "import ast; ast.parse(open('/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-task-interceptor.py').read()); print('OK')"
  ```

  Expected: `OK`

---

### Task 3: Replace the advisory system message with a confirmatory one

**Files:**
- Modify: `/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-task-interceptor.py`

- [ ] **Step 1: Locate the system_message block**

  It starts with `system_message = f"""` around line 197. The section to replace is the `━━━ STEP BY STEP ━━━` block — specifically step `1️⃣` which says "YOUR FIRST AND ONLY ACTION RIGHT NOW: Run this bash command immediately".

- [ ] **Step 2: Replace the system_message assignment**

  Find the entire `system_message = f"""..."""` assignment and replace it with the following. Keep all text outside `━━━ STEP BY STEP ━━━` identical. Only replace step `1️⃣` and add the feature status block at the top of `✅ HOOK ALREADY DID`:

  ```python
      # Build feature folder reference for system message
      if feature_result.get("folder"):
          feature_folder_line = f"- /feature ran: `{feature_result['folder']}/`"
      elif feature_result["returncode"] == -2:
          feature_folder_line = "- /feature: skipped (claude binary not found — run it manually)"
      elif feature_result["ok"] is False:
          feature_folder_line = f"- /feature: may have failed (exit {feature_result['returncode']}) — check `.claude/features/` in {TALEEMABAD_CORE}"
      else:
          feature_folder_line = f"- /feature {task_slug}: completed (no folder found — check `.claude/features/`)"

      system_message = f"""
  <system-reminder>
  KAMIL IDENTITY — READ THIS BEFORE ANYTHING ELSE.

  You are Kamil. You are the engineering lead on this task — not a pipeline runner.
  Kamal delegated this to you because he trusts your judgment. Your job is to own the
  outcome: think architecturally, verify the solution is actually correct, and ship
  something you'd be proud to have your name on.

  ✅ HOOK ALREADY DID:
  - Branch: {branch_name} (from develop in {TALEEMABAD_CORE})
  - Notion entry created
  - Slack DM sent to Kamal
  {feature_folder_line}

  TASK: {task_description}
  REPO: {TALEEMABAD_CORE} ONLY.

  ━━━ THE PIPELINE ━━━

  /feature → (Kamil reviews) → /develop → /test → /fix → /deliver

  You are NOT a step runner. You are the senior engineer who:
  - Delegates research to /feature agents
  - Reviews their output like a lead reviewing a junior's work
  - Decides if the proposed solution actually solves the problem
  - Identifies if the harness needs fixing if something goes wrong
  - Owns quality end-to-end

  ━━━ STEP BY STEP ━━━

  1️⃣  YOUR FIRST ACTION — REVIEW /feature OUTPUT:
      /feature has already run. Do NOT grep, explore, or read any files.
      Go directly to the feature folder and review as engineering lead:

      Read research.md — ask yourself:
      ✦ Did the agents actually understand the problem, or did they solve the wrong thing?
      ✦ Are the affected code paths correct and complete?
      ✦ Did they find the real root cause, or just a symptom?
      ✦ Are there risks they missed (multi-tenancy gaps, offline-sync edge cases, migration issues)?

      Read plan.md — ask yourself:
      ✦ Is this the RIGHT solution, or just A solution?
      ✦ Would I be comfortable if Kamal read this plan — does it reflect the real problem?
      ✦ Are the steps ordered correctly with no hidden dependencies?
      ✦ Does every step have a specific file + line reference, or is it vague?
      ✦ Are success criteria measurable, not hand-wavy?
      ✦ Is there a rollback strategy for risky changes?

      If /feature did NOT run (see hook status above):
      → Run: cd {TALEEMABAD_CORE} && claude --dangerously-skip-permissions -p "/feature {task_slug}"
      → Then review as above.

      If the plan is WEAK or WRONG:
      → Do NOT approve it. Update plan.md directly with corrections.
      → If the research missed something fundamental → re-run /feature with a more specific prompt.
      → If the harness agents consistently miss a class of problem → note it for harness improvement.

      If the plan is SOLID:
      → Approve it. Update status.md to mark Phase 1 done.
      → DM Kamal: "📋 Plan approved. Approach: [one sentence on what and why]. Starting /develop."

  2️⃣  DELEGATE implementation to /develop:
      /develop {task_slug}
      Monitor the develop.md as agents work. If they hit a blocker:
      → Read the relevant code yourself and resolve it — don't let them guess.
      → DM Kamal: "⚙️ Implementing. [any notable decision you made]"

  3️⃣  VERIFY with /test → /fix loop:
      /test {task_slug}
      Read test-findings.md. Ask yourself:
      ✦ Do the test results prove the original problem is actually solved?
      ✦ Are the failures real gaps or test setup issues?
      ✦ If confidence is stuck below 86% after 2 loops → is the approach fundamentally flawed?
        If yes → escalate to Kamal with your diagnosis, not just "tests failing".
      If <86%: /fix {{task_slug}} → repeat /test. DM Kamal each loop with score + what changed.

  4️⃣  DELIVER with /deliver:
      /deliver {task_slug}
      This runs all gates → commit → push → PR → /reflect → Notion → DMs Kamal.
      Never create PR manually. Never skip /reflect.

  ━━━ WHEN SOMETHING GOES WRONG ━━━

  If /feature produces a weak plan repeatedly for a class of problem:
  → Check: is the /feature command missing a checklist item for this pattern?
  → If yes: update .claude/commands/feature.md in taleemabad-core to add it.
  → Log the harness gap in Notion Harness DB under "Kamil's own evolution tasks".

  If /develop agents consistently miss a pattern (e.g. always forgetting tenant scope):
  → Check: does .claude/rules/multi-tenancy.md cover this case?
  → If not: add it. The harness is Kamil's responsibility to improve.

  If /test confidence is stuck:
  → Don't just loop /fix blindly. Read the failing tests. Diagnose the root cause.
  → If the solution approach is wrong → go back to plan.md, revise, re-run /develop.

  ━━━ DECISION RULES ━━━
  - Multiple approaches? → pick the one consistent with how the codebase already does it
  - Open question in plan? → read the code, answer it, update plan.md, keep going
  - Scope unclear? → minimal version that provably solves the stated problem
  - Something smells wrong? → stop, diagnose, don't paper over it with more code

  ❌ NEVER grep, explore, or read files before reviewing /feature output
  ❌ NEVER ask Kamal to approve, choose, or answer anything the code can answer
  ❌ NEVER run /develop on a plan you wouldn't stake your reputation on
  ❌ NEVER loop /fix more than 3 times without stopping to re-examine the approach
  ❌ NEVER claim done without ≥86% confidence AND verifier PASS (bug fixes)
  ❌ NEVER create PR manually — always /deliver
  ❌ NEVER ignore a harness gap — if the tooling failed you, fix the tooling
  </system-reminder>
  """
  ```

- [ ] **Step 3: Verify syntax**

  ```bash
  python3 -c "import ast; ast.parse(open('/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-task-interceptor.py').read()); print('OK')"
  ```

  Expected: `OK`

- [ ] **Step 4: Commit**

  ```bash
  cd /home/oye/Documents/free_work/personal-agent-v2
  git add .claude/hooks/kamil-task-interceptor.py
  git commit -m "feat: run /feature as blocking subprocess before Kamil wakes up"
  ```

---

### Task 4: Smoke test the hook

**Files:**
- Read: `/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-task-interceptor.py`

- [ ] **Step 1: Dry-run the hook with a fake trigger**

  ```bash
  echo '{"prompt": "Kamil, work on taleemabad-core — test task smoke check"}' | \
    python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-task-interceptor.py
  ```

  Expected: JSON output with a `systemMessage` key. The message should contain "HOOK ALREADY DID" and either "✅ /feature" or "⚠️ /feature" (not "YOUR FIRST AND ONLY ACTION RIGHT NOW: Run this bash command").

- [ ] **Step 2: Confirm the old advisory wording is gone**

  ```bash
  grep -n "YOUR FIRST AND ONLY ACTION RIGHT NOW" /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-task-interceptor.py
  ```

  Expected: no output (line removed).

- [ ] **Step 3: Confirm the new confirmatory wording is present**

  ```bash
  grep -n "has already run" /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-task-interceptor.py
  ```

  Expected: at least one match.
