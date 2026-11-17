(function () {
  "use strict";
  var D = window.ViewerDom;
  var el = D.el, icon = D.icon, clear = D.clear, chip = D.chip, avatar = D.avatar;
  var STATUS = D.STATUS, CONF = D.CONF, confKey = D.confKey;
  var LIVE_GROUP = "Questions posées";
  var BATCH_GROUP = "Questions du lot";

  window.ViewerList = function (ctx) {
    var DATA = ctx.data, QUESTIONS = ctx.questions, state = ctx.state;
    var isLive = ctx.isLive, resetFilters = ctx.resetFilters, select = ctx.select;
    function $(id) { return document.getElementById(id); }
    function isFiltered() { return state.status !== "all" || state.confidence !== "all" || state.search.trim() !== ""; }
    function verdictNode(question) {
      if (!DATA.is_scored || typeof question.is_correct !== "boolean") return null;
      return el("span", { class: "row " + (question.is_correct ? "ok-text" : "bad-text"), title: question.is_correct ? "Réponse correcte" : "Réponse incorrecte" }, [
        icon(question.is_correct ? "check" : "error", "sm"),
        el("span", { text: question.is_correct ? "Correcte" : "Incorrecte" })
      ]);
    }
    function caseRow(question) {
      var status = STATUS[question.status] || { label: String(question.status), tone: "gray" };
      var conf = CONF[confKey(question)];
      return el("button", { class: "case-row", type: "button", "data-id": question.id, onclick: function () { select(question.id); } }, [
        avatar(question.id.toUpperCase(), conf.tone, 48),
        el("div", { class: "grow" }, [
          el("div", { class: "case-question clamp", text: question.question }),
          el("div", { class: "case-meta" }, [
            chip(status.label, status.tone),
            chip("Confiance " + conf.label.toLowerCase(), conf.tone),
            verdictNode(question),
            question.family ? el("span", { class: "muted", text: question.family }) : null
          ])
        ])
      ]);
    }
    function caseGroup(title, rows) {
      return el("div", { class: "case-group" }, [
        title ? el("h2", { class: "group-title", text: title + " · " + rows.length }) : null,
        el("div", { class: "list" }, rows.map(caseRow))
      ]);
    }
    function emptyList() {
      if (!QUESTIONS.length) {
        return el("div", { class: "empty-state" }, [
          icon("chat"), el("h2", { text: "Aucune question pour l'instant" }),
          el("p", { text: "Posez une question aux archives depuis la barre du haut." })
        ]);
      }
      return el("div", { class: "empty-state" }, [
        icon("search-off"), el("h2", { text: "Aucun cas ne correspond" }),
        el("p", { text: "Aucune question ne correspond aux filtres actifs." }),
        el("button", { class: "outline-btn", type: "button", onclick: resetFilters, text: "Réinitialiser les filtres" })
      ]);
    }
    function renderList(visible) {
      var box = $("case-list");
      clear(box);
      box.appendChild(el("div", { class: "section-head" }, [
        el("span", { text: "Cas · " + visible.length + " sur " + QUESTIONS.length }),
        isFiltered() ? el("button", { class: "pill", type: "button", onclick: resetFilters, text: "Réinitialiser" }) : null
      ]));
      if (!visible.length) { box.appendChild(emptyList()); return; }
      var live = visible.filter(isLive);
      var rest = visible.filter(function (question) { return !isLive(question); });
      if (live.length) box.appendChild(caseGroup(LIVE_GROUP, live));
      if (rest.length) box.appendChild(caseGroup(live.length ? BATCH_GROUP : null, rest));
    }
    return renderList;
  };
})();
