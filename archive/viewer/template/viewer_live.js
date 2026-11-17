(function () {
  "use strict";
  var App = window.ViewerApp;
  if (!App || !App.live) return;
  var D = window.ViewerDom;
  var el = D.el, clear = D.clear, icon = D.icon, decimal = D.decimal;
  var ASK_URL = "/api/ask";
  var PLACEHOLDER = "Poser une question aux archives…";
  var MSG_INTERRUPTED = "La connexion a été interrompue avant la réponse.";
  var MSG_UNREACHABLE = "Le serveur est injoignable. Vérifiez qu'il est lancé.";
  var MSG_REFUSED = "La question a été refusée par le serveur.";
  var MSG_BAD_EVENT = "Réponse illisible reçue du serveur.";
  var form = document.getElementById("batch-form");
  var input = document.getElementById("batch-input");
  var send = document.getElementById("batch-send");
  var panel = document.getElementById("live-panel");
  var running = false;

  function setBusy(isBusy) {
    running = isBusy;
    input.disabled = isBusy;
    send.disabled = isBusy;
  }

  /* ---------- Progress panel ---------- */
  function stepNode(step, isLatest) {
    var marker = isLatest && running ? el("span", { class: "spinner", role: "presentation" }) : icon("check", "sm");
    return el("li", { class: "step" }, [
      marker,
      el("span", { class: "grow" }, [
        el("span", { text: step.label }),
        step.detail ? el("span", { class: "step-detail", text: " · " + step.detail }) : null
      ]),
      el("span", { class: "step-time", text: decimal(step.elapsed_s || 0, 1) + " s" })
    ]);
  }
  function renderPanel(question, steps, errorMessage) {
    clear(panel);
    panel.hidden = false;
    var close = D.iconButton("close", "Fermer", function () { panel.hidden = true; });
    panel.appendChild(el("div", { class: "progress-head" }, [
      el("div", {}, [
        el("div", { class: "progress-title", text: errorMessage ? "Question en échec" : "Question en cours" }),
        el("div", { class: "progress-question", text: question })
      ]),
      errorMessage ? close : null
    ]));
    panel.appendChild(el("ul", { class: "steps" }, steps.map(function (step, index) {
      return stepNode(step, index === steps.length - 1);
    })));
    if (errorMessage) panel.appendChild(el("p", { class: "progress-error", text: errorMessage }));
  }

  /* ---------- SSE parsing ---------- */
  function parseBlock(block) {
    var name = "message";
    var data = [];
    block.split("\n").forEach(function (line) {
      if (line.indexOf("event:") === 0) name = line.slice(6).trim();
      else if (line.indexOf("data:") === 0) data.push(line.slice(5).replace(/^ /, ""));
    });
    if (!data.length) return null;
    return { name: name, payload: JSON.parse(data.join("\n")) };
  }
  async function readEvents(body, onEvent) {
    var reader = body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";
    for (;;) {
      var chunk = await reader.read();
      if (chunk.done) break;
      buffer = (buffer + decoder.decode(chunk.value, { stream: true })).replace(/\r\n/g, "\n");
      var cut = buffer.indexOf("\n\n");
      while (cut >= 0) {
        var parsed = parseBlock(buffer.slice(0, cut));
        if (parsed) onEvent(parsed.name, parsed.payload);
        buffer = buffer.slice(cut + 2);
        cut = buffer.indexOf("\n\n");
      }
    }
    var rest = parseBlock(buffer.trim());
    if (rest) onEvent(rest.name, rest.payload);
  }

  /* ---------- Ask ---------- */
  async function refusalMessage(response) {
    try {
      var body = await response.json();
      return body && body.error ? String(body.error) : MSG_REFUSED;
    } catch (error) {
      return MSG_REFUSED;
    }
  }
  async function ask(text) {
    var steps = [];
    var outcome = null;
    var failure = null;
    renderPanel(text, steps, null);
    setBusy(true);
    try {
      var response = await fetch(ASK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text })
      });
      if (!response.ok) {
        panel.hidden = true;
        App.toast(await refusalMessage(response), true);
        return;
      }
      await readEvents(response.body, function (name, payload) {
        if (name === "step") {
          steps.push(payload);
          renderPanel(text, steps, null);
        } else if (name === "result") outcome = payload.question;
        else if (name === "error") failure = payload.message || MSG_BAD_EVENT;
      });
      if (!outcome && !failure) failure = MSG_INTERRUPTED;
    } catch (error) {
      failure = error instanceof SyntaxError ? MSG_BAD_EVENT : MSG_UNREACHABLE;
    } finally {
      setBusy(false);
    }
    if (failure) {
      renderPanel(text, steps, failure);
      App.toast(failure, true);
      return;
    }
    panel.hidden = true;
    input.value = "";
    App.addQuestion(outcome);
    App.openQuestion(outcome.id);
  }

  input.placeholder = PLACEHOLDER;
  input.setAttribute("aria-label", PLACEHOLDER);
  send.setAttribute("aria-label", "Envoyer la question");
  form.setAttribute("role", "form");
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var text = input.value.trim();
    if (running || !text) return;
    ask(text);
  });
})();
