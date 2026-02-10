# E2E Test Harness Specification

## Objective

Create an end-to-end test harness that can be triggered via URL to systematically test all "in progress" features in the notetaker application. The harness should output detailed logs that enable verification of functionality.

## Target Features to Test

Based on the todo file, these features are marked "in progress":

1. **Auto Meeting Title Generation**
   - Meeting title should auto-generate from content
   - Should generate draft title early in meeting
   - Should update to final title after summarization
   - User manual title should be preserved

2. **Smart Real Time Summary Parsing**
   - Every 30 seconds, prompt LLM to summarize
   - Manage 3 transcript categories: done, draft, streaming
   - Manage 2 summary categories: summarized, interim
   - Clean up transcription errors via LLM
   - Identify topics and move completed topics to "done"

3. **Smart Real Time Summary Debug UI**
   - Debug button in meeting UI
   - Two columns showing content streams
   - Left: done, draft, streaming
   - Right: summarized, interim
   - Auto-scroll to bottom

4. **Diarization (WhisperX)**
   - Speaker identification
   - WhisperX integration working

## Test Harness Requirements

### Triggering
- URL pattern: `/test?suite=<suite_name>` or `/test?all=true`
- Example: `http://localhost:6684/test?suite=auto-title`
- Example: `http://localhost:6684/test?all=true`

### Test Suites
Each suite is independent and can run in isolation:

| Suite ID | Feature | Description |
|----------|---------|-------------|
| `auto-title` | Auto Meeting Title | Tests title generation lifecycle |
| `smart-summary` | Smart Real Time Summary | Tests summary parsing pipeline |
| `debug-ui` | Debug UI | Tests debug panel rendering |
| `diarization` | Diarization | Tests speaker identification |

### Output
- All test output goes to logs directory
- Log file: `logs/test_<suite>_<timestamp>.log`
- Console output for real-time monitoring
- Final summary with PASS/FAIL for each test case

### Test Data
- Use pre-recorded audio file for consistent testing
- Use mock LLM responses where needed for determinism
- Store test fixtures in `app/tests/fixtures/`

## Test Cases

### Suite: auto-title

| Test ID | Description | Expected |
|---------|-------------|----------|
| AT-001 | New meeting has no title initially | title is null or empty |
| AT-002 | After 30s of transcription, draft title generated | title is non-empty string |
| AT-003 | After meeting ends and summary, title updated | title reflects content |
| AT-004 | Manual title set before auto-gen preserved | manual title unchanged |
| AT-005 | Manual title set after auto-gen preserved | manual title unchanged |

### Suite: smart-summary

| Test ID | Description | Expected |
|---------|-------------|----------|
| SS-001 | Streaming text accumulates | streaming buffer grows |
| SS-002 | Every 30s, streaming moves to draft | draft contains cleaned text |
| SS-003 | LLM cleans transcription errors | "gonna" -> "going to" etc |
| SS-004 | Topics identified in draft | topic array populated |
| SS-005 | Completed topic moves to done | done has finalized content |
| SS-006 | Interim summary updates | interim reflects current topic |
| SS-007 | Final summary after topic complete | summarized has topic summary |

### Suite: debug-ui

| Test ID | Description | Expected |
|---------|-------------|----------|
| DU-001 | Debug button exists in meeting page | button visible |
| DU-002 | Click debug shows two columns | left and right panels render |
| DU-003 | Left column has done/draft/streaming | 3 text areas present |
| DU-004 | Right column has summarized/interim | 2 text areas present |
| DU-005 | Content auto-scrolls to bottom | scrollTop near max |

### Suite: diarization

| Test ID | Description | Expected |
|---------|-------------|----------|
| DZ-001 | Diarization service loads | service initialized |
| DZ-002 | Process audio identifies speakers | segments have speaker labels |
| DZ-003 | Multiple speakers distinguished | >1 unique speaker ID |
| DZ-004 | Speaker labels persist in transcript | meeting transcript has speakers |

## Architecture

```
/test                          # Test harness page
  ├── TestRunner (JS class)    # Orchestrates test execution
  ├── TestSuite (JS class)     # Contains test cases
  └── TestReporter (JS class)  # Outputs results to log

/api/test/run                  # Backend test endpoint
  ├── run_suite(suite_id)      # Execute specific suite
  └── get_results()            # Retrieve test results

/app/tests/                    # Test infrastructure
  ├── harness.py               # Test runner backend
  ├── fixtures/                # Test data
  │   ├── sample_audio.wav     # Test audio file
  │   └── mock_llm_responses/  # Canned LLM responses
  └── suites/                  # Test suite implementations
      ├── auto_title.py
      ├── smart_summary.py
      ├── debug_ui.py
      └── diarization.py
```

## Success Criteria

1. All test suites can be triggered via URL
2. Each test outputs clear PASS/FAIL with details
3. Logs are written to `logs/test_*.log`
4. Tests are deterministic (same result on repeated runs)
5. Agent can read logs to verify functionality
