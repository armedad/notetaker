# E2E Test Harness Implementation Plan

## Phase 1: Core Infrastructure

### 1.1 Create test harness backend
- Create `app/tests/` directory structure
- Create `app/tests/harness.py` with TestRunner class
- Create `app/routers/testing.py` with API endpoints

### 1.2 Create test harness frontend
- Create `app/static/test.html` test runner page
- Create `app/static/test.js` with TestRunner JS class
- Add route for `/test` page

### 1.3 Logging infrastructure
- Configure test-specific log file
- Create structured log format for test results
- Ensure logs are written to `logs/test_*.log`

**Deliverable:** Can visit `/test` and see list of available suites

---

## Phase 2: Test Suite Framework

### 2.1 Create base test suite class
- `app/tests/base.py` with TestSuite and TestCase classes
- Support for setup/teardown
- Support for async test cases

### 2.2 Create test fixtures
- `app/tests/fixtures/` directory
- Sample audio file for testing
- Mock LLM response files

### 2.3 Create test result reporter
- JSON result format
- Log file writer
- Summary generator (pass/fail counts)

**Deliverable:** Can define and run a simple test suite

---

## Phase 3: Auto Title Test Suite

### 3.1 Implement auto_title.py suite
- AT-001: Check new meeting has no title
- AT-002: Check draft title after transcription
- AT-003: Check final title after summary
- AT-004: Check manual title preserved (before auto)
- AT-005: Check manual title preserved (after auto)

### 3.2 Create necessary fixtures
- Short audio clip for title generation
- Expected title patterns

**Deliverable:** `?suite=auto-title` runs and reports results

---

## Phase 4: Smart Summary Test Suite

### 4.1 Implement smart_summary.py suite
- SS-001: Streaming accumulation
- SS-002: Draft transfer every 30s
- SS-003: LLM transcription cleanup
- SS-004: Topic identification
- SS-005: Completed topic to done
- SS-006: Interim summary updates
- SS-007: Final summary generation

### 4.2 Mock LLM responses
- Create mock responses for deterministic testing
- Store in fixtures/mock_llm_responses/

**Deliverable:** `?suite=smart-summary` runs and reports results

---

## Phase 5: Debug UI Test Suite

### 5.1 Implement debug_ui.py suite
- DU-001: Debug button exists
- DU-002: Two columns render
- DU-003: Left column content
- DU-004: Right column content
- DU-005: Auto-scroll behavior

### 5.2 Frontend testing utilities
- DOM inspection helpers
- Event simulation

**Deliverable:** `?suite=debug-ui` runs and reports results

---

## Phase 6: Diarization Test Suite

### 6.1 Implement diarization.py suite
- DZ-001: Service initialization
- DZ-002: Speaker identification
- DZ-003: Multiple speakers
- DZ-004: Speaker labels in transcript

### 6.2 Test audio with multiple speakers
- Add multi-speaker audio fixture
- Expected speaker count

**Deliverable:** `?suite=diarization` runs and reports results

---

## Phase 7: Integration & Polish

### 7.1 Run all suites
- `?all=true` runs all suites sequentially
- Combined result summary

### 7.2 Documentation
- Update TESTING.md with harness usage
- Add examples for running tests

**Deliverable:** Complete test harness ready for use

---

## File Structure

```
app/
├── routers/
│   └── testing.py          # Test API endpoints
├── static/
│   ├── test.html           # Test runner page
│   └── test.js             # Test runner JS
└── tests/
    ├── __init__.py
    ├── base.py             # Base test classes
    ├── harness.py          # Test orchestration
    ├── fixtures/
    │   ├── sample_audio.wav
    │   └── mock_llm_responses/
    │       ├── title_draft.json
    │       ├── title_final.json
    │       ├── topic_identify.json
    │       └── transcription_cleanup.json
    └── suites/
        ├── __init__.py
        ├── auto_title.py
        ├── smart_summary.py
        ├── debug_ui.py
        └── diarization.py
```
