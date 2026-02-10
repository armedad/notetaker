/**
 * Test Harness Frontend
 */

const state = {
  suites: [],
  running: false,
  results: null,
};

function log(message, className = "") {
  const panel = document.getElementById("results-panel");
  const line = document.createElement("div");
  line.className = `log-line ${className}`;
  line.textContent = message;
  panel.appendChild(line);
  panel.scrollTop = panel.scrollHeight;
}

function clearLog() {
  const panel = document.getElementById("results-panel");
  panel.innerHTML = "";
}

function setRunning(running) {
  state.running = running;
  const indicator = document.getElementById("running-indicator");
  const runAllBtn = document.getElementById("run-all-btn");

  if (running) {
    indicator.classList.add("active");
    runAllBtn.disabled = true;
    document.querySelectorAll(".suite-run-btn").forEach((btn) => {
      btn.disabled = true;
    });
  } else {
    indicator.classList.remove("active");
    runAllBtn.disabled = false;
    document.querySelectorAll(".suite-run-btn").forEach((btn) => {
      btn.disabled = false;
    });
  }
}

function updateSummary(passed, failed, skipped, errors) {
  document.getElementById("summary-passed").textContent = passed;
  document.getElementById("summary-failed").textContent = failed;
  document.getElementById("summary-skipped").textContent = skipped;
  document.getElementById("summary-errors").textContent = errors;
  document.getElementById("summary-bar").style.display = "flex";
}

function renderSuites(suites) {
  const container = document.getElementById("suite-list");
  container.innerHTML = "";

  suites.forEach((suite) => {
    const card = document.createElement("div");
    card.className = "suite-card";
    card.innerHTML = `
      <h3>
        ${suite.name}
        <span class="suite-id">${suite.suite_id}</span>
      </h3>
      <p>${suite.description || "No description"}</p>
      <div class="test-count">${suite.test_count} tests</div>
      <button class="btn suite-run-btn" data-suite="${suite.suite_id}">
        Run Suite
      </button>
    `;
    container.appendChild(card);
  });

  // Add event listeners
  document.querySelectorAll(".suite-run-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const suiteId = btn.dataset.suite;
      runSuite(suiteId);
    });
  });
}

async function loadSuites() {
  try {
    const response = await fetch("/api/test/suites");
    const data = await response.json();
    state.suites = data.suites || [];
    renderSuites(state.suites);
  } catch (error) {
    log(`Error loading suites: ${error.message}`, "error");
  }
}

function formatResult(result) {
  const statusSymbols = {
    passed: "✓",
    failed: "✗",
    skipped: "○",
    error: "!",
  };
  const statusClasses = {
    passed: "pass",
    failed: "fail",
    skipped: "skip",
    error: "error",
  };

  const symbol = statusSymbols[result.status] || "?";
  const className = statusClasses[result.status] || "";
  const duration = result.duration_ms ? ` (${result.duration_ms.toFixed(1)}ms)` : "";

  return { text: `  [${symbol}] ${result.test_id}: ${result.name}${duration} - ${result.message}`, className };
}

function displayResults(data) {
  if (data.suites) {
    // Multiple suites
    let totalPassed = 0;
    let totalFailed = 0;
    let totalSkipped = 0;
    let totalErrors = 0;

    data.suites.forEach((suite) => {
      log(`\n${"=".repeat(60)}`, "header");
      log(`SUITE: ${suite.name} (${suite.suite_id})`, "header");
      log(`${"=".repeat(60)}`, "header");

      suite.results.forEach((result) => {
        const { text, className } = formatResult(result);
        log(text, className);
      });

      log(`\nSuite Summary: ${suite.passed} passed, ${suite.failed} failed, ${suite.skipped} skipped, ${suite.error} errors`);

      totalPassed += suite.passed;
      totalFailed += suite.failed;
      totalSkipped += suite.skipped;
      totalErrors += suite.error;
    });

    log(`\n${"=".repeat(60)}`, "header");
    log(`OVERALL: ${totalPassed} passed, ${totalFailed} failed, ${totalSkipped} skipped, ${totalErrors} errors`, "header");
    log(`${"=".repeat(60)}`, "header");

    updateSummary(totalPassed, totalFailed, totalSkipped, totalErrors);
  } else if (data.result) {
    // Single suite
    const suite = data.result;

    log(`\n${"=".repeat(60)}`, "header");
    log(`SUITE: ${suite.name} (${suite.suite_id})`, "header");
    log(`${"=".repeat(60)}`, "header");

    suite.results.forEach((result) => {
      const { text, className } = formatResult(result);
      log(text, className);
    });

    log(`\nSummary: ${suite.passed} passed, ${suite.failed} failed, ${suite.skipped} skipped, ${suite.error} errors`);

    updateSummary(suite.passed, suite.failed, suite.skipped, suite.error);
  }

  if (data.log_file) {
    log(`\nLog file: ${data.log_file}`);
  }
}

async function runSuite(suiteId) {
  if (state.running) return;

  setRunning(true);
  clearLog();
  log(`Running suite: ${suiteId}...`, "header");

  try {
    const response = await fetch(`/api/test/run?suite=${encodeURIComponent(suiteId)}`);
    const data = await response.json();

    if (data.status === "error") {
      log(`Error: ${data.message}`, "error");
    } else {
      displayResults(data);
    }
  } catch (error) {
    log(`Error: ${error.message}`, "error");
  } finally {
    setRunning(false);
  }
}

async function runAll() {
  if (state.running) return;

  setRunning(true);
  clearLog();
  log("Running all test suites...", "header");

  try {
    const response = await fetch("/api/test/run?all=true");
    const data = await response.json();

    if (data.status === "error") {
      log(`Error: ${data.message}`, "error");
    } else {
      displayResults(data);
    }
  } catch (error) {
    log(`Error: ${error.message}`, "error");
  } finally {
    setRunning(false);
  }
}

// Check URL params for auto-run
function checkAutoRun() {
  const params = new URLSearchParams(window.location.search);
  const suite = params.get("suite");
  const all = params.get("all");

  if (all === "true") {
    setTimeout(() => runAll(), 500);
  } else if (suite) {
    setTimeout(() => runSuite(suite), 500);
  }
}

// Initialize
document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("run-all-btn").addEventListener("click", runAll);

  await loadSuites();
  checkAutoRun();
});
