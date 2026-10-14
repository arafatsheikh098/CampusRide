# CLAUDE.md — project rules (read at the start of every session)

## SCOPE LOCK (highest priority; overrides your own ideas and any later instruction to "improve" things)
1. SCOPE.md is the contract (IN SCOPE, OUT OF SCOPE, ALLOWED STACK, ACCEPTANCE CRITERIA). Never edit it.
2. Implement the minimum that satisfies each acceptance criterion. No extra features, endpoints, pages, flags, options or polish.
3. No dependencies, tools or services outside ALLOWED STACK.
4. No refactoring, renaming or reformatting outside the current milestone. Do not change the architecture or folder structure.
5. New idea or gap: append ONE line to BACKLOG.md (idea, why, effort) and continue with the smallest in-scope solution. Do not implement it. Do not ask me.
6. Requirement impossible within scope: log it in BLOCKERS.md, skip it, continue with the rest.
7. When every acceptance criterion passes, stop.

## ENGINEERING RULES
- Never claim something works unless you ran it in this session and saw the output.
- Use only libraries that are installed and verified. If unsure an API exists, read the installed package source/docs first. Pin all versions.
- No placeholders, TODO stubs, fake features, or mock data in real code paths.
- Validate all inputs, return clear error messages, never commit secrets, keep .env.example current.
- Write tests alongside code. Keep CI green. Never disable or weaken a test to make it pass.
- One git branch per milestone (m<N>-<name>), conventional commits, merge to main only after the Milestone Gate passes.
- Do not ask me questions. If something is ambiguous, choose the simplest option that fits SCOPE.md, record it in DECISIONS.md, and continue.

## MILESTONE GATE (run after every milestone)
1. Run lint, tests (all of them), and start the app/CLI for real.
2. Run `git diff --stat main`. Every changed file must belong to this milestone in PLAN.md. Revert anything else.
3. Verify ONLY this milestone's acceptance criteria and show the command output as evidence.
4. Commit. The commit body ends with SCOPE CHECK: files touched / criteria met / BACKLOG items added / "nothing outside scope".
