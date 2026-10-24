"""Build outbox/index.html - an inbox-style viewer for DEMO MODE emails."""
from __future__ import annotations

import html
import re
from pathlib import Path

KIND_LABELS = {
    "mom": "Minutes of Meeting", "followup": "Follow-up", "reminder": "Reminder",
    "weekly-report": "Weekly report", "invite": "Invite",
}
KIND_COLORS = {
    "mom": "#0f766e", "followup": "#1d4ed8", "reminder": "#b91c1c",
    "weekly-report": "#7c3aed", "invite": "#d97706",
}
_BANNER_RE = re.compile(r"To: (?P<to>.*?)<br>Subject: (?P<subject>.*?)(?: &middot; attachment: (?P<att>[^<]*))?</div>", re.S)


def _entries(outbox: Path) -> list[dict]:
    entries = []
    for path in sorted(outbox.glob("*__*.html"), key=lambda p: p.stat().st_mtime, reverse=True):
        kind = path.name.split("__", 1)[0]
        match = _BANNER_RE.search(path.read_text(encoding="utf-8", errors="replace")[:4000])
        entries.append({
            "file": path.name,
            "kind": kind,
            "to": html.unescape(match["to"]) if match else "",
            "subject": html.unescape(match["subject"]) if match else path.stem,
            "attachment": html.unescape(match["att"] or "") if match else "",
        })
    return entries


def write_index(outbox: Path, project_name: str) -> Path:
    entries = _entries(outbox)
    counts = {k: sum(1 for e in entries if e["kind"] == k) for k in KIND_LABELS}
    filters = "".join(
        f'<button data-kind="{k}">{html.escape(label)} <span>{counts[k]}</span></button>'
        for k, label in KIND_LABELS.items() if counts[k]
    )
    items = "".join(
        f'<a class="item" href="{html.escape(e["file"])}" target="preview" data-kind="{html.escape(e["kind"])}">'
        f'<span class="tag" style="background:{KIND_COLORS.get(e["kind"], "#475569")}">'
        f'{html.escape(KIND_LABELS.get(e["kind"], e["kind"]))}</span>'
        f'<span class="subject">{html.escape(e["subject"])}</span>'
        f'<span class="to">To: {html.escape(e["to"])}</span>'
        + (f'<span class="att">&#128206; {html.escape(e["attachment"])}</span>' if e["attachment"] else "")
        + "</a>"
        for e in entries
    )
    first = html.escape(entries[0]["file"]) if entries else "about:blank"
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Outbox - {html.escape(project_name)}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;font-family:Segoe UI,Helvetica,Arial,sans-serif;background:#eef2f7;color:#1e293b;height:100vh;display:flex;flex-direction:column}}
header{{background:#0f2747;color:#fff;padding:14px 20px;display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}}
header h1{{font-size:18px;margin:0}} header .sub{{color:#cbd5e1;font-size:13px}}
header .demo{{margin-left:auto;background:#fff7ed;color:#9a3412;font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px}}
main{{flex:1;display:flex;min-height:0}}
aside{{width:380px;min-width:300px;background:#fff;border-right:1px solid #e2e8f0;display:flex;flex-direction:column}}
.filters{{display:flex;flex-wrap:wrap;gap:6px;padding:12px;border-bottom:1px solid #e2e8f0}}
.filters button{{border:1px solid #cbd5e1;background:#fff;border-radius:999px;padding:4px 10px;font-size:12px;cursor:pointer;color:#334155}}
.filters button span{{color:#64748b}} .filters button.on{{background:#0f2747;color:#fff;border-color:#0f2747}} .filters button.on span{{color:#cbd5e1}}
.list{{overflow-y:auto;flex:1}}
.item{{display:flex;flex-direction:column;gap:3px;padding:12px 14px;border-bottom:1px solid #f1f5f9;text-decoration:none;color:inherit;border-left:3px solid transparent}}
.item:hover{{background:#f8fafc}} .item.active{{background:#eff6ff;border-left-color:#1d4ed8}}
.tag{{align-self:flex-start;color:#fff;font-size:11px;font-weight:600;padding:1px 8px;border-radius:999px}}
.subject{{font-size:14px;font-weight:600}} .to,.att{{font-size:12px;color:#64748b;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
iframe{{flex:1;border:0;background:#eef2f7}}
.empty{{padding:20px;color:#64748b;font-size:14px}}
@media (max-width:760px){{main{{flex-direction:column}} aside{{width:100%;max-height:45vh}}}}
</style></head><body>
<header><h1>Outbox</h1><span class="sub">{html.escape(project_name)} &middot; {len(entries)} emails</span>
<span class="demo">DEMO MODE - nothing was sent</span></header>
<main>
<aside><div class="filters"><button data-kind="" class="on">All <span>{len(entries)}</span></button>{filters}</div>
<div class="list">{items or '<div class="empty">No emails yet. Run <code>python main.py demo</code>.</div>'}</div></aside>
<iframe name="preview" src="{first}" title="Email preview"></iframe>
</main>
<script>
const items=[...document.querySelectorAll('.item')];
const select=a=>{{items.forEach(i=>i.classList.toggle('active',i===a));}};
items.forEach(a=>a.addEventListener('click',()=>select(a)));
if(items[0])select(items[0]);
document.querySelectorAll('.filters button').forEach(b=>b.addEventListener('click',()=>{{
  document.querySelectorAll('.filters button').forEach(x=>x.classList.toggle('on',x===b));
  items.forEach(i=>i.style.display=!b.dataset.kind||i.dataset.kind===b.dataset.kind?'':'none');
}}));
</script>
</body></html>"""
    path = outbox / "index.html"
    path.write_text(page, encoding="utf-8")
    return path
