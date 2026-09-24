"""HTML sign-off report from a run object (see CONTRACT.md).

render_report(run) -> standalone, print-ready HTML string.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

SEV_COLOUR = {"Critical": "#dc2626", "Material": "#f59e0b", "Cosmetic": "#94a3b8"}
SEV_ORDER = {"Critical": 0, "Material": 1, "Cosmetic": 2}
STATUS_LABEL = {"confirmed": "Confirmed", "dismissed": "Dismissed", "unresolved": "Unresolved",
                "unreviewed": "Unreviewed"}
REASON_LABEL = {"false_positive": "False positive", "acceptable_variation": "Acceptable variation",
                "will_fix_in_source": "Will fix in source"}

_CSS = """
@font-face{font-family:"Open Runde";font-weight:400;font-display:swap;src:url(https://cdn.jsdelivr.net/npm/@fontsource/open-runde/files/open-runde-latin-400-normal.woff2) format("woff2")}
@font-face{font-family:"Open Runde";font-weight:500;font-display:swap;src:url(https://cdn.jsdelivr.net/npm/@fontsource/open-runde/files/open-runde-latin-500-normal.woff2) format("woff2")}
@font-face{font-family:"Open Runde";font-weight:600;font-display:swap;src:url(https://cdn.jsdelivr.net/npm/@fontsource/open-runde/files/open-runde-latin-600-normal.woff2) format("woff2")}
@page{size:A4;margin:18mm 16mm}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:#fff}
body{font-family:"Open Runde",-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;color:#3f3f46;font-size:11pt;line-height:1.5;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.page{max-width:760px;margin:0 auto;padding:40px 24px 64px}
@media print{.page{max-width:none;padding:0}}
h1,h2,h3{color:#181925;letter-spacing:-0.02em;font-weight:600;margin:0}
h1{font-size:24pt;line-height:1.15}
h2{font-size:15pt;margin:40px 0 14px;padding-bottom:8px;border-bottom:1px solid #e8e8e8;break-after:avoid}
h3{font-size:11pt}
.muted{color:#666}.soft{color:#737373}.faint{color:#a3a3a3}
.zh{font-family:"Noto Sans TC","PingFang TC","Open Runde",sans-serif}
.num{font-variant-numeric:tabular-nums}
.eyebrow{font-size:9pt;text-transform:uppercase;letter-spacing:.08em;color:#9580ff;font-weight:600;margin-bottom:10px}
.cover{padding-bottom:28px;border-bottom:1px solid #e8e8e8}
.titles{margin:18px 0 6px;font-size:12pt;color:#181925;font-weight:500}
.titles .zh{display:block;margin-top:2px;color:#3f3f46;font-weight:400}
.meta{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 32px;margin-top:22px;font-size:10pt}
.meta div{display:grid;grid-template-columns:120px 1fr;gap:0 12px;align-items:baseline}
.meta div span:first-child{color:#737373}
.meta div span:last-child{color:#181925}
.counts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:26px}
.tile{border:1px solid #e8e8e8;border-radius:12px;padding:12px 14px;background:#fff}
.tile .n{font-size:22pt;font-weight:600;color:#181925;line-height:1.1}
.tile .l{font-size:9pt;color:#737373;margin-top:4px;display:flex;align-items:center;gap:6px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%}
.status-row{display:flex;flex-wrap:wrap;gap:8px 18px;margin-top:14px;font-size:10pt;color:#3f3f46}
.status-row b{color:#181925;font-weight:600}
.card{border:1px solid #e8e8e8;border-radius:12px;padding:16px 18px;margin:0 0 14px;break-inside:avoid;page-break-inside:avoid;background:#fff}
.card-head{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:10px}
.fid{font-weight:600;color:#181925;font-variant-numeric:tabular-nums}
.pill{display:inline-block;border-radius:999px;padding:1px 9px;font-size:8.5pt;font-weight:500;line-height:1.6;border:1px solid #e8e8e8;color:#3f3f46;background:#fff}
.pill.type{background:#f5f5f5;border-color:#f5f5f5}
.pill.sev{color:#fff;border-color:transparent}
.pill.src{color:#737373}
.section{margin-left:auto;font-size:9pt;color:#737373;text-align:right}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.col{border-left:2px solid #e8e8e8;padding-left:12px}
.col .lab{font-size:8.5pt;color:#a3a3a3;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px;display:flex;justify-content:space-between}
.col .txt{font-size:10pt;color:#181925;line-height:1.55;overflow-wrap:anywhere}
mark{background:#f3f1ff;color:inherit;border-bottom:1.5px solid #9580ff;padding:0 1px;border-radius:2px}
.expl{margin-top:12px;font-size:10pt;color:#3f3f46}
.expl b{color:#181925;font-weight:600}
.decision{margin-top:10px;padding-top:10px;border-top:1px solid #e8e8e8;font-size:9.5pt;color:#3f3f46;display:flex;flex-wrap:wrap;gap:6px 18px}
.decision span span{color:#181925;font-weight:500}
.note{margin-top:6px;font-size:9.5pt;color:#3f3f46;background:#f5f5f5;border-radius:8px;padding:8px 10px}
table{width:100%;border-collapse:collapse;font-size:10pt}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid #e8e8e8;vertical-align:top}
th{font-weight:500;color:#737373;font-size:9pt}
.empty{color:#a3a3a3;font-size:10pt}
.footer{margin-top:48px;padding-top:12px;border-top:1px solid #e8e8e8;font-size:9pt;color:#a3a3a3;display:flex;justify-content:space-between}
.unaligned{border:1px solid #fcd34d;border-radius:12px;padding:10px 14px;margin-bottom:8px;font-size:10pt;color:#181925;break-inside:avoid}
.unaligned .tag{font-size:8.5pt;color:#737373;margin-left:8px}
"""


def _e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _marked(text: str, span) -> str:
    text = text or ""
    if span and isinstance(span, (list, tuple)) and len(span) == 2:
        try:
            a, b = int(span[0]), int(span[1])
        except (TypeError, ValueError):
            return _e(text)
        if 0 <= a < b <= len(text):
            return _e(text[:a]) + "<mark>" + _e(text[a:b]) + "</mark>" + _e(text[b:])
    return _e(text)


def _fmt_ts(ts) -> str:
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y, %H:%M UTC")
    except ValueError:
        return str(ts)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")


def _card(f: dict) -> str:
    sev = f.get("severity") or "Cosmetic"
    en, zh = f.get("en") or {}, f.get("zh") or {}
    status = f.get("status") or "unreviewed"
    conf = f.get("confidence")
    conf_s = f"{float(conf) * 100:.0f}%" if isinstance(conf, (int, float)) else "—"
    parts = [f'<article class="card" id="{_e(f.get("id"))}">',
             '<div class="card-head">',
             f'<span class="fid">{_e(f.get("id"))}</span>',
             f'<span class="pill type">{_e((f.get("type") or "").replace("_", " "))}</span>',
             f'<span class="pill sev" style="background:{SEV_COLOUR.get(sev, "#94a3b8")}">{_e(sev)}</span>',
             f'<span class="pill src">{_e(f.get("source") or "")}</span>',
             f'<span class="section">{_e(f.get("section") or "")}</span>',
             '</div>',
             '<div class="cols">',
             '<div class="col"><div class="lab"><span>English</span>'
             f'<span class="num">{"p." + str(en.get("page")) if en.get("page") is not None else ""}</span></div>'
             f'<div class="txt">{_marked(en.get("text"), en.get("span"))}</div></div>',
             '<div class="col"><div class="lab"><span>Chinese</span>'
             f'<span class="num">{"p." + str(zh.get("page")) if zh.get("page") is not None else ""}</span></div>'
             f'<div class="txt zh">{_marked(zh.get("text"), zh.get("span"))}</div></div>',
             '</div>',
             f'<div class="expl"><b>Finding.</b> {_e(f.get("explanation") or "")} '
             f'<span class="soft num">Confidence {conf_s}.</span></div>',
             '<div class="decision">',
             f'<span>Decision: <span>{_e(STATUS_LABEL.get(status, status))}</span></span>']
    if f.get("dismiss_reason"):
        parts.append(f'<span>Reason: <span>{_e(REASON_LABEL.get(f["dismiss_reason"], f["dismiss_reason"]))}</span></span>')
    parts.append('</div>')
    if f.get("note"):
        parts.append(f'<div class="note">{_e(f["note"])}</div>')
    parts.append('</article>')
    return "\n".join(parts)


def render_report(run: dict) -> str:
    run = run or {}
    meta = run.get("meta") or {}
    findings = list(run.get("findings") or [])
    findings.sort(key=lambda f: (SEV_ORDER.get(f.get("severity"), 3),
                                 ((f.get("en") or {}).get("page") if (f.get("en") or {}).get("page") is not None else 10 ** 6),
                                 f.get("id") or ""))
    counts = run.get("counts") or {}
    by_sev = {s: sum(1 for f in findings if f.get("severity") == s) for s in SEV_ORDER}
    by_status = {s: sum(1 for f in findings if (f.get("status") or "unreviewed") == s) for s in STATUS_LABEL}
    unaligned = run.get("unaligned_sections") or []
    unreadable = meta.get("unreadable_pages") or {}
    glossary = run.get("glossary") or []
    auth = meta.get("authoritative") or "none"
    auth_label = {"EN": "English prevails", "ZH": "Chinese prevails"}.get(auth, "No authoritative version")
    if meta.get("authoritative_detected") and auth in ("EN", "ZH"):
        auth_label += " (detected from the filing)"
    generated = _now()

    out = [f'<title>Concord — {_e(meta.get("company") or run.get("run_id") or "sign-off")}</title>',
           f'<style>{_CSS}</style>',
           '<div class="page">',
           '<header class="cover">',
           '<div class="eyebrow">Concord</div>',
           '<h1>Bilingual consistency sign-off</h1>',
           f'<div class="titles">{_e(meta.get("en_title") or "—")}'
           f'<span class="zh">{_e(meta.get("zh_title") or "—")}</span></div>',
           '<div class="meta">',
           f'<div><span>Company</span><span>{_e(meta.get("company") or "—")}</span></div>',
           f'<div><span>Stock code</span><span class="num">{_e(meta.get("stock_code") or "—")}</span></div>',
           f'<div><span>Run</span><span class="num">{_e(run.get("run_id") or "—")} · {_e(_fmt_ts(run.get("created_at")))}</span></div>',
           f'<div><span>Authoritative version</span><span>{_e(auth_label)}</span></div>',
           f'<div><span>Reviewer</span><span>{_e(run.get("reviewer") or "—")}</span></div>',
           f'<div><span>Pages</span><span class="num">EN {_e(meta.get("en_pages", "—"))} · ZH {_e(meta.get("zh_pages", "—"))}</span></div>',
           '</div>',
           '<div class="counts">']
    for sev in SEV_ORDER:
        out.append(f'<div class="tile"><div class="n num">{by_sev[sev]}</div>'
                   f'<div class="l"><span class="dot" style="background:{SEV_COLOUR[sev]}"></span>{sev}</div></div>')
    out.append(f'<div class="tile"><div class="n num">{_e(counts.get("unaligned_sections", len(unaligned)))}</div>'
               f'<div class="l"><span class="dot" style="background:#fcd34d"></span>Unaligned sections</div></div>')
    out.append('</div>')
    out.append('<div class="status-row">' + " ".join(
        f'<span>{STATUS_LABEL[s]} <b class="num">{by_status[s]}</b></span>' for s in STATUS_LABEL)
        + f' <span class="soft">· {_e(counts.get("total", len(findings)))} findings in total</span></div>')
    out.append('</header>')

    # findings
    out.append('<h2>Findings</h2>')
    if not findings:
        out.append('<p class="empty">No discrepancies were found between the two versions.</p>')
    else:
        current = None
        for f in findings:
            sev = f.get("severity") or "Cosmetic"
            if sev != current:
                current = sev
                out.append(f'<h3 style="margin:22px 0 10px;color:{SEV_COLOUR.get(sev, "#94a3b8")}">{_e(sev)} '
                           f'<span class="soft num" style="font-weight:400">· {by_sev.get(sev, 0)}</span></h3>')
            out.append(_card(f))

    # appendix
    out.append('<h2>Appendix</h2>')
    out.append('<h3 style="margin:14px 0 8px">Unaligned sections</h3>')
    if unaligned:
        for u in unaligned:
            out.append(f'<div class="unaligned"><span class="{"zh" if u.get("lang") == "zh" else ""}">{_e(u.get("heading") or "—")}</span>'
                       f'<span class="tag">{_e((u.get("lang") or "").upper())}'
                       f'{" p." + str(u.get("page")) if u.get("page") is not None else ""} · no counterpart</span></div>')
    else:
        out.append('<p class="empty">Every section has a counterpart.</p>')

    out.append('<h3 style="margin:22px 0 8px">Unreadable pages</h3>')
    en_bad, zh_bad = unreadable.get("en") or [], unreadable.get("zh") or []
    if en_bad or zh_bad:
        out.append(f'<p class="num">EN: {_e(", ".join(map(str, en_bad)) or "none")} · '
                   f'ZH: {_e(", ".join(map(str, zh_bad)) or "none")}</p>')
    else:
        out.append('<p class="empty">All pages were readable.</p>')

    out.append('<h3 style="margin:22px 0 8px">Glossary of defined terms</h3>')
    if glossary:
        out.append('<table><thead><tr><th>English</th><th>Chinese</th></tr></thead><tbody>')
        for g in glossary:
            out.append(f'<tr><td>{_e(g.get("en"))}</td><td class="zh">{_e(g.get("zh"))}</td></tr>')
        out.append('</tbody></table>')
    else:
        out.append('<p class="empty">No glossary was extracted.</p>')

    out.append(f'<footer class="footer"><span>Generated by Concord</span><span class="num">{_e(generated)}</span></footer>')
    out.append('</div>')
    return "\n".join(out)


if __name__ == "__main__":
    import json
    import os
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "findings.json")
    dst = sys.argv[2] if len(sys.argv) > 2 else "/tmp/report.html"
    with open(src, encoding="utf-8") as fh:
        run = json.load(fh)
    html_out = render_report(run)
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(html_out)
    print(f"wrote {dst} ({len(html_out)} bytes)")
