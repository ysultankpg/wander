import { render } from "/md.js";

const $ = (s) => document.querySelector(s);
const thread = $("#thread");
const input = $("#input");
const send = $("#send");
const statusEl = $("#status");
const tpl = $("#tpl-msg");

let busy = false;

/* ---------- health ---------- */

async function health() {
  try {
    const r = await fetch("/api/health");
    const d = await r.json();
    statusEl.className = "status " + (d.ok ? "ok" : "bad");
    statusEl.querySelector("span").textContent = d.ok
      ? `${d.model} · ${d.destinations}+ destinations · local`
      : d.detail;
  } catch {
    statusEl.className = "status bad";
    statusEl.querySelector("span").textContent = "server unreachable";
  }
}

/* ---------- theme ---------- */

const saved = localStorage.getItem("wander-theme");
if (saved) document.documentElement.dataset.theme = saved;
$("#theme").onclick = () => {
  const cur = document.documentElement.dataset.theme;
  const next = cur === "dark" ? "light" : cur === "light" ? "auto" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("wander-theme", next);
};

/* ---------- messages ---------- */

function bubble(role) {
  $("#welcome")?.remove();
  const node = tpl.content.cloneNode(true).querySelector(".msg");
  node.classList.add(role === "user" ? "me" : "bot");
  node.querySelector(".avatar").textContent = role === "user" ? "🙂" : "🧭";
  thread.appendChild(node);
  scroll();
  return {
    tools: node.querySelector(".tools"),
    content: node.querySelector(".content"),
  };
}

function scroll() {
  thread.scrollTop = thread.scrollHeight;
}

function pill(box, text, isError) {
  box.hidden = false;
  const el = document.createElement("span");
  el.className = "pill" + (isError ? " err" : "");
  el.textContent = text;
  box.appendChild(el);
  scroll();
  return el;
}

/* ---------- send turn ---------- */

async function ask(message) {
  if (busy || !message.trim()) return;
  busy = true;
  send.disabled = true;

  bubble("user").content.textContent = message;
  const bot = bubble("bot");
  bot.content.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';

  let answer = "";
  let statusPill = null;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ message }),
    });

    if (!res.ok || !res.body) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || detail.error || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });

      let split;
      while ((split = buf.indexOf("\n\n")) !== -1) {
        const frame = buf.slice(0, split);
        buf = buf.slice(split + 2);
        if (!frame.startsWith("data:")) continue;

        let evt;
        try { evt = JSON.parse(frame.slice(5).trim()); } catch { continue; }

        if (evt.type === "status") {
          if (!statusPill) statusPill = pill(bot.tools, evt.data, false);
          else statusPill.textContent = evt.data;
        } else if (evt.type === "tool") {
          const name = (evt.data?.name || "tool").replace(/_/g, " ");
          const bad = evt.data?.result && evt.data.result.error;
          pill(bot.tools, bad ? `${name} — ${evt.data.result.error}` : `✓ ${name}`, !!bad);
        } else if (evt.type === "token") {
          answer += evt.data;
          bot.content.innerHTML = render(answer);
          scroll();
        } else if (evt.type === "error") {
          pill(bot.tools, evt.data, true);
        }
      }
    }

    if (!answer.trim()) bot.content.innerHTML = render("_No answer came back. Try rephrasing._");
  } catch (err) {
    bot.content.innerHTML = render(`**Something went wrong:** ${err.message}`);
  } finally {
    if (statusPill) statusPill.remove();
    busy = false;
    send.disabled = false;
    input.focus();
  }
}

/* ---------- wiring ---------- */

$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value;
  input.value = "";
  input.style.height = "auto";
  ask(text);
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("#composer").requestSubmit();
  }
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 180) + "px";
});

document.addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (chip) ask(chip.dataset.q);
});

$("#reset").onclick = async () => {
  if (busy) return;
  await fetch("/api/reset", { method: "POST", credentials: "same-origin" });
  thread.innerHTML = "";
  location.reload();
};

health();
setInterval(health, 30000);
input.focus();
