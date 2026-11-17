(function () {
  "use strict";
  var D = window.ViewerDom;
  var el = D.el, clear = D.clear, icon = D.icon, ring = D.ring;
  var DATA = JSON.parse(document.getElementById("viewer-data").textContent);
  var QUESTIONS = DATA.questions || [];
  var SUMMARY = DATA.summary || {};
  var ACCURACY = DATA.is_scored && SUMMARY.accuracy_by_confidence ? SUMMARY.accuracy_by_confidence : null;
  var WIDE_RAIL_QUERY = "(max-width: 1279px)";
  var TOAST_MS = 2200;
  var TOAST_ERROR_MS = 6000;
  var CLAIM = "Les réponses à confiance élevée sont fiables ; relisez en priorité celles à confiance faible.";

  var STATUS = D.STATUS, CONF = D.CONF, confKey = D.confKey, asList = D.asList;
  var answerText = D.answerText, normalize = D.normalize, initials = D.initials;
  var formatDate = D.formatDate, decimal = D.decimal;
  var tone = D.tone, chip = D.chip, avatar = D.avatar, iconButton = D.iconButton;
  var CITE = {
    verified: { label: "Citation vérifiée", tone: "green" },
    unverified: { label: "Citation absente du document", tone: "pink" },
    not_located: { label: "Vérifiée, non localisée sur la page", tone: "gray" },
    not_rendered: { label: "Image non générée", tone: "gray" },
    unchecked: { label: "Non contrôlée (vérification indisponible)", tone: "gray" }
  };
  var state = { status: "all", confidence: "all", search: "", tab: "answer", selectedId: null };
  var toastTimer = null;

  function $(id) { return document.getElementById(id); }
  function countBy(predicate) { return QUESTIONS.filter(predicate).length; }
  function isLive(question) { return question.is_live === true; }

  /* ---------- Filtering ---------- */
  function matches(question, skip) {
    if (skip !== "status" && state.status !== "all" && question.status !== state.status) return false;
    if (skip !== "confidence" && state.confidence !== "all" && confKey(question) !== state.confidence) return false;
    var term = normalize(state.search.trim());
    if (!term) return true;
    return normalize([question.id, question.question, question.family || "", answerText(question)].join(" ")).indexOf(term) >= 0;
  }
  function countWhere(skip, predicate) {
    return QUESTIONS.filter(function (question) { return matches(question, skip) && predicate(question); }).length;
  }
  function visibleQuestions() {
    var shown = QUESTIONS.filter(function (question) { return matches(question); });
    return shown.filter(isLive).concat(shown.filter(function (question) { return !isLive(question); }));
  }
  function selectedQuestion() {
    return QUESTIONS.filter(function (item) { return item.id === state.selectedId; })[0] || null;
  }
  function applyFilters() {
    var open = state.selectedId;
    if (open && !visibleQuestions().some(function (item) { return item.id === open; })) goList();
    else renderAll();
  }
  function setFilter(key, value) { state[key] = value; applyFilters(); }
  function setSearch(value, fromTopBar) {
    state.search = value;
    if ($("list-filter").value !== value) $("list-filter").value = value;
    if (!DATA.live && $("batch-input").value !== value) $("batch-input").value = value;
    $("batch-clear").hidden = DATA.live || !value;
    if (fromTopBar && state.selectedId) goList();
    else applyFilters();
  }
  function resetFilters() {
    state.status = "all"; state.confidence = "all";
    setSearch("", false);
  }

  /* ---------- Sidebar and header ---------- */
  function navItem(iconNode, label, active, onclick, trailing) {
    return el("button", { class: "nav-item", type: "button", "aria-pressed": String(active), onclick: onclick }, [
      iconNode, el("span", { class: "nav-label", text: label }), trailing
    ]);
  }
  function renderNav() {
    var statusNav = $("status-nav");
    clear(statusNav);
    statusNav.appendChild(navItem(icon("grid"), "Toutes", state.status === "all",
      function () { setFilter("status", "all"); },
      el("span", { class: "count", text: String(countWhere("status", function () { return true; })) })));
    Object.keys(STATUS).forEach(function (key) {
      statusNav.appendChild(navItem(icon(STATUS[key].icon), STATUS[key].plural, state.status === key,
        function () { setFilter("status", key); },
        el("span", { class: "count", text: String(countWhere("status", function (q) { return q.status === key; })) })));
    });
    var confNav = $("conf-nav");
    clear(confNav);
    confNav.appendChild(navItem(el("span", { class: "dot " + tone("gray") }), "Toute confiance", state.confidence === "all",
      function () { setFilter("confidence", "all"); }));
    Object.keys(CONF).forEach(function (key) {
      confNav.appendChild(navItem(el("span", { class: "dot " + tone(CONF[key].tone) }), CONF[key].label, state.confidence === key,
        function () { setFilter("confidence", key); },
        el("span", { text: String(countWhere("confidence", function (q) { return confKey(q) === key; })) })));
    });
    var toggle = $("theme-toggle");
    clear(toggle);
    toggle.appendChild(icon(D.isDark() ? "sun" : "moon"));
    toggle.appendChild(document.createTextNode(D.isDark() ? "Thème clair" : "Thème sombre"));
  }
  function renderHeader() {
    $("run-meta").textContent = DATA.run_id ? "Lot " + DATA.run_id + " · " + formatDate(DATA.generated_at) : "Questions posées en direct";
    var box = $("avatars");
    clear(box);
    Object.keys(STATUS).forEach(function (key) {
      var count = countBy(function (q) { return q.status === key; });
      var node = avatar(String(count), STATUS[key].tone, 52);
      node.className += " ringed";
      node.setAttribute("role", "listitem");
      node.setAttribute("title", STATUS[key].plural);
      node.setAttribute("aria-label", STATUS[key].plural + " : " + count);
      box.appendChild(node);
    });
    var total = avatar(String(QUESTIONS.length), "gray", 52);
    total.setAttribute("role", "listitem");
    total.setAttribute("aria-label", "Questions : " + QUESTIONS.length);
    total.setAttribute("title", "Questions");
    box.appendChild(total);
    var accuracy = $("run-accuracy");
    clear(accuracy);
    Object.keys(CONF).forEach(function (key) {
      var row = ACCURACY ? ACCURACY[key] : null;
      if (!row || !row.n) return;
      accuracy.appendChild(chip(CONF[key].label + " : " + row.correct + "/" + row.n + " (" + Math.round(row.accuracy * 100) + " %)", CONF[key].tone));
    });
  }

  /* ---------- Detail ---------- */
  function notice(toneName, iconName, title, body) {
    var content = [el("div", { class: "notice-title", text: title })];
    if (body) content.push(el("div", { class: "notice-body" }, [body]));
    return el("div", { class: "notice " + tone(toneName) }, [icon(iconName), el("div", { class: "grow" }, content)]);
  }
  function bulletList(lines) {
    return el("ul", {}, lines.map(function (line) { return el("li", { text: String(line) }); }));
  }
  function missingValuesBody(question) {
    var missing = question.missing_values || [];
    if (!missing.length) return bulletList(question.ungrounded_values);
    var items = missing.map(function (value) {
      return el("li", {}, [
        el("strong", { class: "mono", text: String(value) }),
        document.createTextNode(" — introuvable dans les sources")
      ]);
    });
    return el("div", {}, [
      el("ul", {}, items),
      el("div", { class: "muted missing-context", text: "Réponse : " + asList(question.answer).join(" ; ") })
    ]);
  }
  function answerBox(question) {
    var box = el("div", { class: "answer-box" }, [el("div", { class: "answer-label", text: "Réponse" })]);
    var items = asList(question.answer);
    if (question.status === "not_found" || !items.length) {
      box.appendChild(el("div", { class: "answer-big none", text: question.status === "not_found" ? "Aucune réponse" : "—" }));
    } else if (Array.isArray(question.answer) && items.length > 1) {
      box.appendChild(el("div", { class: "answer-chips" }, items.map(function (item) {
        return chip(String(item), question.status === "conflict" ? "pink" : "gray", "lg");
      })));
    } else {
      box.appendChild(el("div", { class: "answer-big", text: String(items[0]) }));
    }
    return box;
  }
  var NOTE_TITLES = { aggregation: "Calcul vérifié", superseded: "Version en vigueur retenue" };
  function noteNotice(question) {
    var title = NOTE_TITLES[question.family] || "Note du moteur";
    if (question.family === "aggregation") return notice("green", "check", title, document.createTextNode(question.note));
    var body = el("div", { class: "note-internal" }, [
      el("span", { class: "note-hint", text: "(note interne) " }),
      document.createTextNode(question.note)
    ]);
    return notice("gray", "doc", title, body);
  }
  function noticesFor(question) {
    var list = [];
    var reasons = question.confidence_reasons || [];
    if (question.status === "conflict") {
      list.push(notice("pink", "warning", "Les sources se contredisent", document.createTextNode("Conflit détecté entre les documents cités.")));
    }
    if (question.status === "not_found") {
      list.push(notice("gray", "search-off", "Aucune réponse trouvée", document.createTextNode("La réponse n'apparaît dans aucune des sources consultées. Voir l'onglet Documents consultés.")));
    }
    if (question.error) list.push(notice("pink", "error", "Erreur", document.createTextNode(question.error)));
    list.push(reasons.length
      ? notice(CONF[confKey(question)].tone, "error", "Pourquoi cette confiance ?", bulletList(reasons))
      : notice("green", "verified", "Pourquoi cette confiance ?", document.createTextNode("Aucun signal d'alerte.")));
    if (DATA.is_scored && question.is_correct === false) {
      list.push(notice("pink", "error", "Réponse attendue : " + (asList(question.expected_answer).map(String).join(" ou ") || "—")));
    }
    if ((question.ungrounded_values || []).length) {
      list.push(notice("yellow", "error", "Valeurs non retrouvées dans les sources", missingValuesBody(question)));
    }
    if ((question.dropped_citations || []).length) {
      list.push(notice("gray", "doc", "Citations écartées (non retrouvées dans le document)", bulletList(question.dropped_citations)));
    }
    if (question.note) list.push(noteNotice(question));
    return el("div", { class: "notices" }, list);
  }
  function documentsList(question) {
    var rows = question.retrieved || [];
    if (!rows.length) return el("p", { class: "empty-line", text: "Aucun document consulté." });
    return el("div", { class: "doc-rows" }, rows.map(function (doc) {
      var score = typeof doc.score === "number" ? doc.score : null;
      var scoreTone = score === null ? "gray" : score >= 0.9 ? "green" : score >= 0.8 ? "yellow" : "gray";
      return el("div", { class: "doc-row" }, [
        avatar(initials(doc.doc_type || "?"), scoreTone, 48),
        el("div", { class: "grow" }, [
          el("div", { class: "doc-id", text: doc.doc_id }),
          el("div", { class: "doc-meta", text: (doc.doc_type || "–") + " · " + (doc.doc_date || "–") })
        ]),
        chip("Score " + (score === null ? "–" : decimal(score, 2)), scoreTone)
      ]);
    }));
  }
  function footerLine(question) {
    var count = (question.evidence || []).length;
    var left = (typeof question.elapsed_s === "number" ? decimal(question.elapsed_s, 1) + " s · " : "") +
      "Confiance " + CONF[confKey(question)].label.toLowerCase();
    var right = [el("span", { class: "row" }, [icon("chat", "sm"), el("span", { text: count + " citation" + (count > 1 ? "s" : "") })])];
    if (DATA.is_scored && typeof question.is_correct === "boolean") {
      right.push(el("span", { class: "row " + (question.is_correct ? "ok-text" : "bad-text") }, [
        icon(question.is_correct ? "check" : "error", "sm"),
        el("span", { text: question.is_correct ? "Réponse correcte" : "Réponse incorrecte" })
      ]));
    }
    return el("div", { class: "footer-line" }, [el("div", { text: left }), el("div", { class: "row wrap", style: "gap:20px" }, right)]);
  }
  function renderDetail(question) {
    var box = $("detail");
    clear(box);
    box.appendChild(el("div", { class: "row between" }, [
      el("div", { class: "row" }, [
        avatar(question.id.toUpperCase(), CONF[confKey(question)].tone, 30),
        question.family ? el("span", { class: "ellipsis", style: "font-size:15px", text: question.family }) : null
      ]),
      chip(STATUS[question.status] ? STATUS[question.status].label : String(question.status),
        STATUS[question.status] ? STATUS[question.status].tone : "gray")
    ]));
    box.appendChild(el("h2", { class: "question-title", text: question.question }));
    if (state.tab === "answer") {
      box.appendChild(answerBox(question));
      var timeline = D.stepsTimeline(question.steps, question.elapsed_s);
      if (timeline) box.appendChild(timeline);
      box.appendChild(noticesFor(question));
    } else {
      box.appendChild(documentsList(question));
    }
    box.appendChild(footerLine(question));
  }

  /* ---------- Evidence ---------- */
  function openLightbox(item, alt) {
    var box = $("lightbox");
    clear(box);
    var meta = [el("div", { class: "doc-id", text: item.doc_id })];
    if (item.page !== null && item.page !== undefined) meta.push(el("div", { class: "doc-meta", text: "Page " + item.page }));
    box.appendChild(el("div", { class: "lb-head" }, [
      avatar(initials(item.doc_id), CITE[item.state] ? CITE[item.state].tone : "gray", 36),
      el("div", { class: "grow" }, meta),
      iconButton("close", "Fermer (Échap)", function () { box.close(); })
    ]));
    box.appendChild(el("div", { class: "lb-body" }, [el("img", { src: item.full_image || item.crop_image, alt: alt })]));
    box.showModal();
  }
  function evidenceCard(item, isConflict) {
    var cite = CITE[item.state] || { label: "État inconnu", tone: "gray" };
    var hasPage = item.page !== null && item.page !== undefined;
    var shown = item.crop_image || item.full_image;
    var alt = "Extrait de " + item.doc_id + (hasPage ? ", page " + item.page : "");
    var open = function () { openLightbox(item, alt); };
    var card = el("article", { class: "panel card" });
    if (shown) {
      card.appendChild(el("button", { class: "thumb", type: "button", "aria-label": "Agrandir : " + alt, onclick: open }, [
        el("img", { src: shown, alt: alt, loading: "lazy" })
      ]));
    }
    card.appendChild(el("div", { class: "row between wrap" }, [
      el("div", { class: "row" }, [avatar(initials(item.doc_id), cite.tone, 30), el("span", { class: "mono ellipsis", style: "font-size:14px", text: item.doc_id })]),
      chip(cite.label, cite.tone, "wrap")
    ]));
    if (item.value) card.appendChild(el("div", { class: "card-value" + (isConflict ? " conflict" : ""), text: item.value }));
    card.appendChild(el("blockquote", { class: "quote" + (item.state === "unverified" ? " struck" : ""), text: "« " + (item.quote || "") + " »" }));
    var foot = [el("span", { text: hasPage ? "Page " + item.page : "" })];
    if (shown) {
      foot.push(el("button", { class: "link-btn", type: "button", onclick: open }, [icon("fullscreen", "md"), "Agrandir la source"]));
    }
    card.appendChild(el("div", { class: "row between card-foot" }, foot));
    return card;
  }
  function renderEvidence(question) {
    var box = $("evidence");
    clear(box);
    var items = question.evidence || [];
    if (state.tab !== "answer" || !items.length) return;
    var isConflict = question.status === "conflict";
    var grid = el("div", { class: "evidence" + (isConflict || items.length > 1 ? " multi" : "") });
    items.forEach(function (item) { grid.appendChild(evidenceCard(item, isConflict)); });
    box.appendChild(grid);
  }

  /* ---------- Right rail ---------- */
  function toast(text, isError) {
    var node = $("toast");
    node.textContent = text;
    node.className = "toast" + (isError ? " error" : "");
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { node.hidden = true; }, isError ? TOAST_ERROR_MS : TOAST_MS);
  }
  function copyLink() {
    try {
      navigator.clipboard.writeText(location.href).then(function () { toast("Lien de la question copié"); }, function () {});
    } catch (error) { /* clipboard unavailable: the URL bar still holds the link */ }
  }
  function renderScore() {
    var box = $("score-panel");
    clear(box);
    var totals = { n: 0, correct: 0 };
    if (ACCURACY) {
      Object.keys(ACCURACY).forEach(function (key) {
        totals.n += ACCURACY[key].n; totals.correct += ACCURACY[key].correct;
      });
    }
    var overall = totals.n ? totals.correct / totals.n : 0;
    box.appendChild(ring(ACCURACY ? overall : 0, ACCURACY ? Math.round(overall * 100) + " %" : String(QUESTIONS.length)));
    box.appendChild(el("h2", { text: ACCURACY ? "Exactitude du lot" : "Questions du lot" }));
    box.appendChild(chip(ACCURACY ? totals.correct + " sur " + totals.n + " correctes" : "Exactitude non calculée", ACCURACY ? "green" : "gray"));
    box.appendChild(el("div", { class: "row" }, [
      iconButton("link", "Copier le lien de la question", copyLink),
      iconButton("filter-off", "Réinitialiser les filtres", resetFilters),
      iconButton(D.isDark() ? "sun" : "moon", D.isDark() ? "Thème clair" : "Thème sombre", switchTheme)
    ]));
  }
  function sectionHead(title, onAll) {
    return el("div", { class: "section-head" }, [el("span", { text: title }), el("button", { class: "pill", type: "button", onclick: onAll, text: "Tout voir" })]);
  }
  function renderConfidencePanel() {
    var box = $("conf-panel");
    clear(box);
    box.appendChild(sectionHead(ACCURACY ? "Exactitude par confiance" : "Questions par confiance", function () { setFilter("confidence", "all"); }));
    var list = el("div", { class: "list" });
    Object.keys(CONF).forEach(function (key) {
      var total = countBy(function (q) { return confKey(q) === key; });
      var row = ACCURACY ? ACCURACY[key] : null;
      var sub = row ? row.correct + " sur " + row.n + " correctes" : total + " question" + (total > 1 ? "s" : "");
      var right = row ? Math.round(row.accuracy * 100) + " %" : ACCURACY ? "–" : String(total);
      list.appendChild(el("button", { class: "list-item", type: "button", "aria-pressed": String(state.confidence === key),
        onclick: function () { setFilter("confidence", key); } }, [
        avatar(CONF[key].short, CONF[key].tone, 48),
        el("div", { class: "grow" }, [el("div", { class: "conf-name", text: "Confiance " + CONF[key].label.toLowerCase() }), el("div", { class: "conf-sub", text: sub })]),
        el("span", { class: "conf-name", text: right })
      ]));
    });
    box.appendChild(list);
    if (ACCURACY) box.appendChild(el("p", { class: "claim", text: CLAIM }));
  }
  var renderList = window.ViewerList({
    data: DATA, questions: QUESTIONS, state: state, isLive: isLive,
    resetFilters: resetFilters, select: select
  });

  /* ---------- Orchestration ---------- */
  function renderTabs(question) {
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (tab) {
      var isDocs = tab.getAttribute("data-tab") === "documents";
      tab.setAttribute("aria-pressed", String(state.tab === tab.getAttribute("data-tab")));
      tab.textContent = isDocs ? "Documents consultés (" + (question.retrieved || []).length + ")" : "Réponse";
    });
  }
  function renderAll() {
    var question = selectedQuestion();
    renderNav();
    renderHeader();
    renderScore();
    renderConfidencePanel();
    $("list-view").hidden = question !== null;
    $("detail-view").hidden = question === null;
    if (!question) { renderList(visibleQuestions()); return; }
    renderDetail(question);
    renderEvidence(question);
    renderTabs(question);
  }
  function setHash(id) {
    var target = id ? "#" + encodeURIComponent(id) : "";
    if (location.hash !== target) location.hash = target;
  }
  function select(id) {
    state.selectedId = id;
    setHash(id);
    renderAll();
    window.scrollTo(0, 0);
  }
  function goList() {
    state.selectedId = null;
    setHash("");
    renderAll();
  }
  function move(step) {
    var visible = visibleQuestions();
    if (!visible.length || !state.selectedId) return;
    var index = visible.findIndex(function (item) { return item.id === state.selectedId; });
    var next = index < 0 ? 0 : (index + step + visible.length) % visible.length;
    select(visible[next].id);
  }
  function switchTheme() {
    D.toggleTheme();
    renderNav();
    renderScore();
  }
  function hashId() {
    try { return decodeURIComponent(location.hash.slice(1)); }
    catch (error) { return ""; }
  }
  function knownId(id) { return QUESTIONS.some(function (item) { return item.id === id; }); }
  function onHashChange() {
    var id = hashId();
    var next = knownId(id) ? id : null;
    if (next === state.selectedId) return;
    state.selectedId = next;
    renderAll();
  }
  function addQuestion(question) {
    var index = QUESTIONS.findIndex(function (item) { return item.id === question.id; });
    if (index >= 0) QUESTIONS[index] = question;
    else QUESTIONS.push(question);
    state.status = "all"; state.confidence = "all";
    setSearch("", false);
  }

  /* ---------- Wiring ---------- */
  function wire() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-icon]"), function (node) {
      node.appendChild(icon(node.getAttribute("data-icon")));
    });
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (tab) {
      tab.addEventListener("click", function () { state.tab = tab.getAttribute("data-tab"); renderAll(); });
    });
    $("prev").addEventListener("click", function () { move(-1); });
    $("next").addEventListener("click", function () { move(1); });
    $("back").addEventListener("click", goList);
    $("theme-toggle").addEventListener("click", switchTheme);
    $("list-filter").addEventListener("input", function (event) { setSearch(event.target.value, false); });
    if (!DATA.live) {
      $("batch-input").addEventListener("input", function (event) { setSearch(event.target.value, true); });
      $("batch-form").addEventListener("submit", function (event) { event.preventDefault(); if (state.selectedId) goList(); });
      $("batch-clear").addEventListener("click", function () { setSearch("", true); $("batch-input").focus(); });
    }
    $("lightbox").addEventListener("click", function (event) { if (event.target === this) this.close(); });
    document.addEventListener("keydown", function (event) {
      if (event.altKey || event.ctrlKey || event.metaKey || $("lightbox").open || !state.selectedId) return;
      if (event.target.matches && event.target.matches('input, textarea, select, [contenteditable="true"]')) return;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        move(event.key === "ArrowUp" ? -1 : 1);
      }
    });
    window.addEventListener("hashchange", onHashChange);
  }

  if (!QUESTIONS.length && !DATA.live) {
    $("app").replaceWith(el("div", { class: "empty" }, [
      el("h2", { text: "Aucune question à afficher" }),
      el("p", { text: "Cette exécution ne contient aucune réponse à vérifier." })
    ]));
    return;
  }
  window.ViewerApp = { live: DATA.live === true, addQuestion: addQuestion, openQuestion: select, toast: toast };
  wire();
  var initial = hashId();
  state.selectedId = knownId(initial) ? initial : null;
  renderAll();
})();
