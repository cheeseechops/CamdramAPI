(function () {
  "use strict";

  const data = window.CAMDRAM;
  if (!data || data.totalPeople === undefined) return;

  const ROW_HEIGHT = 40;
  const VISIBLE_ROWS = 60;
  const PER_PAGE = 100;
  const SEARCH_DEBOUNCE_MS = 180;
  // Simple mode: render one page of rows, native scroll only (no virtual list = no vanish on scroll)
  const SIMPLE_SCROLL = true;

  const peopleTable = document.getElementById("people-table");
  const peopleTbody = document.getElementById("people-tbody");
  const peopleSpacer = document.getElementById("people-spacer");
  const peopleMeta = document.getElementById("people-meta");
  const peopleCountSpan = document.getElementById("people-count");
  const peopleTotalSpan = document.getElementById("people-total");
  const peopleLoading = document.getElementById("people-loading");
  const peopleScroll = document.getElementById("people-scroll");
  const peopleScrollInner = document.getElementById("people-scroll-inner");
  const searchInput = document.getElementById("search-person");
  const activeOnlyInput = document.getElementById("active-only");
  const societyGrid = document.getElementById("society-grid");
  const venueGrid = document.getElementById("venue-grid");
  const roleList = document.getElementById("role-list");
  const roleRankTitle = document.getElementById("role-rank-title");
  const roleMeta = document.getElementById("role-meta");
  const roleRankTable = document.getElementById("role-rank-table");
  const roleRankTbody = roleRankTable && roleRankTable.querySelector("tbody");
  const includeCount1RolesInput = document.getElementById("include-count1-roles");
  const activeOnlyRolesInput = document.getElementById("active-only-roles");

  const rankingsUrl = data.rankingsUrl || "/api/rankings";
  const rolesUrl = data.rolesUrl || "/api/roles";
  const personUrlTemplate = data.personUrlTemplate || "/person/0";
  let allLoaded = [];
  let totalCount = data.totalPeople || 0;
  let currentSearch = "";
  let currentActiveOnly = false;
  let sortCol = peopleTable.getAttribute("data-sort-col") || "count";
  let sortDir = peopleTable.getAttribute("data-sort-dir") || "desc";
  let fetchInFlight = false;
  let searchDebounce = null;
  let theadHeight = 0;
  let lastVisibleStart = -1;
  let lastVisibleEnd = -1;
  let rafId = null;

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function personStatsUrl(pid) {
    return personUrlTemplate.replace(/0$/, String(pid));
  }

  function buildRow(p) {
    const tr = document.createElement("tr");
    tr.className = "virtual-row";
    tr.setAttribute("data-pid", p.pid);
    tr.setAttribute("data-name", (p.name || "").toLowerCase());
    tr.setAttribute("data-slug", p.slug || "");
    tr.setAttribute("data-count", p.count);
    tr.setAttribute("data-num-shows", p.num_shows);
    tr.setAttribute("data-num-titles", p.num_titles);
    tr.setAttribute("data-top-role", (p.top_role || "").toLowerCase());
    tr.setAttribute("data-top-role-count", p.top_role_count || 0);
    tr.setAttribute("data-credit-date-range", p.credit_date_range || "");
    const topRoleText = p.top_role_count ? p.top_role + " (" + p.top_role_count + ")" : "—";
    const creditRangeText = p.credit_date_range || "—";
    tr.innerHTML =
      '<td class="num">' + escapeHtml(String(p.count)) + "</td>" +
      '<td class="num">' + escapeHtml(String(p.num_shows)) + "</td>" +
      '<td class="num">' + escapeHtml(String(p.num_titles)) + "</td>" +
      '<td class="name"><a href="' + escapeHtml(personStatsUrl(p.pid)) + '">' + escapeHtml(p.name || "") + "</a></td>" +
      '<td class="top-role">' + escapeHtml(creditRangeText) + "</td>" +
      '<td class="top-role">' + escapeHtml(topRoleText) + "</td>";
    return tr;
  }

  function fetchPage(page, search, append) {
    if (fetchInFlight) return Promise.resolve();
    fetchInFlight = true;
    if (!append) peopleLoading && (peopleLoading.style.display = "block");
    const url = rankingsUrl +
      "?page=" + page +
      "&per_page=" + PER_PAGE +
      (search ? "&search=" + encodeURIComponent(search) : "") +
      (currentActiveOnly ? "&active_only=1" : "") +
      "&sort_col=" + encodeURIComponent(sortCol) +
      "&sort_dir=" + encodeURIComponent(sortDir);
    return fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (!append) allLoaded = [];
        allLoaded = allLoaded.concat(res.people || []);
        totalCount = res.total !== undefined ? res.total : allLoaded.length;
        if (peopleScrollInner && peopleTable && totalCount > 0) {
          theadHeight = peopleTable.querySelector("thead").offsetHeight || 0;
          peopleScrollInner.style.height = (theadHeight + totalCount * ROW_HEIGHT) + "px";
        }
        fetchInFlight = false;
        peopleLoading && (peopleLoading.style.display = "none");
        lastVisibleStart = -1;
        lastVisibleEnd = -1;
        if (window.CAMDRAM_SIMPLE_SCROLL) {
          if (typeof window.CAMDRAM_renderSimple === "function") window.CAMDRAM_renderSimple();
        } else {
          renderVirtual();
        }
        updateCounts();
      })
      .catch(function () {
        fetchInFlight = false;
        peopleLoading && (peopleLoading.style.display = "none");
      });
  }

  function ensureDataForRange(start, end) {
    const needEnd = Math.min(end + 1, totalCount);
    const loaded = allLoaded.length;
    if (needEnd <= loaded || totalCount === 0) return Promise.resolve();
    const nextPage = Math.floor(loaded / PER_PAGE) + 1;
    return fetchPage(nextPage, currentSearch, true);
  }

  function renderVirtual() {
    if (!peopleScroll || !peopleTbody || totalCount <= 0) return;
    if (!theadHeight && peopleTable) theadHeight = peopleTable.querySelector("thead").offsetHeight || 0;
    const scrollTop = peopleScroll.scrollTop;
    const bodyScrollTop = Math.max(0, scrollTop - theadHeight);
    let visibleStart = Math.max(0, Math.floor(bodyScrollTop / ROW_HEIGHT));
    let visibleEnd = Math.min(totalCount, visibleStart + VISIBLE_ROWS);
    // Clamp so we never show an empty window (e.g. scroll past end)
    if (visibleStart >= totalCount) visibleStart = Math.max(0, totalCount - VISIBLE_ROWS);
    if (visibleEnd <= visibleStart) visibleEnd = Math.min(totalCount, visibleStart + VISIBLE_ROWS);
    const topHeight = visibleStart * ROW_HEIGHT;
    const bottomHeight = Math.max(0, (totalCount - visibleEnd) * ROW_HEIGHT);

    peopleSpacer.style.height = topHeight + "px";
    peopleSpacer.style.minHeight = topHeight + "px";
    peopleSpacer.style.display = topHeight > 0 ? "table-row" : "none";

    const rangeUnchanged = (lastVisibleStart === visibleStart && lastVisibleEnd === visibleEnd);
    lastVisibleStart = visibleStart;
    lastVisibleEnd = visibleEnd;

    ensureDataForRange(visibleStart, visibleEnd).then(function () {
      const rowCount = Math.min(visibleEnd - visibleStart, allLoaded.length - visibleStart);
      if (rowCount <= 0 && totalCount > 0) return; // safety: don't clear if we'd show nothing
      if (rangeUnchanged && rowCount > 0) {
        const existing = peopleTbody.querySelectorAll("tr.virtual-row").length;
        if (existing === rowCount) return; // already showing correct rows
      }
      peopleTbody.querySelectorAll("tr.virtual-row").forEach(function (r) { r.remove(); });
      const fragment = document.createDocumentFragment();
      for (let i = visibleStart; i < visibleEnd && i < allLoaded.length; i++) {
        fragment.appendChild(buildRow(allLoaded[i]));
      }
      peopleTbody.appendChild(fragment);

      let bottomSpacer = document.getElementById("people-spacer-bottom");
      if (bottomHeight > 0) {
        if (!bottomSpacer) {
          bottomSpacer = document.createElement("tr");
          bottomSpacer.id = "people-spacer-bottom";
          bottomSpacer.className = "virtual-spacer";
          bottomSpacer.setAttribute("aria-hidden", "true");
          bottomSpacer.innerHTML = "<td colspan=\"6\"></td>";
          peopleTbody.appendChild(bottomSpacer);
        }
        bottomSpacer.style.height = bottomHeight + "px";
        bottomSpacer.style.minHeight = bottomHeight + "px";
        bottomSpacer.style.display = "table-row";
      } else if (bottomSpacer) {
        bottomSpacer.style.display = "none";
      }
    });
  }

  function updateCounts() {
    if (peopleTotalSpan) peopleTotalSpan.textContent = totalCount.toLocaleString();
    if (peopleCountSpan) peopleCountSpan.textContent = currentSearch ? totalCount.toLocaleString() + " matching" : totalCount.toLocaleString();
  }

  function onScroll() {
    if (rafId != null) cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(function () {
      rafId = null;
      renderVirtual();
    });
  }

  function reloadPeopleAndResetScroll() {
    fetchPage(1, currentSearch, false).then(function () {
      peopleScroll.scrollTop = 0;
      if (window.CAMDRAM_SIMPLE_SCROLL) {
        maybeLoadMoreSimple();
      } else {
        renderVirtual();
      }
    });
  }

  function maybeLoadMoreSimple() {
    if (!peopleScroll || fetchInFlight) return;
    if (allLoaded.length >= totalCount) return;
    const thresholdPx = 320;
    const nearBottom = peopleScroll.scrollTop + peopleScroll.clientHeight >= peopleScroll.scrollHeight - thresholdPx;
    if (!nearBottom) return;
    const nextPage = Math.floor(allLoaded.length / PER_PAGE) + 1;
    fetchPage(nextPage, currentSearch, true).then(function () {
      // If viewport is still not filled (or user is still near bottom), continue loading.
      maybeLoadMoreSimple();
    });
  }

  peopleScroll.style.height = "70vh";
  peopleScroll.style.overflow = "auto";

  if (SIMPLE_SCROLL) {
    window.CAMDRAM_SIMPLE_SCROLL = true;
    window.CAMDRAM_renderSimple = function () {
      if (!peopleTbody) return;
      peopleTbody.querySelectorAll("tr.virtual-row").forEach(function (r) { r.remove(); });
      peopleSpacer.style.height = "0";
      peopleSpacer.style.display = "none";
      var bot = document.getElementById("people-spacer-bottom");
      if (bot) bot.remove();
      var n = allLoaded.length;
      var fragment = document.createDocumentFragment();
      for (var i = 0; i < n; i++) fragment.appendChild(buildRow(allLoaded[i]));
      peopleTbody.appendChild(fragment);
      if (peopleScrollInner && peopleTable) {
        theadHeight = peopleTable.querySelector("thead").offsetHeight || 0;
        peopleScrollInner.style.height = (theadHeight + n * ROW_HEIGHT) + "px";
      }
    };
    peopleScroll.addEventListener("scroll", maybeLoadMoreSimple, { passive: true });
  } else {
    window.CAMDRAM_SIMPLE_SCROLL = false;
    peopleScroll.addEventListener("scroll", onScroll, { passive: true });
  }

  if (searchInput) {
    searchInput.addEventListener("input", function () {
      clearTimeout(searchDebounce);
      searchDebounce = setTimeout(function () {
        currentSearch = searchInput.value.trim();
        reloadPeopleAndResetScroll();
      }, SEARCH_DEBOUNCE_MS);
    });
  }

  if (activeOnlyInput) {
    activeOnlyInput.addEventListener("change", function () {
      currentActiveOnly = !!activeOnlyInput.checked;
      reloadPeopleAndResetScroll();
    });
  }

  fetchPage(1, "", false).then(function () {
    if (window.CAMDRAM_SIMPLE_SCROLL) maybeLoadMoreSimple();
  });

  function updateSortHeaders() {
    peopleTable.querySelectorAll("thead th").forEach(function (th) {
      const c = th.getAttribute("data-col");
      th.classList.remove("sort-asc", "sort-desc");
      th.setAttribute("aria-sort", "none");
      if (c === sortCol) {
        th.classList.add(sortDir === "asc" ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", sortDir === "asc" ? "ascending" : "descending");
      }
    });
  }

  peopleTable.querySelectorAll("thead th[data-col]").forEach(function (th) {
    th.addEventListener("click", function () {
      const clickedCol = th.getAttribute("data-col");
      if (!clickedCol) return;
      if (clickedCol === sortCol) {
        sortDir = sortDir === "asc" ? "desc" : "asc";
      } else {
        sortCol = clickedCol;
        const type = th.getAttribute("data-type");
        sortDir = type === "string" ? "asc" : "desc";
      }
      peopleTable.setAttribute("data-sort-col", sortCol);
      peopleTable.setAttribute("data-sort-dir", sortDir);
      updateSortHeaders();
      reloadPeopleAndResetScroll();
    });
  });
  updateSortHeaders();

  // --- Tabs ---
  document.querySelectorAll(".tab-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const tab = this.getAttribute("data-tab");
      document.querySelectorAll(".tab-btn").forEach(function (b) {
        b.classList.toggle("active", b.getAttribute("data-tab") === tab);
        b.setAttribute("aria-selected", b.getAttribute("data-tab") === tab ? "true" : "false");
      });
      document.querySelectorAll(".tab-panel").forEach(function (panel) {
        const isActive = panel.id === tab;
        panel.classList.toggle("active", isActive);
        panel.setAttribute("aria-hidden", !isActive);
      });
    });
  });

  // --- By society ---
  function renderSocietyTop() {
    if (!societyGrid) return;
    const societyTop = data.societyTop || [];
    const frag = document.createDocumentFragment();
    societyTop.forEach(function (society) {
      const card = document.createElement("article");
      card.className = "society-card";
      const top = society.top || [];
      let rows = "";
      if (!top.length) {
        rows = "<tr><td colspan=\"3\">No data</td></tr>";
      } else {
        rows = top.map(function (p, idx) {
          const profileUrl = personStatsUrl(p.pid);
          return "<tr>" +
            "<td class=\"num\">" + (idx + 1) + "</td>" +
            "<td class=\"name\"><a href=\"" + profileUrl + "\">" + escapeHtml(p.name || "") + "</a></td>" +
            "<td class=\"num\">" + escapeHtml(String(p.count || 0)) + "</td>" +
            "</tr>";
        }).join("");
      }
      card.innerHTML =
        "<h3>" + escapeHtml(society.label || "Society") + "</h3>" +
        "<div class=\"table-wrap\">" +
        "<table class=\"data-table society-table\">" +
        "<thead><tr><th scope=\"col\">#</th><th scope=\"col\">Name</th><th scope=\"col\">Shows</th></tr></thead>" +
        "<tbody>" + rows + "</tbody>" +
        "</table>" +
        "</div>";
      frag.appendChild(card);
    });
    societyGrid.innerHTML = "";
    societyGrid.appendChild(frag);
  }
  renderSocietyTop();

  function renderVenueTop() {
    if (!venueGrid) return;
    const venueTop = data.venueTop || [];
    const frag = document.createDocumentFragment();
    venueTop.forEach(function (venue) {
      const card = document.createElement("article");
      card.className = "society-card";
      const top = venue.top || [];
      let rows = "";
      if (!top.length) {
        rows = "<tr><td colspan=\"3\">No data</td></tr>";
      } else {
        rows = top.map(function (p, idx) {
          const profileUrl = personStatsUrl(p.pid);
          return "<tr>" +
            "<td class=\"num\">" + (idx + 1) + "</td>" +
            "<td class=\"name\"><a href=\"" + profileUrl + "\">" + escapeHtml(p.name || "") + "</a></td>" +
            "<td class=\"num\">" + escapeHtml(String(p.count || 0)) + "</td>" +
            "</tr>";
        }).join("");
      }
      card.innerHTML =
        "<h3>" + escapeHtml(venue.label || "Venue") + "</h3>" +
        "<p class=\"role-meta\">" + escapeHtml(venue.venue_name || "") + "</p>" +
        "<div class=\"table-wrap\">" +
        "<table class=\"data-table society-table\">" +
        "<thead><tr><th scope=\"col\">#</th><th scope=\"col\">Name</th><th scope=\"col\">Shows</th></tr></thead>" +
        "<tbody>" + rows + "</tbody>" +
        "</table>" +
        "</div>";
      frag.appendChild(card);
    });
    venueGrid.innerHTML = "";
    venueGrid.appendChild(frag);
  }
  renderVenueTop();

  // --- By role ---
  if (!roleList) return;

  let roleDataRoles = data.roles || [];
  let roleDataByRole = data.byRole || {};

  function fetchRoleData(includeCount1, activeOnly) {
    const params = [];
    if (includeCount1) params.push("include_count1=1");
    if (activeOnly) params.push("active_only=1");
    const url = rolesUrl + (params.length ? "?" + params.join("&") : "");
    return fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (res) {
        roleDataRoles = res.roles || [];
        roleDataByRole = res.by_role || {};
      })
      .catch(function () {});
  }

  function reloadRoleDataAndReset() {
    const includeCount1 = !!(includeCount1RolesInput && includeCount1RolesInput.checked);
    const activeOnly = !!(activeOnlyRolesInput && activeOnlyRolesInput.checked);
    fetchRoleData(includeCount1, activeOnly).then(function () {
      renderRoleList();
      roleRankTitle.textContent = "Ranking";
      roleMeta.textContent = "Choose a role from the list.";
      roleRankTbody.innerHTML = "";
    });
  }

  function renderRoleList() {
    const roleFragment = document.createDocumentFragment();
    const mainOrder = ["Tech", "Prod", "Cast", "Band"];
    const roles = roleDataRoles || [];
    mainOrder.forEach(function (main) {
      const inMain = roles.filter(function (r) {
        return (r.main_group || "Prod") === main;
      });
      if (!inMain.length) return;

      const mainHeader = document.createElement("li");
      mainHeader.className = "role-main-header";
      mainHeader.textContent = main;
      roleFragment.appendChild(mainHeader);

      const bySub = {};
      inMain.forEach(function (r) {
        const sub = r.category || "Unknown / Unclassified";
        if (!bySub[sub]) bySub[sub] = [];
        bySub[sub].push(r);
      });

      Object.keys(bySub).sort().forEach(function (sub) {
        const subHeader = document.createElement("li");
        subHeader.className = "role-sub-header";
        subHeader.textContent = sub;
        roleFragment.appendChild(subHeader);

        bySub[sub].sort(function (a, b) {
          if (b.num_people !== a.num_people) return b.num_people - a.num_people;
          return (a.name || "").localeCompare(b.name || "");
        }).forEach(function (r) {
          const li = document.createElement("li");
          li.className = "role-item";
          li.setAttribute("data-role", r.name);
          li.setAttribute("role", "option");
          li.setAttribute("tabindex", "0");
          li.innerHTML = escapeHtml(r.name) + " <span class=\"role-n\">(" + r.num_people + ")</span>";
          li.addEventListener("click", function () { selectRole(li.getAttribute("data-role")); });
          li.addEventListener("keydown", function (e) {
            if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectRole(li.getAttribute("data-role")); }
          });
          roleFragment.appendChild(li);
        });
      });
    });
    roleList.innerHTML = "";
    roleList.appendChild(roleFragment);
  }

  renderRoleList();

  if (includeCount1RolesInput) {
    includeCount1RolesInput.addEventListener("change", function () {
      reloadRoleDataAndReset();
    });
  }

  if (activeOnlyRolesInput) {
    activeOnlyRolesInput.addEventListener("change", function () {
      reloadRoleDataAndReset();
    });
  }

  function selectRole(roleName) {
    if (!roleName) return;
    roleList.querySelectorAll(".role-item").forEach(function (li) {
      li.classList.toggle("selected", li.getAttribute("data-role") === roleName);
    });
    roleRankTitle.textContent = roleName;
    const ranked = roleDataByRole[roleName];
    if (!ranked || !ranked.length) {
      roleMeta.textContent = "No data for this role.";
      roleRankTbody.innerHTML = "";
      return;
    }
    roleMeta.textContent = ranked.length + " people";
    const frag = document.createDocumentFragment();
    let rank = 0;
    let prevCount = null;
    ranked.forEach(function (p, i) {
      if (prevCount === null || p.count !== prevCount) rank = i + 1;
      prevCount = p.count;
      const tr = document.createElement("tr");
      const profileUrl = personStatsUrl(p.pid);
      tr.innerHTML =
        "<td class=\"num\">" + rank + "</td>" +
        "<td class=\"name\"><a href=\"" + profileUrl + "\">" + escapeHtml(p.name || "") + "</a></td>" +
        "<td class=\"num\">" + p.count + "</td>";
      frag.appendChild(tr);
    });
    roleRankTbody.innerHTML = "";
    roleRankTbody.appendChild(frag);
  }
})();
