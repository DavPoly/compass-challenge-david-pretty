(function () {
  "use strict";
  var SVG_NS = "http://www.w3.org/2000/svg";
  var THEME_KEY = "viewer-theme";
  var RING_RADIUS = 63;

  /* Static Material-style icon paths (24x24 viewBox). */
  var ICONS = {
    search: "M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z",
    "search-off": "M10 3a7 7 0 0 1 5.6 11.2l5.7 5.7-1.4 1.4-5.7-5.7A7 7 0 1 1 10 3zm0 2a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM3 4.4L4.4 3 21 19.6 19.6 21z",
    "arrow-forward": "M12 4l-1.41 1.41L16.17 11H4v2h12.17l-5.58 5.59L12 20l8-8z",
    "arrow-back": "M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z",
    "arrow-up": "M4 12l1.41 1.41L11 7.83V20h2V7.83l5.58 5.59L20 12l-8-8-8 8z",
    close: "M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z",
    check: "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z",
    error: "M11 15h2v2h-2zm0-8h2v6h-2zm.99-5C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8z",
    warning: "M12 5.99L19.53 19H4.47L12 5.99M12 2L1 21h22L12 2zm1 14h-2v2h2v-2zm0-6h-2v4h2v-4z",
    fullscreen: "M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z",
    moon: "M9.37 5.51c-.18.64-.27 1.31-.27 1.99 0 4.08 3.32 7.4 7.4 7.4.68 0 1.35-.09 1.99-.27C17.45 17.19 14.93 19 12 19c-3.86 0-7-3.14-7-7 0-2.93 1.81-5.45 4.37-6.49M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36a5.39 5.39 0 0 1-4.4 2.26 5.4 5.4 0 0 1-3.14-9.8c-.44-.06-.9-.1-1.36-.1z",
    sun: "M12 7c-2.76 0-5 2.24-5 5s2.24 5 5 5 5-2.24 5-5-2.24-5-5-5zM2 13h2c.55 0 1-.45 1-1s-.45-1-1-1H2c-.55 0-1 .45-1 1s.45 1 1 1zm18 0h2c.55 0 1-.45 1-1s-.45-1-1-1h-2c-.55 0-1 .45-1 1s.45 1 1 1zM11 2v2c0 .55.45 1 1 1s1-.45 1-1V2c0-.55-.45-1-1-1s-1 .45-1 1zm0 18v2c0 .55.45 1 1 1s1-.45 1-1v-2c0-.55-.45-1-1-1s-1 .45-1 1zM5.99 4.58a.996.996 0 0 0-1.41 0 .996.996 0 0 0 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0s.39-1.03 0-1.41L5.99 4.58zm12.37 12.37a.996.996 0 0 0-1.41 0 .996.996 0 0 0 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0a.996.996 0 0 0 0-1.41l-1.06-1.06zm1.06-10.96a.996.996 0 0 0 0-1.41.996.996 0 0 0-1.41 0l-1.06 1.06c-.39.39-.39 1.03 0 1.41s1.03.39 1.41 0l1.06-1.06zM7.05 18.36a.996.996 0 0 0 0-1.41.996.996 0 0 0-1.41 0l-1.06 1.06c-.39.39-.39 1.03 0 1.41s1.03.39 1.41 0l1.06-1.06z",
    link: "M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z",
    chat: "M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z",
    grid: "M3 3v8h8V3H3zm6 6H5V5h4v4zm-6 4v8h8v-8H3zm6 6H5v-4h4v4zm4-16v8h8V3h-8zm6 6h-4V5h4v4zm-6 4v8h8v-8h-8zm6 6h-4v-4h4v4z",
    "task-alt": "M22 5.18L10.59 16.6l-4.24-4.24 1.41-1.41 2.83 2.83 10-10L22 5.18zM12 20c-4.41 0-8-3.59-8-8s3.59-8 8-8c1.57 0 3.04.46 4.28 1.25l1.45-1.45A9.93 9.93 0 0 0 12 2C6.48 2 2 6.48 2 12s4.48 10 10 10c1.73 0 3.36-.44 4.78-1.22l-1.5-1.5c-1 .46-2.11.72-3.28.72z",
    compare: "M9.01 14H2v2h7.01v3L13 15l-3.99-4v3zm5.98-1v-3H22V8h-7.01V5L11 9l3.99 4z",
    verified: "M23 12l-2.44-2.79.34-3.69-3.61-.82-1.89-3.2L12 2.96 8.6 1.5 6.71 4.69 3.1 5.5l.34 3.7L1 12l2.44 2.79-.34 3.7 3.61.82L8.6 22.5l3.4-1.47 3.4 1.46 1.89-3.19 3.61-.82-.34-3.69L23 12zm-12.91 4.72l-3.8-3.81 1.48-1.48 2.32 2.33 5.85-5.87 1.48 1.48-7.33 7.35z",
    doc: "M8 16h8v2H8zm0-4h8v2H8zm6-10H6c-1.1 0-2 .9-2 2v16c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm4 18H6V4h7v5h5v11z",
    workspaces: "M12 4a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM6 14a3 3 0 1 0 0 6 3 3 0 0 0 0-6zm12 0a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
    "filter-off": "M4.25 5.61C6.27 8.2 10 13 10 13v6c0 .55.45 1 1 1h2c.55 0 1-.45 1-1v-6s3.72-4.8 5.74-7.39A.998.998 0 0 0 18.95 4H5.04c-.83 0-1.3.95-.79 1.61z"
  };

  function icon(name, sizeClass) {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", "icon" + (sizeClass ? " " + sizeClass : ""));
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    var path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", ICONS[name] || "");
    svg.appendChild(path);
    return svg;
  }

  function el(tag, props, children) {
    var node = document.createElement(tag);
    Object.keys(props || {}).forEach(function (key) {
      var value = props[key];
      if (value === null || value === undefined || value === false) return;
      if (key === "text") node.textContent = value;
      else if (key === "class") node.className = value;
      else if (key.indexOf("on") === 0) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? "" : String(value));
    });
    (children || []).forEach(function (child) {
      if (child === null || child === undefined || child === false) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function ring(fraction, label) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 140 140");
    svg.setAttribute("aria-hidden", "true");
    var circumference = 2 * Math.PI * RING_RADIUS;
    [["var(--muted)", 0], ["var(--badge)", circumference * (1 - fraction)]].forEach(function (spec, index) {
      if (index === 1 && fraction <= 0) return;
      var circle = document.createElementNS(ns, "circle");
      circle.setAttribute("cx", "70"); circle.setAttribute("cy", "70"); circle.setAttribute("r", String(RING_RADIUS));
      circle.setAttribute("fill", "none"); circle.setAttribute("stroke-width", "8");
      circle.style.stroke = spec[0];
      if (index === 1) {
        circle.setAttribute("stroke-linecap", "round");
        circle.style.strokeDasharray = String(circumference);
        circle.style.strokeDashoffset = String(spec[1]);
      }
      svg.appendChild(circle);
    });
    return el("div", { class: "ring" }, [svg, el("span", { class: "ring-value", text: label })]);
  }

  function storedTheme() {
    try { return window.localStorage.getItem(THEME_KEY); }
    catch (error) { return null; }
  }
  function isDark() {
    return document.documentElement.getAttribute("data-theme") === "dark";
  }
  function applyTheme(name) {
    document.documentElement.setAttribute("data-theme", name);
  }
  function toggleTheme() {
    var next = isDark() ? "light" : "dark";
    applyTheme(next);
    try { window.localStorage.setItem(THEME_KEY, next); }
    catch (error) { /* storage unavailable: choice lasts for this page only */ }
  }
  var saved = storedTheme();
  var prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(saved === "dark" || saved === "light" ? saved : prefersDark ? "dark" : "light");

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
  var SMALL_AVATAR_TEXT = 3;
  var SMALL_FONT_RATIO = 0.24;

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
    var day = new Intl.DateTimeFormat("fr-CA", { day: "numeric", month: "long", year: "numeric" });
    var time = new Intl.DateTimeFormat("fr-CA", { hour: "numeric", minute: "2-digit" });
    return day.format(date) + ", " + time.format(date);
  }
  function decimal(number, digits) { return number.toFixed(digits).replace(".", ","); }
  function tone(name) { return "t-" + name; }
  function chip(text, toneName, extra) {
    return el("span", { class: "chip " + tone(toneName) + (extra ? " " + extra : ""), text: text });
  }
  function avatar(text, toneName, size) {
    var props = { class: "avatar " + tone(toneName), style: "--s:" + size + "px" };
    if (text.length > SMALL_AVATAR_TEXT) props.style += ";font-size:" + Math.round(size * SMALL_FONT_RATIO) + "px";
    return el("span", props, [text]);
  }
  var STEP_ICONS = {
    route: "arrow-forward", retrieve: "search", draft: "doc", hop: "link",
    validate: "verified", ground: "task-alt", render: "fullscreen"
  };
  var STEPS_TITLE = "Déroulement";
  var TOTAL_LABEL = "Total : ";
  function stepRow(step, marker) {
    return el("li", { class: "step" }, [
      marker,
      el("span", { class: "grow" }, [
        el("span", { text: step.label }),
        step.detail ? el("span", { class: "step-detail", text: " · " + step.detail }) : null
      ]),
      el("span", { class: "step-time", text: decimal(step.elapsed_s || 0, 1) + " s" })
    ]);
  }
  function stepsTimeline(steps, totalSeconds) {
    if (!Array.isArray(steps) || !steps.length) return null;
    var total = typeof totalSeconds === "number" ? totalSeconds : steps[steps.length - 1].elapsed_s || 0;
    return el("details", { class: "timeline", open: true }, [
      el("summary", {}, [el("span", { text: STEPS_TITLE }), icon("arrow-forward", "sm chevron")]),
      el("ul", { class: "steps" }, steps.map(function (step) {
        return stepRow(step, icon(STEP_ICONS[step.step] || "check", "sm"));
      })),
      el("div", { class: "timeline-total", text: TOTAL_LABEL + decimal(total, 1) + " s" })
    ]);
  }

  function iconButton(name, label, onclick, extraClass) {
    return el("button", { class: "round " + (extraClass || ""), type: "button", "aria-label": label, title: label, onclick: onclick }, [icon(name)]);
  }

  window.ViewerDom = {
    el: el, clear: clear, icon: icon, ring: ring, isDark: isDark, toggleTheme: toggleTheme,
    STATUS: STATUS, CONF: CONF, confKey: confKey, asList: asList, answerText: answerText,
    normalize: normalize, formatDate: formatDate, decimal: decimal, initials: initials, tone: tone, chip: chip, avatar: avatar, iconButton: iconButton,
    stepRow: stepRow, stepsTimeline: stepsTimeline
  };
})();
