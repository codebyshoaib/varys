# Worktree Handoff Protocol — for delegated implementers

When the product-lead (or any orchestrator) spawns an implementer with
`isolation: "worktree"`, the agent is given a `worktreePath` and is ALREADY on a
dedicated branch (`worktree-agent-<id>`) created from the parent's HEAD.

**The failure this prevents:** the agent's Bash tool `cwd` defaults to the MAIN
checkout (`/home/shoaib/varys`), not the worktree. So a naive `git checkout -b feat/x
origin/master` runs in the human's working tree — switching its branch, dirtying its
index, and colliding with branches already checked out elsewhere. Twice observed: the
implementer's branch landed in the shared checkout and the main tree had to be
recovered by hand. The deliverable (the pushed branch + PR) was fine; the local repo
was not. This protocol makes that impossible.

## MANDATORY steps for the implementer (paste into every worktree handoff prompt)

1. **First action — go to your worktree and stay there:**
   ```bash
   cd "<worktreePath>"          # the exact path you were given
   git rev-parse --show-toplevel   # MUST print <worktreePath>; if not, STOP and cd again
   ```

2. **Every git/file command runs inside the worktree.** Either operate from
   `cd "<worktreePath>"` or pass `git -C "<worktreePath>" …`. NEVER run git in, cd to,
   or write files under `/home/shoaib/varys` (the human's shared checkout). That tree
   is off-limits.

3. **Do NOT `git checkout -b … origin/master`.** You are already on a fresh branch.
   Just rename it, and (if you need a specific base) reset it — within your worktree:
   ```bash
   git -C "<worktreePath>" branch -m feat/<slug>
   git -C "<worktreePath>" fetch origin
   git -C "<worktreePath>" reset --hard origin/master   # ONLY if the spec says base off master
   ```
   `reset --hard` here moves only YOUR worktree branch — it never touches the shared
   checkout or a branch checked out elsewhere.

4. **Commit / push / PR all from the worktree:**
   ```bash
   git -C "<worktreePath>" add <explicit paths>     # NEVER `git add -A`/`git add .` (hook-blocked)
   git -C "<worktreePath>" commit --no-verify -m "…" # --no-verify avoids the beads dolt pre-commit lock
   git -C "<worktreePath>" push -u origin feat/<slug>
   gh pr create --base <base> --head feat/<slug> --title … --body …
   ```

5. **Exit self-check (REQUIRED before you report done):**
   ```bash
   git -C /home/shoaib/varys status --short   # MUST be empty / unchanged from when you started
   git -C /home/shoaib/varys branch --show-current   # MUST be the branch it was on at start
   ```
   If you dirtied or switched the shared checkout, you broke the protocol — restore it
   (`git -C /home/shoaib/varys checkout -- .`, switch back) and say so in your report.

## Orchestrator cleanup (after the implementer returns)

The branch + PR live on origin; the local worktree + its auto-branch are disposable:
```bash
git worktree remove --force "<worktreePath>"
git worktree prune
git branch -D worktree-agent-<id>     # and any stray local feat/ copy (it's on origin)
```
Then verify the human's checkout is on its original branch with a clean tree.
