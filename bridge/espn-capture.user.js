// ==UserScript==
// @name         ESPN Draft Capture
// @namespace    fantasy-draft-assistant
// @version      0.1
// @description  Capture the ESPN draft room's own traffic so a local tool can follow the draft. ESPN's read API does not publish picks while a draft runs; the draft room gets them over its own connection, which only exists inside the browser.
// @match        https://fantasy.espn.com/*
// @match        https://*.espn.com/football/draft*
// @match        https://*.espn.com/football/waitingroom*
// @run-at       document-start
// @grant        none
// ==/UserScript==

(function () {
  "use strict";

  // Everything seen so far, for inspection from the console.
  const log = [];
  window.__draftCapture = log;

  const note = (channel, url, payload) => {
    let text = payload;
    if (typeof text !== "string") {
      try { text = JSON.stringify(text); } catch (e) { text = String(text); }
    }
    if (!text || text.length < 2) return;
    log.push({ t: Date.now(), channel, url: String(url).slice(0, 160),
               body: text.slice(0, 4000) });
    if (log.length % 25 === 0) {
      console.log(`[capture] ${log.length} messages — run copyCapture()`);
    }
  };

  // --- websockets: wrapped before the page can open any ---
  const NativeWS = window.WebSocket;
  function WrappedWS(url, protocols) {
    const ws = protocols === undefined ? new NativeWS(url)
                                       : new NativeWS(url, protocols);
    console.log("[capture] websocket opened:", url);
    ws.addEventListener("message", (e) => note("ws", url, e.data));
    const send = ws.send.bind(ws);
    ws.send = (data) => { note("ws-send", url, data); return send(data); };
    return ws;
  }
  WrappedWS.prototype = NativeWS.prototype;
  ["CONNECTING", "OPEN", "CLOSING", "CLOSED"].forEach((k, i) => {
    WrappedWS[k] = i;
  });
  window.WebSocket = WrappedWS;

  // --- fetch, in case picks arrive over plain HTTP polling instead ---
  const nativeFetch = window.fetch;
  if (nativeFetch) {
    window.fetch = async function (...args) {
      const res = await nativeFetch.apply(this, args);
      const url = (args[0] && args[0].url) || args[0];
      if (/draft|pick|roster/i.test(String(url))) {
        res.clone().text().then((t) => note("fetch", url, t)).catch(() => {});
      }
      return res;
    };
  }

  // --- XHR, same reason ---
  const open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.addEventListener("load", () => {
      if (/draft|pick|roster/i.test(String(url))) {
        note("xhr", url, this.responseText);
      }
    });
    return open.call(this, method, url, ...rest);
  };

  // --- helpers to get the capture out ---
  window.copyCapture = function (n) {
    const slice = log.slice(-(n || 40));
    const text = JSON.stringify(slice, null, 1);
    if (typeof copy === "function") { copy(text); console.log("copied", slice.length, "messages"); }
    else console.log(text);
    return slice.length;
  };
  window.captureSummary = function () {
    const byChannel = {};
    log.forEach((m) => {
      const key = m.channel + " " + m.url.split("?")[0];
      byChannel[key] = (byChannel[key] || 0) + 1;
    });
    console.table(byChannel);
    return byChannel;
  };

  // A banner, because "is this thing on?" is the first question and the
  // console is busy. Removed once picks start arriving.
  const banner = () => {
    if (!document.body) return setTimeout(banner, 50);
    const el = document.createElement("div");
    el.id = "draft-capture-banner";
    el.textContent = "capture armed — 0 msgs";
    // Top-right: DevTools docks at the bottom, which hid this.
    el.style.cssText = "position:fixed;top:8px;right:8px;z-index:2147483647;" +
      "background:#0a7;color:#fff;font:12px/1.4 monospace;padding:4px 8px;" +
      "border-radius:4px;opacity:.9;pointer-events:none";
    document.body.appendChild(el);
    setInterval(() => {
      el.textContent = `capture armed — ${log.length} msgs`;
      el.style.background = log.length ? "#0a7" : "#a70";
    }, 1000);
  };
  banner();

  console.log("[capture] armed on", location.href,
              "— draft as normal, then run: captureSummary() / copyCapture()");
})();
