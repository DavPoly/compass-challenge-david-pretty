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
  var HIT_LIMIT = 5;
  var CLAIM = "Les réponses à confiance élevée sont fiables ; relisez en priorité celles à confiance faible.";

  var STATUS = {
    answered: { label: "Répondue", plural: "Répondues", tone: "green", icon: "task-alt" },
    not_found: { label: "Introuvable", plural: "Introuvables", tone: "gray", icon: "search-off" },
    conflict: { label: "Conflit", plural: "Conflits", tone: "pink", icon: "compare" }
  };
  var CONF = {
    high: { label: "Élevée", short: "ÉL", tone: "green" },
    medium: { label: "Moyenne", short: "MO", tone: "yellow" },
    low: { label: "Faible", short: "FA", tone: "pink" },
    unknown: { label: "Inconnue", short: "?", tone: "gray" }
  };
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
  function confKey(question) { return question.confidence || "unknown"; }
  function asList(value) {
    if (value === null || value === undefined) return [];
    return Array.isArray(value) ? value : [value];
  }
  function answerText(question) { return asList(question.answer).join(" ou "); }
  function normalize(text) {
    return String(text).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }
  function initials(text) {
    return String(text).split(/[\s_\-.]+/).filter(Boolean).slice(0, 2)
      .map(function (part) { return part[0]; }).join("").toUpperCase();
  }
  function formatDate(iso) {
    var date = new Date(iso);
    if (!iso || isNaN(date.getTime())) return iso || "";
    return date.toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" });
  }
  function decimal(number, digits) { return number.toFixed(digits).replace(".", ","); }
  function tone(name) { return "t-" + name; }
  function chip(text, toneName, extra) {
    return el("span", { class: "chip " + tone(toneName) + (extra ? " " + extra : ""), text: text });
  }
  function avatar(text, toneName, size) {
    var props = { class: "avatar " + tone(toneName), style: "--s:" + size + "px" };
    if (text.length > 3) props.style += ";font-size:" + Math.round(size * 0.24) + "px";
    return el("span", props, [text]);
  }
  function iconButton(name, label, onclick, extraClass) {
    return el("button", { class: "round " + (extraClass || ""), type: "button", "aria-label": label, title: label, onclick: onclick }, [icon(name)]);
  }
  function countBy(predicate) { return QUESTIONS.filter(predicate).length; }

  /* ---------- Filtering ---------- */
  function visibleQuestions() {
    var term = normalize(state.search.trim());
    return QUESTIONS.filter(function (question) {
      if (state.status !== "all" && question.status !== state.status) return false;
      if (state.confidence !== "all" && confKey(question) !== state.confidence) return false;
      if (!term) return true;
      return normalize([question.id, question.question, question.family || "", answerText(question)].join(" ")).indexOf(term) >= 0;
    });
  }
  function resetFilters() {
    state.status = "all"; state.confidence = "all"; state.search = "";
    $("list-filter").value = "";
    renderAll();
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
      function () { state.status = "all"; renderAll(); }, el("span", { class: "count", text: String(QUESTIONS.length) })));
    Object.keys(STATUS).forEach(function (key) {
      statusNav.appendChild(navItem(icon(STATUS[key].icon), STATUS[key].plural, state.status === key,
        function () { state.status = key; renderAll(); },
        el("span", { class: "count", text: String(countBy(function (q) { return q.status === key; })) })));
    });
    var confNav = $("conf-nav");
    clear(confNav);
    confNav.appendChild(navItem(el("span", { class: "dot " + tone("gray") }), "Toute confiance", state.confidence === "all",
      function () { state.confidence = "all"; renderAll(); }));
    Object.keys(CONF).forEach(function (key) {
      confNav.appendChild(navItem(el("span", { class: "dot " + tone(CONF[key].tone) }), CONF[key].label, state.confidence === key,
        function () { state.confidence = key; renderAll(); },
        el("span", { text: String(countBy(function (q) { return confKey(q) === key; })) })));
    });
    var toggle = $("theme-toggle");
    clear(toggle);
    toggle.appendChild(icon(D.isDark() ? "sun" : "moon"));
    toggle.appendChild(document.createTextNode(D.isDark() ? "Thème clair" : "Thème sombre"));
  }
  function renderHeader() {
    $("run-meta").textContent = "Lot " + (DATA.run_id || "?") + " · " + formatDate(DATA.generated_at);
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
      list.push(notice("yellow", "error", "Valeurs non retrouvées dans les sources", bulletList(question.ungrounded_values)));
    }
    if ((question.dropped_citations || []).length) {
      list.push(notice("gray", "doc", "Citations écartées (non retrouvées dans le document)", bulletList(question.dropped_citations)));
    }
    if (question.note) list.push(notice("green", "check", "Calcul vérifié", document.createTextNode(question.note)));
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
  function copyLink() {
    var shown = function () {
      var toast = $("toast");
      toast.hidden = false;
      clearTimeout(toastTimer);
      toastTimer = setTimeout(function () { toast.hidden = true; }, TOAST_MS);
    };
    try {
      navigator.clipboard.writeText(location.href).then(shown, function () {});
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
    box.appendChild(sectionHead(ACCURACY ? "Exactitude par confiance" : "Questions par confiance", function () { state.confidence = "all"; renderAll(); }));
    var list = el("div", { class: "list" });
    Object.keys(CONF).forEach(function (key) {
      var total = countBy(function (q) { return confKey(q) === key; });
      var row = ACCURACY ? ACCURACY[key] : null;
      var sub = row ? row.correct + " sur " + row.n + " correctes" : total + " question" + (total > 1 ? "s" : "");
      var right = row ? Math.round(row.accuracy * 100) + " %" : ACCURACY ? "–" : String(total);
      list.appendChild(el("button", { class: "list-item", type: "button", "aria-pressed": String(state.confidence === key),
        onclick: function () { state.confidence = key; renderAll(); } }, [
        avatar(CONF[key].short, CONF[key].tone, 48),
        el("div", { class: "grow" }, [el("div", { class: "conf-name", text: "Confiance " + CONF[key].label.toLowerCase() }), el("div", { class: "conf-sub", text: sub })]),
        el("span", { class: "conf-name", text: right })
      ]));
    });
    box.appendChild(list);
    if (ACCURACY) box.appendChild(el("p", { class: "claim", text: CLAIM }));
  }
  function renderQuestionList(visible) {
    var box = $("list-panel");
    clear(box);
    box.appendChild(sectionHead("Questions · " + visible.length + " sur " + QUESTIONS.length, resetFilters));
    var list = el("div", { class: "list q-list" });
    visible.forEach(function (question) {
      var status = STATUS[question.status] || { label: String(question.status), tone: "gray" };
      var verdict = DATA.is_scored && typeof question.is_correct === "boolean"
        ? { text: question.is_correct ? "Correcte" : "Incorrecte", cls: question.is_correct ? "ok-text" : "bad-text" }
        : { text: "Confiance " + CONF[confKey(question)].label.toLowerCase(), cls: "muted" };
      list.appendChild(el("button", { class: "list-item", type: "button", "data-id": question.id,
        "aria-current": String(question.id === state.selectedId), onclick: function () { select(question.id, true); } }, [
        avatar(question.id.toUpperCase(), CONF[confKey(question)].tone, 48),
        el("div", { class: "grow" }, [
          el("div", { class: "list-title clamp", text: question.question }),
          el("div", { class: "list-sub" }, [
            el("span", { class: tone(status.tone), style: "color:var(--tf)", text: status.label }),
            el("span", { class: verdict.cls, text: verdict.text })
          ])
        ])
      ]));
    });
    if (!visible.length) list.appendChild(el("p", { class: "empty-line", text: "Aucune question ne correspond aux filtres." }));
    box.appendChild(list);
  }

  /* ---------- Orchestration ---------- */
  function renderAll() {
    var question = QUESTIONS.filter(function (item) { return item.id === state.selectedId; })[0] || QUESTIONS[0];
    renderNav();
    renderHeader();
    renderScore();
    renderConfidencePanel();
    renderQuestionList(visibleQuestions());
    renderDetail(question);
    renderEvidence(question);
    $("prev").disabled = $("next").disabled = !visibleQuestions().length;
    var tabs = document.querySelectorAll(".tab");
    Array.prototype.forEach.call(tabs, function (tab) {
      var isDocs = tab.getAttribute("data-tab") === "documents";
      tab.setAttribute("aria-pressed", String(state.tab === tab.getAttribute("data-tab")));
      tab.textContent = isDocs ? "Documents consultés (" + (question.retrieved || []).length + ")" : "Réponse";
    });
  }
  function select(id, scrollToDetail, fromHash) {
    state.selectedId = id;
    if (!fromHash && location.hash !== "#" + encodeURIComponent(id)) history.replaceState(null, "", "#" + encodeURIComponent(id));
    renderAll();
    if (scrollToDetail && window.matchMedia(WIDE_RAIL_QUERY).matches) $("main").scrollIntoView({ block: "start" });
  }
  function move(step) {
    var visible = visibleQuestions();
    if (!visible.length) return;
    var index = visible.findIndex(function (item) { return item.id === state.selectedId; });
    var next = index < 0 ? 0 : (index + step + visible.length) % visible.length;
    select(visible[next].id, false);
    var current = document.querySelector('.q-list [aria-current="true"]');
    if (current) current.scrollIntoView({ block: "nearest" });
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

  /* ---------- Batch search ---------- */
  function searchBatch(query) {
    var tokens = normalize(query).split(/[^a-z0-9]+/).filter(function (token) { return token.length > 1; });
    if (!tokens.length) return [];
    var needed = Math.max(1, Math.ceil(tokens.length / 2));
    return QUESTIONS.map(function (question) {
      var haystack = normalize([question.id, question.question, question.family || "", answerText(question)].join(" "));
      var score = tokens.filter(function (token) { return haystack.indexOf(token) >= 0; }).length;
      return { question: question, score: score };
    }).filter(function (hit) { return hit.score >= needed; })
      .sort(function (a, b) { return b.score - a.score; }).slice(0, HIT_LIMIT);
  }
  function hitCard(question) {
    var summary = question.status === "not_found" ? "Aucune réponse trouvée dans les documents consultés."
      : question.status === "conflict" ? "Les sources se contredisent : " + answerText(question)
      : answerText(question) || "—";
    return el("div", { class: "hit" }, [
      el("div", { class: "hit-answer", text: summary }),
      el("div", { class: "hit-question clamp", text: question.id + " · " + question.question }),
      el("div", { class: "row wrap" }, [
        chip("Confiance " + CONF[confKey(question)].label.toLowerCase(), CONF[confKey(question)].tone),
        el("button", { class: "outline-btn", type: "button", onclick: function () {
          state.status = "all"; state.confidence = "all"; state.search = ""; state.tab = "answer";
          $("list-filter").value = "";
          select(question.id, true);
        } }, ["Ouvrir la question " + question.id.toUpperCase(), icon("arrow-forward", "sm")])
      ])
    ]);
  }
  function renderBatchResults() {
    var query = $("batch-input").value.trim();
    var box = $("batch-results");
    clear(box);
    $("batch-clear").hidden = !query;
    box.hidden = !query;
    if (!query) return;
    var hits = searchBatch(query);
    if (!hits.length) {
      box.appendChild(el("p", { class: "thread-title", text: "Aucun passage pertinent dans ce lot. Essayez un nom de projet, de firme ou de document." }));
      return;
    }
    box.appendChild(el("p", { class: "thread-title", text: hits.length + " question" + (hits.length > 1 ? "s" : "") + " correspondante" + (hits.length > 1 ? "s" : "") }));
    hits.forEach(function (hit) { box.appendChild(hitCard(hit.question)); });
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
    $("theme-toggle").addEventListener("click", switchTheme);
    $("list-filter").addEventListener("input", function (event) { state.search = event.target.value; renderAll(); });
    $("batch-input").addEventListener("input", renderBatchResults);
    $("batch-form").addEventListener("submit", function (event) { event.preventDefault(); renderBatchResults(); });
    $("batch-clear").addEventListener("click", function () { $("batch-input").value = ""; renderBatchResults(); $("batch-input").focus(); });
    $("lightbox").addEventListener("click", function (event) { if (event.target === this) this.close(); });
    document.addEventListener("keydown", function (event) {
      if (event.altKey || event.ctrlKey || event.metaKey || $("lightbox").open) return;
      if (event.target.matches && event.target.matches('input, textarea, select, [contenteditable="true"]')) return;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        move(event.key === "ArrowUp" ? -1 : 1);
      }
    });
    window.addEventListener("hashchange", function () {
      var id = hashId();
      if (knownId(id)) select(id, false, true);
    });
  }

  if (!QUESTIONS.length) {
    $("app").replaceWith(el("div", { class: "empty" }, [
      el("h2", { text: "Aucune question à afficher" }),
      el("p", { text: "Cette exécution ne contient aucune réponse à vérifier." })
    ]));
    return;
  }
  wire();
  var initial = hashId();
  var known = knownId(initial);
  select(known ? initial : QUESTIONS[0].id, false, known);
})();
