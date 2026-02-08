# Debug Session: Server not coming up

**Status:** INVESTIGATING
**Started:** 2026-02-07
**Drive:** /Users/chee/projects/notetaker

---

## 1. Investigation (Evidence Gathering)
**Goal:** Gather Hard Evidence (logs, traces) of *what* is failing.

- [ ] **Reproduction Steps:**
  1. Run `./notetaker.sh`.
  2. Observe launcher output and server log creation.
  3. Check latest launcher/server logs for errors.

- [ ] **Hard Evidence Collected:**
  - [x] Launcher log shows server log path created but server log empty.
  - [x] `curl http://127.0.0.1:6684/api/health` failed (exit code 7).
  - [x] `lsof -i :6684` returned no listener.

**Current State:** Uvicorn appears not to start or exits immediately without writing logs.

---

## 2. Diagnosis (Hypothesis Board)
**Goal:** List potential causes, track their status, and avoid repeating work.

**Hypothesis Status:** `PENDING` (To do), `TESTING` (In progress), `RULED_OUT` (Proven false), `CONFIRMED` (Proven true).

| ID | Hypothesis (I believe X because Y...) | Status | Test/Evidence |
|----|---------------------------------------|--------|---------------|
| H1 | No server log is created due to bad log path | RULED_OUT | Server log file is created at expected path |
| H2 | Uvicorn exits immediately with error | PENDING | Add uvicorn exit code logs |
| H3 | Port 6684 already in use | RULED_OUT | `lsof -i :6684` shows no listener |

**Active Hypothesis Verification Plan:**
- **Selected Hypothesis:** [TBD]
- **Test Case:** `[TBD]`
- **Result:** `[TBD]`

---

## 3. Fix & Verify (Resolution)
**Goal:** Apply minimal fix and confirm with new logs.

- [ ] **The Fix:**
  - [ ] File(s) modified: `[]`
  - [ ] Description: `[]`

- [ ] **Verification (Post-Fix):**
  - [ ] Reproduction steps run again?
  - [ ] **New Logs:** `[]`

---

## Retrospective
- **Root Cause Category:** [TBD]
- **Prevention:** [TBD]
