const API_PREFIX = "/api/v1";

const state = {
  portfolioId: null,
  portfolio: null,
  savedPortfolios: [],
  dependencyResponse: null,
  paths: [],
  busy: false,
};

const els = {
  apiStatus: document.querySelector("#api-status"),
  portfolioName: document.querySelector("#portfolio-name"),
  positions: document.querySelector("#positions"),
  positionTemplate: document.querySelector("#position-row-template"),
  weightTotal: document.querySelector("#weight-total"),
  addPosition: document.querySelector("#add-position"),
  equalizeWeights: document.querySelector("#equalize-weights"),
  demoButton: document.querySelector("#demo-button"),
  createSync: document.querySelector("#create-sync"),
  portfolioIdInput: document.querySelector("#portfolio-id"),
  loadExisting: document.querySelector("#load-existing"),
  runPipeline: document.querySelector("#run-pipeline"),
  refreshSaved: document.querySelector("#refresh-saved"),
  savedPortfolios: document.querySelector("#saved-portfolios"),
  holdingsCard: document.querySelector("#holdings-card"),
  holdingsSummary: document.querySelector("#holdings-summary"),
  holdingsList: document.querySelector("#holdings-list"),
  processQueue: document.querySelector("#process-queue"),
  sessionCard: document.querySelector("#session-card"),
  activePortfolioId: document.querySelector("#active-portfolio-id"),
  copyId: document.querySelector("#copy-id"),
  clearLog: document.querySelector("#clear-log"),
  activityLog: document.querySelector("#activity-log"),
  resultsTitle: document.querySelector("#results-title"),
  refreshPaths: document.querySelector("#refresh-paths"),
  summaryGrid: document.querySelector("#summary-grid"),
  metricPaths: document.querySelector("#metric-paths"),
  metricSuppliers: document.querySelector("#metric-suppliers"),
  metricCompanies: document.querySelector("#metric-companies"),
  metricEvidence: document.querySelector("#metric-evidence"),
  basisCard: document.querySelector("#basis-card"),
  weightBasis: document.querySelector("#weight-basis"),
  dependencyBasis: document.querySelector("#dependency-basis"),
  filters: document.querySelector("#filters"),
  pathSearch: document.querySelector("#path-search"),
  roleFilter: document.querySelector("#role-filter"),
  empty: document.querySelector("#results-empty"),
  dependencyList: document.querySelector("#dependency-list"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function normalizeRole(role) {
  return String(role || "").replaceAll("_", " ");
}

function formatWeight(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return `${number.toFixed(number % 1 === 0 ? 1 : 2)}%`;
}

function addLog(message, kind = "muted") {
  const p = document.createElement("p");
  p.className = kind;
  p.textContent = message;
  if (els.activityLog.querySelector(".muted")?.textContent === "Ready.") {
    els.activityLog.innerHTML = "";
  }
  els.activityLog.prepend(p);
}

function setBusy(isBusy, label = null) {
  state.busy = isBusy;
  els.createSync.disabled = isBusy;
  els.loadExisting.disabled = isBusy;
  els.refreshPaths.disabled = isBusy || !state.portfolioId;
  els.runPipeline.disabled = isBusy || !state.portfolioId;
  els.addPosition.disabled = isBusy;
  els.equalizeWeights.disabled = isBusy;
  els.demoButton.disabled = isBusy;
  els.refreshSaved.disabled = isBusy;
  els.savedPortfolios.querySelectorAll("button").forEach((button) => { button.disabled = isBusy; });
  els.processQueue.disabled = isBusy || !hasActiveEnrichment(state.portfolio);

  const labelSpan = els.createSync.querySelector("span:first-child");
  labelSpan.textContent = label || "Create & sync portfolio";
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  let body = null;
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    body = await response.json();
  } else {
    body = await response.text();
  }

  if (!response.ok) {
    const detail = body?.detail || body || `HTTP ${response.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  return body;
}

async function checkHealth() {
  try {
    const body = await requestJson("/health", { headers: {} });
    els.apiStatus.classList.remove("error");
    els.apiStatus.classList.add("ok");
    els.apiStatus.querySelector("span:last-child").textContent = body.status === "ok" ? "API online" : "API responding";
  } catch (error) {
    els.apiStatus.classList.remove("ok");
    els.apiStatus.classList.add("error");
    els.apiStatus.querySelector("span:last-child").textContent = "API unavailable";
  }
}

const ASSET_STATUS_TONE = {
  ready: "good",
  pending_enrichment: "wait",
  unsupported: "bad",
  invalid: "bad",
};
const JOB_STATUS_TONE = {
  queued: "wait",
  processing: "wait",
  completed: "good",
  failed: "bad",
};
const PORTFOLIO_STATUS_TONE = { ready: "good", partially_ready: "wait" };

function statusChip(status, tones) {
  const tone = tones[status] || "";
  return `<span class="status-chip ${tone}">${escapeHtml(normalizeRole(status))}</span>`;
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}

function latestJobsByTicker(portfolio) {
  const jobs = new Map();
  for (const job of portfolio?.enrichment_jobs || []) {
    const current = jobs.get(job.ticker);
    if (!current || job.updated_at > current.updated_at) jobs.set(job.ticker, job);
  }
  return jobs;
}

function hasActiveEnrichment(portfolio) {
  return [...latestJobsByTicker(portfolio).values()]
    .some((job) => job.status === "queued" || job.status === "processing");
}

async function loadSavedPortfolios() {
  try {
    state.savedPortfolios = await requestJson(`${API_PREFIX}/portfolios?limit=25`, { headers: {} });
    renderSavedPortfolios();
  } catch (error) {
    els.savedPortfolios.innerHTML = '<p class="error">Could not load saved portfolios.</p>';
    addLog(`Saved portfolios: ${error.message}`, "error");
  }
}

function renderSavedPortfolios() {
  if (!state.savedPortfolios.length) {
    els.savedPortfolios.innerHTML = '<p class="muted">No saved portfolios yet.</p>';
    return;
  }
  els.savedPortfolios.innerHTML = state.savedPortfolios.map((portfolio) => {
    const tickers = portfolio.positions.map((position) => position.ticker).join(", ");
    const active = portfolio.portfolio_id === state.portfolioId ? " active" : "";
    return `
      <button class="saved-item${active}" type="button" data-portfolio-id="${escapeHtml(portfolio.portfolio_id)}">
        <strong>${escapeHtml(portfolio.name)}</strong>
        ${statusChip(portfolio.status, PORTFOLIO_STATUS_TONE)}
        <small>${escapeHtml(tickers)} · ${escapeHtml(formatDate(portfolio.created_at))}</small>
      </button>
    `;
  }).join("");
  els.savedPortfolios.querySelectorAll(".saved-item").forEach((button) => {
    button.disabled = state.busy;
    button.addEventListener("click", () => openPortfolio(button.dataset.portfolioId));
  });
}

async function loadPortfolioDetails(portfolioId = state.portfolioId) {
  try {
    state.portfolio = await requestJson(`${API_PREFIX}/portfolios/${portfolioId}`, { headers: {} });
  } catch (error) {
    state.portfolio = null;
  }
  renderHoldings();
  return state.portfolio;
}

function renderHoldings() {
  const portfolio = state.portfolio;
  els.holdingsCard.hidden = !portfolio;
  els.processQueue.disabled = state.busy || !hasActiveEnrichment(portfolio);
  if (!portfolio) return;

  const jobs = latestJobsByTicker(portfolio);
  const notReady = portfolio.positions.filter((position) => position.asset.status !== "ready").length;
  els.holdingsSummary.innerHTML = `${escapeHtml(portfolio.name)} · ${statusChip(portfolio.status, PORTFOLIO_STATUS_TONE)} · ${
    notReady
      ? `${notReady} of ${portfolio.positions.length} holdings not resolved yet. Unresolved holdings are left out of the graph until enrichment resolves them.`
      : `All ${portfolio.positions.length} holdings resolved.`
  }`;

  els.holdingsList.innerHTML = portfolio.positions.map((position) => {
    const asset = position.asset;
    const job = jobs.get(position.ticker);
    const label = asset.company_name || (asset.asset_type !== "unknown" ? asset.asset_type : "");
    let jobLine = "";
    if (job && asset.status !== "ready") {
      const attempts = `${job.attempts} attempt${job.attempts === 1 ? "" : "s"}`;
      const error = job.last_error ? ` · ${job.last_error}` : "";
      const retry = job.status === "queued" && job.next_attempt_at
        ? ` · next retry ${formatDate(job.next_attempt_at)}`
        : "";
      jobLine = `<div class="holding-job${job.status === "failed" ? " error" : ""}">Enrichment ${escapeHtml(job.status)} · ${escapeHtml(attempts)}${escapeHtml(retry)}${escapeHtml(error)}</div>`;
    }
    return `
      <div class="holding-row">
        <span class="holding-ticker">${escapeHtml(position.ticker)}</span>
        <span class="holding-weight">${escapeHtml(formatWeight(position.weight_pct))}</span>
        <span class="holding-name">${escapeHtml(label)}</span>
        ${statusChip(asset.status, ASSET_STATUS_TONE)}
        ${jobLine}
      </div>
    `;
  }).join("");
}

async function processEnrichmentQueue() {
  if (!state.portfolioId) return;
  const id = state.portfolioId;
  const before = new Set(
    (state.portfolio?.positions || [])
      .filter((position) => position.asset.status === "ready")
      .map((position) => position.ticker),
  );

  try {
    setBusy(true, "Processing enrichment…");
    addLog("Processing enrichment queue…", "running");
    const result = await requestJson(`${API_PREFIX}/enrichment-jobs/process?limit=10`, { method: "POST" });
    if (!result.jobs_claimed) {
      addLog("No enrichment jobs are due yet; queued jobs wait for their next retry time.", "running");
    } else {
      addLog(
        `Enrichment: ${result.jobs_completed} resolved, ${result.jobs_requeued} requeued, ${result.jobs_failed} failed.`,
        result.jobs_failed ? "error" : result.jobs_completed ? "success" : "running",
      );
    }

    const portfolio = await loadPortfolioDetails(id);
    const newlyReady = (portfolio?.positions || [])
      .filter((position) => position.asset.status === "ready" && !before.has(position.ticker));
    if (newlyReady.length) {
      addLog(`Resolved ${newlyReady.map((position) => position.ticker).join(", ")}; re-syncing graph…`, "running");
      const sync = await requestJson(`${API_PREFIX}/portfolios/${id}/graph/sync`, { method: "POST" });
      addLog(`Graph synced: ${sync.companies_synced} companies.`, "success");
      await loadDependencyPaths(id);
    }
    await loadSavedPortfolios();
  } catch (error) {
    addLog(`Enrichment stopped: ${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

async function openPortfolio(portfolioId) {
  setActivePortfolio(portfolioId);
  renderSavedPortfolios();
  const portfolio = await loadPortfolioDetails(portfolioId);
  if (!portfolio) {
    renderLoadError("Portfolio not found");
    addLog("Portfolio not found.", "error");
    return;
  }
  addLog(`Opened “${portfolio.name}”.`, "success");
  await loadDependencyPaths(portfolioId);
}

function addPositionRow(ticker = "", weight = "") {
  const fragment = els.positionTemplate.content.cloneNode(true);
  const row = fragment.querySelector(".position-row");
  const tickerInput = row.querySelector(".ticker-input");
  const weightInput = row.querySelector(".weight-input");
  const removeButton = row.querySelector(".remove-position");

  tickerInput.value = ticker;
  weightInput.value = weight;
  tickerInput.addEventListener("input", () => {
    tickerInput.value = tickerInput.value.toUpperCase().replace(/\s+/g, "");
  });
  weightInput.addEventListener("input", updateWeightTotal);
  removeButton.addEventListener("click", () => {
    if (els.positions.children.length <= 1) return;
    row.remove();
    updateWeightTotal();
  });

  els.positions.appendChild(fragment);
  updateWeightTotal();
}

function replacePositions(items) {
  els.positions.innerHTML = "";
  items.forEach((item) => addPositionRow(item.ticker, item.weight));
  updateWeightTotal();
}

function updateWeightTotal() {
  const total = [...els.positions.querySelectorAll(".weight-input")]
    .reduce((sum, input) => sum + (Number(input.value) || 0), 0);
  els.weightTotal.textContent = `${total.toFixed(2)}%`;
  els.weightTotal.classList.toggle("invalid", Math.abs(total - 100) > 0.01);
}

function equalizeWeights() {
  const inputs = [...els.positions.querySelectorAll(".weight-input")];
  if (!inputs.length) return;
  const base = Math.floor((100 / inputs.length) * 100) / 100;
  let assigned = 0;
  inputs.forEach((input, index) => {
    const value = index === inputs.length - 1 ? 100 - assigned : base;
    input.value = value.toFixed(2);
    assigned += value;
  });
  updateWeightTotal();
}

function collectPortfolioPayload() {
  const name = els.portfolioName.value.trim();
  if (!name) throw new Error("Portfolio name is required.");

  const rows = [...els.positions.querySelectorAll(".position-row")];
  const positions = rows.map((row) => ({
    ticker: row.querySelector(".ticker-input").value.trim().toUpperCase(),
    weight_pct: Number(row.querySelector(".weight-input").value),
  }));

  if (positions.some((position) => !position.ticker)) {
    throw new Error("Every position needs a ticker.");
  }
  if (positions.some((position) => !Number.isFinite(position.weight_pct) || position.weight_pct <= 0)) {
    throw new Error("Every position needs a positive weight.");
  }

  const tickers = positions.map((position) => position.ticker);
  if (new Set(tickers).size !== tickers.length) {
    throw new Error("Duplicate tickers are not allowed.");
  }

  const total = positions.reduce((sum, position) => sum + position.weight_pct, 0);
  if (Math.abs(total - 100) > 0.01) {
    throw new Error(`Portfolio weights must sum to 100%. Current total: ${total.toFixed(2)}%.`);
  }

  return { name, positions };
}

function setActivePortfolio(portfolioId) {
  state.portfolioId = portfolioId;
  els.portfolioIdInput.value = portfolioId;
  els.activePortfolioId.textContent = portfolioId;
  els.sessionCard.hidden = false;
  els.refreshPaths.disabled = false;
  els.runPipeline.disabled = false;
}

async function createAndSyncPortfolio() {
  try {
    setBusy(true, "Creating portfolio…");
    const payload = collectPortfolioPayload();
    addLog(`Creating “${payload.name}”…`, "running");
    const portfolio = await requestJson(`${API_PREFIX}/portfolios`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setActivePortfolio(portfolio.portfolio_id);
    state.portfolio = portfolio;
    renderHoldings();
    addLog(`Portfolio created: ${portfolio.portfolio_id}`, "success");
    if (hasActiveEnrichment(portfolio)) {
      const pending = [...latestJobsByTicker(portfolio).keys()].join(", ");
      addLog(`Queued for enrichment: ${pending}.`, "running");
    }

    setBusy(true, "Syncing graph…");
    const sync = await requestJson(`${API_PREFIX}/portfolios/${portfolio.portfolio_id}/graph/sync`, {
      method: "POST",
    });
    const unresolved = sync.unresolved_company_assets?.length || 0;
    addLog(`Graph synced: ${sync.companies_synced} companies, ${unresolved} unresolved assets.`, unresolved ? "running" : "success");

    await loadDependencyPaths(portfolio.portfolio_id);
  } catch (error) {
    addLog(error.message, "error");
  } finally {
    setBusy(false);
    loadSavedPortfolios();
  }
}

async function loadExistingPortfolio() {
  const portfolioId = els.portfolioIdInput.value.trim();
  if (!portfolioId) {
    addLog("Enter a portfolio ID first.", "error");
    return;
  }
  await openPortfolio(portfolioId);
}

async function loadDependencyPaths(portfolioId = state.portfolioId) {
  if (!portfolioId) return;
  try {
    setBusy(true, "Loading dependencies…");
    addLog("Loading dependency paths…", "running");
    const body = await requestJson(`${API_PREFIX}/portfolios/${portfolioId}/graph/dependency-paths?limit=500`, {
      headers: {},
    });
    state.dependencyResponse = body;
    state.paths = body.paths || [];
    renderDependencyResponse();
    addLog(`Loaded ${state.paths.length} dependency path${state.paths.length === 1 ? "" : "s"}.`, "success");
  } catch (error) {
    renderLoadError(error.message);
    addLog(error.message, "error");
  } finally {
    setBusy(false);
  }
}

async function runPipeline() {
  if (!state.portfolioId) return;
  const id = state.portfolioId;
  const stages = [
    ["Graph sync", `${API_PREFIX}/portfolios/${id}/graph/sync`],
    ["SEC filings", `${API_PREFIX}/portfolios/${id}/graph/sec-filings/sync?company_limit=5&filings_per_company=4`],
    ["Filing evidence", `${API_PREFIX}/portfolios/${id}/graph/filing-evidence/sync?filing_limit=8&evidence_per_filing=8`],
    ["Semantic candidates", `${API_PREFIX}/portfolios/${id}/graph/evidence-semantic-candidates/sync?evidence_limit=20&candidates_per_evidence=10`],
    ["Supplier resolution", `${API_PREFIX}/portfolios/${id}/graph/candidate-entities/sync?candidate_limit=100`],
    ["Dependency promotion", `${API_PREFIX}/portfolios/${id}/graph/evidence-backed-dependencies/sync?candidate_limit=100`],
  ];

  try {
    setBusy(true, "Running pipeline…");
    for (const [label, url] of stages) {
      addLog(`${label}…`, "running");
      await requestJson(url, { method: "POST" });
      addLog(`${label} complete.`, "success");
    }
    await loadDependencyPaths(id);
  } catch (error) {
    addLog(`Pipeline stopped: ${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

function renderLoadError(message) {
  els.resultsTitle.textContent = "Unable to load paths";
  els.summaryGrid.hidden = true;
  els.basisCard.hidden = true;
  els.filters.hidden = true;
  els.dependencyList.innerHTML = "";
  els.empty.hidden = false;
  els.empty.querySelector("h3").textContent = "Dependency paths unavailable";
  els.empty.querySelector("p").textContent = message.includes("Portfolio not found")
    ? "That portfolio does not exist on this backend. With the default in-memory store (PORTFOLIO_STORE=memory), portfolios are lost when the server restarts."
    : message;
}

function renderDependencyResponse() {
  const body = state.dependencyResponse;
  const paths = state.paths;
  const suppliers = new Set(paths.map((path) => path.supplier_id));
  const companies = new Set(paths.map((path) => path.company_cik));
  const evidence = new Set(paths.flatMap((path) => path.provenance.map((item) => item.evidence_id)));

  els.resultsTitle.textContent = paths.length ? "Evidence-backed dependencies" : "No promoted dependencies yet";
  els.metricPaths.textContent = String(paths.length);
  els.metricSuppliers.textContent = String(suppliers.size);
  els.metricCompanies.textContent = String(companies.size);
  els.metricEvidence.textContent = String(evidence.size);
  els.summaryGrid.hidden = false;

  els.weightBasis.textContent = body.weight_basis || "";
  els.dependencyBasis.textContent = body.dependency_basis || "";
  els.basisCard.hidden = false;

  populateRoleFilter(paths);
  els.filters.hidden = paths.length === 0;
  els.empty.hidden = paths.length !== 0;
  if (!paths.length) {
    els.empty.querySelector("h3").textContent = "No promoted dependencies found";
    els.empty.querySelector("p").textContent = "The portfolio is synced, but its companies do not have promoted supplier dependencies yet. Run the optional dependency pipeline if the required providers are configured.";
  }

  renderFilteredPaths();
}

function populateRoleFilter(paths) {
  const previous = els.roleFilter.value;
  const roles = [...new Set(paths.flatMap((path) => path.roles || []))].sort();
  els.roleFilter.innerHTML = '<option value="">All roles</option>' + roles
    .map((role) => `<option value="${escapeHtml(role)}">${escapeHtml(normalizeRole(role))}</option>`)
    .join("");
  if (roles.includes(previous)) els.roleFilter.value = previous;
}

function renderFilteredPaths() {
  const search = els.pathSearch.value.trim().toLowerCase();
  const role = els.roleFilter.value;
  const filtered = state.paths.filter((path) => {
    const haystack = [
      ...(path.asset_path || []),
      path.company_name,
      path.supplier_name,
      ...(path.roles || []),
    ].join(" ").toLowerCase();
    const searchMatch = !search || haystack.includes(search);
    const roleMatch = !role || (path.roles || []).includes(role);
    return searchMatch && roleMatch;
  });

  els.dependencyList.innerHTML = filtered.map(renderPathCard).join("");
  if (state.paths.length && !filtered.length) {
    els.dependencyList.innerHTML = '<div class="empty-state"><div class="empty-mark">⌕</div><h3>No matching paths</h3><p>Change the search or role filter to see more dependencies.</p></div>';
  }
}

function renderPathCard(path) {
  const pathNodes = [...(path.asset_path || []), path.company_name, path.supplier_name];
  const pathHtml = pathNodes.map((node, index) => {
    const nodeHtml = `<span class="path-node">${escapeHtml(node)}</span>`;
    return index === pathNodes.length - 1 ? nodeHtml : `${nodeHtml}<span class="path-arrow">→</span>`;
  }).join("");

  const roles = (path.roles || []).map((role) => `<span class="role-chip">${escapeHtml(normalizeRole(role))}</span>`).join("");
  const provenance = (path.provenance || []).map(renderEvidenceCard).join("");
  const evidenceLabel = `${path.provenance?.length || 0} provenance record${path.provenance?.length === 1 ? "" : "s"}`;

  return `
    <article class="dependency-card">
      <div class="dependency-main">
        <div>
          <div class="path-line">${pathHtml}</div>
          <h3 class="supplier-title">${escapeHtml(path.supplier_name)}</h3>
          <div class="company-subtitle">Dependent company: ${escapeHtml(path.company_name)} · CIK ${escapeHtml(path.company_cik)}</div>
          <div class="role-list">${roles}</div>
        </div>
        <div class="weight-block">
          <span>Company path weight</span>
          <strong>${escapeHtml(formatWeight(path.company_path_weight_pct))}</strong>
          <small>Not supplier impact</small>
        </div>
      </div>
      <details class="provenance-details">
        <summary>${escapeHtml(evidenceLabel)}</summary>
        <div class="provenance-stack">${provenance}</div>
      </details>
    </article>
  `;
}

function renderEvidenceCard(item) {
  const sourceUrl = /^https:\/\//i.test(item.source_url || "") ? item.source_url : "";
  const sourceLink = sourceUrl
    ? `<a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noreferrer">Open SEC source ↗</a>`
    : "Source unavailable";

  return `
    <div class="evidence-card">
      <div class="evidence-topline">
        <span class="evidence-role">${escapeHtml(normalizeRole(item.role))}</span>
        <span class="evidence-mention">Mention: ${escapeHtml(item.object_mention)}</span>
      </div>
      <blockquote>${escapeHtml(item.supporting_text)}</blockquote>
      <div class="evidence-meta">
        <span>${escapeHtml(item.source_date)}</span>
        <span>Accession ${escapeHtml(item.accession_number)}</span>
        ${sourceLink}
      </div>
      <div class="method-line">
        ${escapeHtml(item.extraction_method)} · ${escapeHtml(item.model_name)} · ${escapeHtml(item.entity_resolution_method)}
      </div>
    </div>
  `;
}

els.addPosition.addEventListener("click", () => addPositionRow("", ""));
els.equalizeWeights.addEventListener("click", equalizeWeights);
els.demoButton.addEventListener("click", () => {
  els.portfolioName.value = "NVIDIA Dependency View";
  replacePositions([{ ticker: "NVDA", weight: "100.00" }]);
});
els.createSync.addEventListener("click", createAndSyncPortfolio);
els.loadExisting.addEventListener("click", loadExistingPortfolio);
els.runPipeline.addEventListener("click", runPipeline);
els.refreshPaths.addEventListener("click", () => loadDependencyPaths());
els.refreshSaved.addEventListener("click", loadSavedPortfolios);
els.processQueue.addEventListener("click", processEnrichmentQueue);
els.pathSearch.addEventListener("input", renderFilteredPaths);
els.roleFilter.addEventListener("change", renderFilteredPaths);
els.copyId.addEventListener("click", async () => {
  if (!state.portfolioId) return;
  try {
    await navigator.clipboard.writeText(state.portfolioId);
    addLog("Portfolio ID copied.", "success");
  } catch (error) {
    addLog("Could not copy automatically. Select the portfolio ID manually.", "error");
  }
});
els.clearLog.addEventListener("click", () => {
  els.activityLog.innerHTML = '<p class="muted">Ready.</p>';
});

replacePositions([{ ticker: "NVDA", weight: "100.00" }]);
checkHealth();
loadSavedPortfolios();
