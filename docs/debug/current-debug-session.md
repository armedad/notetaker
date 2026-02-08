# Debug Session: Server crash during recording start

**Status:** DIAGNOSING
**Started:** 2026-02-05
**Drive:** /Users/chee/projects/notetaker

---

## 1. Investigation (Evidence Gathering)
**Goal:** Gather Hard Evidence (logs, traces) of *what* is failing.

- [x] **Reproduction Steps:**
  1. Start server with `notetaker.sh`
  2. Open UI at http://localhost:6684
  3. Select audio device, start recording
  4. Status above buttons stays "Not recording" (even after start)

- [x] **Hard Evidence Collected:**
  - [x] Latest crash log unchanged (last modified 00:39) — no new bus error captured after RawInputStream change
  - [x] Server logs show recording start and continuous callbacks until shutdown, but no stop request

**Current State:** The server process becomes defunct immediately after recording start, with no Python traceback in logs. This suggests a crash below Python (likely C-extension or PortAudio). Need deeper crash logging.

---

## 2. Diagnosis (Hypothesis Board)
**Goal:** List potential causes, track their status, and avoid repeating work.

| ID | Hypothesis (I believe X because Y...) | Status | Test/Evidence |
|----|---------------------------------------|--------|---------------|
| H1 | Start API call blocks/hangs in backend | TESTING | Add timing logs around API start/stop and apply curl timeouts |
| H2 | RawInputStream resolves numpy bus error but server still restarts due to another shutdown trigger | PENDING | Inspect uvicorn shutdown cause in logs |
| H2 | Server fails on startup due to invalid faulthandler signal registration | CONFIRMED | `RuntimeError: signal 11/6 cannot be registered` in launcher log |

**Active Hypothesis Verification Plan:**
- **Selected Hypothesis:** H1
- **Test Case:** Add verbose logging in stop path; reproduce stop hang
- **Result:** Pending

---

## 3. Fix & Verify (Resolution)
**Goal:** Apply minimal fix and confirm with new logs.

- [ ] **The Fix:**
  - [ ] File(s) modified: 
  - [ ] Description:

- [ ] **Verification (Post-Fix):**
  - [ ] Reproduction steps run again?
  - [ ] **New Logs:** 

---

## Retrospective
- **Root Cause Category:** TBD
- **Prevention:** TBD
