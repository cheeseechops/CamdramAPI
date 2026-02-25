(function () {
  "use strict";

  const data = window.CAMDRAM_GAME;
  if (!data || !data.byRole) return;

  const promptEl = document.getElementById("game-prompt");
  const roleEl = document.getElementById("game-role");
  const optionsEl = document.getElementById("game-options");
  const feedbackEl = document.getElementById("game-feedback");
  const scoreEl = document.getElementById("game-score");
  const nextBtn = document.getElementById("game-next-btn");
  const modeButtons = document.querySelectorAll(".game-mode-btn");

  if (!promptEl || !roleEl || !optionsEl || !feedbackEl || !scoreEl || !nextBtn) return;

  const byRole = data.byRole || {};
  const rolesMeta = Array.isArray(data.roles) ? data.roles : [];
  const TOP_ROLE_LIMIT = 20;
  const techRoleNames = rolesMeta
    .filter(function (r) {
      return r && r.main_group === "Tech" && byRole[r.name];
    })
    .map(function (r) {
      return r.name;
    });

  const topRoleNames = techRoleNames
    .map(function (roleName) {
      const ranked = byRole[roleName] || [];
      const totalDoneCount = ranked.reduce(function (sum, person) {
        return sum + (person.count || 0);
      }, 0);
      return {
        roleName: roleName,
        totalDoneCount: totalDoneCount,
        numPeople: ranked.length
      };
    })
    .sort(function (a, b) {
      if (b.totalDoneCount !== a.totalDoneCount) return b.totalDoneCount - a.totalDoneCount;
      if (b.numPeople !== a.numPeople) return b.numPeople - a.numPeople;
      return a.roleName.localeCompare(b.roleName);
    })
    .slice(0, TOP_ROLE_LIMIT)
    .map(function (r) { return r.roleName; });

  const eligibleRoles = topRoleNames.filter(function (roleName) {
    const ranked = byRole[roleName];
    return Array.isArray(ranked) && ranked.length >= 3;
  });

  let score = 0;
  let attempts = 0;
  let currentMode = "most-role";
  let question = null;

  function randomInt(maxExclusive) {
    return Math.floor(Math.random() * maxExclusive);
  }

  function sampleN(items, n) {
    const pool = items.slice();
    for (let i = pool.length - 1; i > 0; i--) {
      const j = randomInt(i + 1);
      const tmp = pool[i];
      pool[i] = pool[j];
      pool[j] = tmp;
    }
    return pool.slice(0, n);
  }

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function updateScore() {
    scoreEl.innerHTML = "Score: <strong>" + score + "/" + attempts + "</strong>";
  }

  function resetScore() {
    score = 0;
    attempts = 0;
    updateScore();
  }

  function buildMostRoleQuestion() {
    for (let tries = 0; tries < 200; tries++) {
      const roleName = eligibleRoles[randomInt(eligibleRoles.length)];
      const ranked = byRole[roleName];
      if (!ranked || ranked.length < 3) continue;

      const pool = ranked.slice(0, Math.min(ranked.length, 12));
      const options = sampleN(pool, 3);
      if (options.length < 3) continue;

      let maxCount = -1;
      options.forEach(function (p) {
        if ((p.count || 0) > maxCount) maxCount = p.count || 0;
      });
      const winners = options.filter(function (p) {
        return (p.count || 0) === maxCount;
      });
      if (winners.length !== 1) continue;

      return {
        mode: "most-role",
        prompt: "Who has done this Tech role most?",
        title: roleName,
        options: options.map(function (p) {
          return {
            id: "pid:" + String(p.pid),
            label: p.name || "Unknown",
            isCorrect: p.pid === winners[0].pid
          };
        }),
        revealText: winners[0].name + " has the highest count for this role."
      };
    }
    return null;
  }

  function buildHigherCountQuestion() {
    for (let tries = 0; tries < 200; tries++) {
      const roleName = eligibleRoles[randomInt(eligibleRoles.length)];
      const ranked = byRole[roleName];
      if (!ranked || ranked.length < 2) continue;

      const pool = ranked.slice(0, Math.min(ranked.length, 14));
      const options = sampleN(pool, 2);
      if (options.length < 2) continue;
      if ((options[0].count || 0) === (options[1].count || 0)) continue;

      const winner = (options[0].count || 0) > (options[1].count || 0) ? options[0] : options[1];
      return {
        mode: "higher-count",
        prompt: "Who has done this Tech role more times?",
        title: roleName,
        options: options.map(function (p) {
          return {
            id: "pid:" + String(p.pid),
            label: p.name || "Unknown",
            isCorrect: p.pid === winner.pid
          };
        }),
        revealText: winner.name + " has done " + roleName + " " + winner.count + " times."
      };
    }
    return null;
  }

  function buildPeopleTechStats() {
    const byPerson = {};
    eligibleRoles.forEach(function (roleName) {
      (byRole[roleName] || []).forEach(function (p) {
        if (!p || !p.pid) return;
        if (!byPerson[p.pid]) {
          byPerson[p.pid] = {
            pid: p.pid,
            name: p.name || "Unknown",
            roleCounts: {}
          };
        }
        byPerson[p.pid].roleCounts[roleName] = p.count || 0;
      });
    });
    return byPerson;
  }

  const peopleTechStats = buildPeopleTechStats();

  function buildTopRoleQuestion() {
    const people = Object.keys(peopleTechStats).map(function (pid) {
      return peopleTechStats[pid];
    });
    if (!people.length) return null;

    for (let tries = 0; tries < 300; tries++) {
      const person = people[randomInt(people.length)];
      const roleEntries = Object.keys(person.roleCounts).map(function (roleName) {
        return { roleName: roleName, count: person.roleCounts[roleName] || 0 };
      });
      if (roleEntries.length < 3) continue;
      roleEntries.sort(function (a, b) {
        if (b.count !== a.count) return b.count - a.count;
        return a.roleName.localeCompare(b.roleName);
      });
      if (roleEntries[0].count === roleEntries[1].count) continue;

      const correct = roleEntries[0];
      const distractorPool = roleEntries.slice(1).map(function (r) { return r.roleName; });
      let distractors = sampleN(distractorPool, 2);
      if (distractors.length < 2) {
        const outsidePool = eligibleRoles.filter(function (r) {
          return r !== correct.roleName && distractors.indexOf(r) === -1;
        });
        distractors = distractors.concat(sampleN(outsidePool, 2 - distractors.length));
      }
      if (distractors.length < 2) continue;

      const options = sampleN([
        {
          id: "role:" + correct.roleName,
          label: correct.roleName,
          isCorrect: true
        },
        {
          id: "role:" + distractors[0],
          label: distractors[0],
          isCorrect: false
        },
        {
          id: "role:" + distractors[1],
          label: distractors[1],
          isCorrect: false
        }
      ], 3);

      return {
        mode: "top-role",
        prompt: "What is this person's most-done Tech role?",
        title: person.name,
        options: options,
        revealText: person.name + "'s top Tech role is " + correct.roleName + " (" + correct.count + ")."
      };
    }
    return null;
  }

  function buildQuestion() {
    if (currentMode === "higher-count") return buildHigherCountQuestion();
    if (currentMode === "top-role") return buildTopRoleQuestion();
    return buildMostRoleQuestion();
  }

  function lockOptions() {
    optionsEl.querySelectorAll("button").forEach(function (btn) {
      btn.disabled = true;
    });
  }

  function handleGuess(optionId, buttonEl) {
    if (!question) return;

    attempts += 1;
    const correctOption = question.options.find(function (opt) { return !!opt.isCorrect; });
    const correct = !!correctOption && optionId === correctOption.id;
    if (correct) score += 1;
    updateScore();
    lockOptions();

    optionsEl.querySelectorAll("button").forEach(function (btn) {
      if (correctOption && btn.dataset.optionId === String(correctOption.id)) {
        btn.classList.add("is-correct");
      }
    });
    if (!correct && buttonEl) {
      buttonEl.classList.add("is-wrong");
    }

    if (correct) {
      feedbackEl.textContent = "Correct!";
    } else {
      feedbackEl.textContent = "Not quite. " + question.revealText;
    }

    nextBtn.hidden = false;
  }

  function modePrompt(mode) {
    if (mode === "higher-count") return "Who has done this Tech role more times?";
    if (mode === "top-role") return "What is this person's most-done Tech role?";
    return "Who has done this Tech role most?";
  }

  function renderQuestion() {
    question = buildQuestion();
    if (!question) {
      promptEl.textContent = modePrompt(currentMode);
      roleEl.textContent = "Unable to generate a question";
      optionsEl.innerHTML = "";
      feedbackEl.textContent = "Try refreshing after updating the cache.";
      nextBtn.hidden = true;
      return;
    }

    promptEl.textContent = question.prompt;
    roleEl.textContent = question.title;
    feedbackEl.textContent = "";
    nextBtn.hidden = true;
    optionsEl.innerHTML = "";

    const frag = document.createDocumentFragment();
    question.options.forEach(function (option) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "game-option-btn";
      btn.dataset.optionId = String(option.id);
      btn.innerHTML = escapeHtml(option.label || "Unknown");
      btn.addEventListener("click", function () {
        handleGuess(option.id, btn);
      });
      frag.appendChild(btn);
    });
    optionsEl.appendChild(frag);
  }

  nextBtn.addEventListener("click", function () {
    renderQuestion();
  });

  updateScore();
  if (!eligibleRoles.length) {
    roleEl.textContent = "No eligible roles found";
    feedbackEl.textContent = "Need Tech role data with at least 3 people per role.";
    return;
  }

  modeButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      const mode = btn.getAttribute("data-mode");
      if (!mode || mode === currentMode) return;
      currentMode = mode;
      modeButtons.forEach(function (b) {
        const active = b === btn;
        b.classList.toggle("active", active);
        b.setAttribute("aria-selected", active ? "true" : "false");
      });
      resetScore();
      renderQuestion();
    });
  });

  renderQuestion();
})();
