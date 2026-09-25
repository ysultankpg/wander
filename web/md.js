// Minimal markdown renderer. Escapes first, then applies a fixed, small set of
// rules — so model output can never inject HTML. The old UI used innerHTML on
// raw text, which is exactly the bug this avoids.

const esc = (s) => s.replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
));

// Only http(s) image/link URLs survive — no javascript:, no data:.
const safeUrl = (u) => (/^https?:\/\//i.test(u.trim()) ? u.trim() : null);

function inline(text) {
  let out = esc(text);
  out = out.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (m, alt, url) => {
    const u = safeUrl(url);
    return u ? `<img src="${u}" alt="${alt}" loading="lazy" />` : "";
  });
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, label, url) => {
    const u = safeUrl(url);
    return u ? `<a href="${u}" target="_blank" rel="noopener noreferrer">${label}</a>` : label;
  });
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  return out;
}

const isRule = (l) => /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(l) && l.includes("-");
const cells = (l) => l.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => inline(c.trim()));

export function render(src) {
  const lines = String(src || "").replace(/\r/g, "").split("\n");
  const html = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) { i++; continue; }

    // Table: header row followed by a |---|---| rule.
    if (line.includes("|") && isRule(lines[i + 1] || "")) {
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        rows.push(cells(lines[i])); i++;
      }
      html.push(
        "<table><thead><tr>" + head.map((c) => `<th>${c}</th>`).join("") +
        "</tr></thead><tbody>" +
        rows.map((r) => "<tr>" + r.map((c) => `<td>${c}</td>`).join("") + "</tr>").join("") +
        "</tbody></table>"
      );
      continue;
    }

    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { html.push(`<h3>${inline(h[2])}</h3>`); i++; continue; }

    if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
        items.push(`<li>${inline(lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, ""))}</li>`);
        i++;
      }
      html.push(`<${ordered ? "ol" : "ul"}>${items.join("")}</${ordered ? "ol" : "ul"}>`);
      continue;
    }

    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|\s*([-*+]|\d+\.)\s)/.test(lines[i])) {
      para.push(lines[i]); i++;
    }
    html.push(`<p>${inline(para.join(" "))}</p>`);
  }

  return html.join("");
}
