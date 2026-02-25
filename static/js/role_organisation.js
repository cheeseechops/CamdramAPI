(function () {
  "use strict";

  const cfg = window.CAMDRAM_ROLE_ORG || {};
  if (!cfg.bootstrapUrl || !cfg.updateUrl || !cfg.deleteUrl) return;

  const searchInput = document.getElementById("role-org-search");
  const sourceList = document.getElementById("role-org-source-list");
  const selectedMeta = document.getElementById("role-org-selected-meta");
  const targetInput = document.getElementById("role-org-target");
  const consolidateBtn = document.getElementById("role-org-consolidate-btn");
  const feedbackEl = document.getElementById("role-org-feedback");
  const groupsEl = document.getElementById("role-org-groups");
  const summaryMeta = document.getElementById("role-org-summary-meta");

  if (!searchInput || !sourceList || !selectedMeta || !targetInput || !consolidateBtn || !feedbackEl || !groupsEl || !summaryMeta) {
    return;
  }

  let roleOptions = [];
  let consolidations = [];
  let selected = new Set();
  let query = "";
  let renderToken = 0;
  let searchDebounce = null;
  const SEARCH_DEBOUNCE_MS = 120;
  const SOURCE_RENDER_CHUNK = 220;

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function selectedValues() {
    return roleOptions.filter(function (r) { return selected.has(r.name); }).map(function (r) { return r.name; });
  }

  function updateSelectedMeta(filteredCount) {
    if (typeof filteredCount === "number") {
      selectedMeta.textContent =
        selected.size + " selected · showing " + filteredCount + " of " + roleOptions.length;
      return;
    }
    selectedMeta.textContent = selected.size + " selected";
  }

  function roleCountLabel(r) {
    return typeof r.count === "number" ? " (" + r.count + ")" : "";
  }

  function roleMatchesQuery(role, q) {
    if (!q) return true;
    return (role.name || "").toLowerCase().indexOf(q) >= 0;
  }

  function createSourceItem(role) {
    const li = document.createElement("li");
    li.className = "role-org-source-item";
    const checked = selected.has(role.name) ? " checked" : "";
    li.innerHTML =
      "<label>" +
      "<input type=\"checkbox\" data-role=\"" + escapeHtml(role.name) + "\"" + checked + ">" +
      "<span>" + escapeHtml(role.name) + "<span class=\"role-n\">" + roleCountLabel(role) + "</span></span>" +
      "</label>";
    return li;
  }

  function renderSourceList() {
    const q = query.trim().toLowerCase();
    const filtered = roleOptions.filter(function (r) { return roleMatchesQuery(r, q); });
    const token = ++renderToken;
    sourceList.innerHTML = "";
    updateSelectedMeta(filtered.length);

    function appendChunk(startIdx) {
      if (token !== renderToken) return;
      const endIdx = Math.min(filtered.length, startIdx + SOURCE_RENDER_CHUNK);
      const frag = document.createDocumentFragment();
      for (let i = startIdx; i < endIdx; i++) {
        frag.appendChild(createSourceItem(filtered[i]));
      }
      sourceList.appendChild(frag);
      if (endIdx < filtered.length) {
        requestAnimationFrame(function () {
          appendChunk(endIdx);
        });
      }
    }

    appendChunk(0);
  }

  function renderConsolidations() {
    const totalGroups = consolidations.length;
    const totalFuture = consolidations.reduce(function (sum, c) {
      return sum + (Array.isArray(c.future_sources) ? c.future_sources.length : 0);
    }, 0);
    summaryMeta.textContent = totalGroups + " consolidated targets, " + totalFuture + " future-only source mappings";

    if (!totalGroups) {
      groupsEl.innerHTML = "<p class=\"role-meta\">No consolidations yet.</p>";
      return;
    }

    const frag = document.createDocumentFragment();
    consolidations.forEach(function (group) {
      const card = document.createElement("section");
      card.className = "role-org-group";

      const activeCount = (group.active_sources || []).length;
      const futureCount = (group.future_sources || []).length;
      const header = document.createElement("div");
      header.className = "role-org-group-header";
      header.innerHTML =
        "<h4>" + escapeHtml(group.target || "") + "</h4>" +
        "<p class=\"role-meta\">" + activeCount + " active, " + futureCount + " future</p>" +
        "<button type=\"button\" class=\"role-org-btn role-org-btn--danger\" data-remove-target=\"" + escapeHtml(group.target || "") + "\">Remove target mapping</button>";
      card.appendChild(header);

      const list = document.createElement("ul");
      list.className = "role-org-mapping-list";
      (group.sources || []).forEach(function (sourceName) {
        const isFuture = (group.future_sources || []).indexOf(sourceName) >= 0;
        const li = document.createElement("li");
        li.className = "role-org-mapping-item";
        li.innerHTML =
          "<span>" + escapeHtml(sourceName) + (isFuture ? " <em>(future)</em>" : "") + "</span>" +
          "<button type=\"button\" class=\"role-org-link-btn\" data-remove-source=\"" + escapeHtml(sourceName) + "\">remove</button>";
        list.appendChild(li);
      });
      card.appendChild(list);
      frag.appendChild(card);
    });

    groupsEl.innerHTML = "";
    groupsEl.appendChild(frag);

  }

  function applyPayload(payload) {
    roleOptions = Array.isArray(payload.available_roles) ? payload.available_roles : [];
    consolidations = Array.isArray(payload.consolidations) ? payload.consolidations : [];
    renderSourceList();
    renderConsolidations();
  }

  function fetchPayload() {
    return fetch(cfg.bootstrapUrl)
      .then(function (r) { return r.json(); })
      .then(function (payload) {
        applyPayload(payload);
      });
  }

  function setFeedback(message, isError) {
    feedbackEl.textContent = message;
    feedbackEl.classList.toggle("role-org-error", !!isError);
  }

  function consolidate() {
    const sourceRoles = selectedValues();
    const targetRole = (targetInput.value || "").trim();
    if (!sourceRoles.length) {
      setFeedback("Select at least one source role.", true);
      return;
    }
    if (!targetRole) {
      setFeedback("Enter a target role.", true);
      return;
    }
    consolidateBtn.disabled = true;
    fetch(cfg.updateUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        targetRole: targetRole,
        sourceRoles: sourceRoles
      })
    })
      .then(function (r) { return r.json(); })
      .then(function (payload) {
        if (!payload.ok) {
          setFeedback(payload.error || "Could not save consolidation.", true);
          return;
        }
        selected = new Set();
        targetInput.value = "";
        applyPayload(payload);
        setFeedback("Saved " + (payload.changed || 0) + " consolidation mapping(s).", false);
      })
      .catch(function () {
        setFeedback("Could not save consolidation.", true);
      })
      .finally(function () {
        consolidateBtn.disabled = false;
      });
  }

  function removeMapping(body) {
    fetch(cfg.deleteUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    })
      .then(function (r) { return r.json(); })
      .then(function (payload) {
        if (!payload.ok) {
          setFeedback(payload.error || "Could not remove mapping.", true);
          return;
        }
        applyPayload(payload);
        setFeedback("Removed " + (payload.changed || 0) + " mapping(s).", false);
      })
      .catch(function () {
        setFeedback("Could not remove mapping.", true);
      });
  }

  searchInput.addEventListener("input", function () {
    if (searchDebounce) clearTimeout(searchDebounce);
    searchDebounce = setTimeout(function () {
      query = searchInput.value || "";
      renderSourceList();
    }, SEARCH_DEBOUNCE_MS);
  });

  sourceList.addEventListener("change", function (e) {
    const target = e.target;
    if (!target || target.tagName !== "INPUT") return;
    const role = target.getAttribute("data-role");
    if (!role) return;
    if (target.checked) selected.add(role);
    else selected.delete(role);
    updateSelectedMeta();
  });

  groupsEl.addEventListener("click", function (e) {
    const btn = e.target;
    if (!btn || btn.tagName !== "BUTTON") return;
    const sourceRole = btn.getAttribute("data-remove-source");
    if (sourceRole) {
      removeMapping({ sourceRole: sourceRole });
      return;
    }
    const targetRole = btn.getAttribute("data-remove-target");
    if (targetRole) {
      removeMapping({ targetRole: targetRole });
    }
  });

  consolidateBtn.addEventListener("click", consolidate);

  fetchPayload().catch(function () {
    setFeedback("Could not load role consolidation data.", true);
  });
})();
