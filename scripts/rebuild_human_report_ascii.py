import html
import json
from pathlib import Path


def zh(codepoints: str) -> str:
    return codepoints.encode("ascii").decode("unicode_escape")


ROOT = Path("outputs/casepack_moderation_10/ground_truth")
SRC = ROOT / "comparison_full.json"
MD_OUT = ROOT / "comparison_report_human_safe.md"
HTML_OUT = ROOT / "comparison_report_human_safe.html"

data = json.loads(SRC.read_text(encoding="utf-8"))
items = data.get("items", [])
summary = data.get("summary", {})

# Chinese labels encoded with \\u to avoid shell/codepage corruption.
T_TITLE = zh("\\u5bf9\\u6bd4\\u62a5\\u544a\\uff08\\u4eba\\u8bdd\\u7248\\uff09")
T_SUB = zh("\\u53ea\\u770b\\u4e09\\u4ef6\\u4e8b\\uff1a\\u6a21\\u578b\\u63d0\\u53d6\\u4e86\\u4ec0\\u4e48\\u3001\\u4eba\\u5de5\\u6807\\u51c6\\u662f\\u4ec0\\u4e48\\u3001\\u5dee\\u5728\\u54ea\\u91cc\\u3002")
T_TOTAL = zh("\\u603b\\u4f53\\u60c5\\u51b5")
T_DIRECT = zh("\\u76f4\\u63a5\\u6548\\u5e94")
T_MOD = zh("\\u8c03\\u8282\\u6548\\u5e94")
T_CONSIST = zh("\\u4e00\\u81f4")
T_MODEL_MORE = zh("\\u6a21\\u578b\\u591a\\u4e86")
T_MODEL_MISS = zh("\\u6a21\\u578b\\u6f0f\\u4e86")
T_MODEL_EXTRACT = zh("\\u6a21\\u578b\\u63d0\\u53d6\\u4e86\\u4ec0\\u4e48")
T_GT = zh("\\u4f60\\u63d0\\u53d6\\u51fa\\u7684\\u6807\\u51c6\\u662f\\u4ec0\\u4e48")
T_DIFF = zh("\\u5dee\\u5f02\\uff08\\u8bf4\\u4eba\\u8bdd\\uff09")
T_FILE = zh("\\u6587\\u4ef6")


def fmt_pair(pair):
    return f"{pair[0]} -> {pair[1]}"


def fmt_mod(item):
    return f"{item[0]} {zh('\\u8c03\\u8282')} {item[1]} -> {item[2]}"


md = [f"# {T_TITLE}", "", T_SUB, "", f"## {T_TOTAL}", ""]
md.append(
    f"- {T_DIRECT}：{zh('\\u6a21\\u578b')} {summary.get('glm_direct', 0)} {zh('\\u6761')}；"
    f"{zh('\\u4eba\\u5de5')} {summary.get('gt_direct', 0)} {zh('\\u6761')}；"
    f"{T_CONSIST} {summary.get('tp_direct', 0)} {zh('\\u6761')}。"
)
md.append(
    f"- {T_MOD}：{zh('\\u6a21\\u578b')} {summary.get('glm_mod', 0)} {zh('\\u6761')}；"
    f"{zh('\\u4eba\\u5de5')} {summary.get('gt_mod', 0)} {zh('\\u6761')}；"
    f"{T_CONSIST} {summary.get('tp_mod', 0)} {zh('\\u6761')}。"
)
md.append("")

for it in items:
    doi = it.get("doi", "")
    g = it.get("gt", {})
    p = it.get("glm", {})
    c = it.get("cmp", {})
    md.extend(
        [
            "",
            f"## {doi}",
            f"- {T_FILE}：`{p.get('file', '')}`",
            "",
            f"### 1) {T_MODEL_EXTRACT}",
            f"- {T_DIRECT}：{len(p.get('direct', []))} {zh('\\u6761')}",
        ]
    )
    for r in p.get("direct", []):
        md.append(
            f"- {r.get('source', '')} -> {r.get('target', '')}"
            f"（{r.get('direction', '')}，{r.get('verification', '')}）"
        )
    md.append(f"- {T_MOD}：{len(p.get('moderations', []))} {zh('\\u6761')}")
    for r in p.get("moderations", []):
        md.append(
            f"- {r.get('moderator', '')} {zh('\\u8c03\\u8282')} {r.get('moderated_effects', '')}"
            f"（{r.get('direction', '')}，{r.get('verification', '')}）"
        )

    md.extend(["", f"### 2) {T_GT}", f"- {T_DIRECT}：{len(g.get('direct_effects', []))} {zh('\\u6761')}"])
    for r in g.get("direct_effects", []):
        md.append(
            f"- {r.get('source', '')} -> {r.get('target', '')}"
            f"（{r.get('direction', '')}，{r.get('verification', '')}）"
        )
    md.append(f"- {T_MOD}：{len(g.get('moderations', []))} {zh('\\u6761')}")
    for r in g.get("moderations", []):
        rel = "; ".join(
            [f"{x.get('source', '')} -> {x.get('target', '')}" for x in (r.get("moderated_effects") or [])]
        )
        md.append(
            f"- {r.get('moderator', '')} {zh('\\u8c03\\u8282')} {rel}"
            f"（{r.get('direction', '')}，{r.get('verification', '')}）"
        )

    md.extend(
        [
            "",
            f"### 3) {T_DIFF}",
            f"- {T_DIRECT}：{T_CONSIST} {len(c.get('tp_d', []))} {zh('\\u6761')}，"
            f"{T_MODEL_MORE} {len(c.get('fp_d', []))} {zh('\\u6761')}，"
            f"{T_MODEL_MISS} {len(c.get('fn_d', []))} {zh('\\u6761')}。",
            f"- {T_MOD}：{T_CONSIST} {len(c.get('tp_m', []))} {zh('\\u6761')}，"
            f"{T_MODEL_MORE} {len(c.get('fp_m', []))} {zh('\\u6761')}，"
            f"{T_MODEL_MISS} {len(c.get('fn_m', []))} {zh('\\u6761')}。",
        ]
    )
    if c.get("fp_d"):
        md.append(f"- {T_DIRECT}{T_MODEL_MORE}：")
        md.extend([f"- {fmt_pair(x)}" for x in c["fp_d"]])
    if c.get("fn_d"):
        md.append(f"- {T_DIRECT}{T_MODEL_MISS}：")
        md.extend([f"- {fmt_pair(x)}" for x in c["fn_d"]])
    if c.get("fp_m"):
        md.append(f"- {T_MOD}{T_MODEL_MORE}：")
        md.extend([f"- {fmt_mod(x)}" for x in c["fp_m"]])
    if c.get("fn_m"):
        md.append(f"- {T_MOD}{T_MODEL_MISS}：")
        md.extend([f"- {fmt_mod(x)}" for x in c["fn_m"]])

MD_OUT.write_text("\n".join(md), encoding="utf-8")

css = (
    "body{font-family:'Microsoft YaHei','PingFang SC',Arial,sans-serif;line-height:1.6;margin:24px;"
    "background:#f6f7fb;color:#111}"
    ".card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin:14px 0}"
    "h1,h2,h3{margin:.5em 0}.muted{color:#666}ul{margin:8px 0 8px 20px}"
)
html_parts = [
    "<!doctype html><html lang='zh-CN'><head><meta charset='UTF-8'>",
    "<meta name='viewport' content='width=device-width, initial-scale=1'>",
    f"<title>{html.escape(T_TITLE)}</title><style>{css}</style></head><body>",
    f"<h1>{html.escape(T_TITLE)}</h1>",
    f"<p class='muted'>{html.escape(T_SUB)}</p>",
    "<div class='card'>",
    f"<h2>{html.escape(T_TOTAL)}</h2>",
    (
        f"<p>{html.escape(T_DIRECT)}：{zh('\\u6a21\\u578b')} {summary.get('glm_direct', 0)} "
        f"{zh('\\u6761')}；{zh('\\u4eba\\u5de5')} {summary.get('gt_direct', 0)} {zh('\\u6761')}；"
        f"{html.escape(T_CONSIST)} {summary.get('tp_direct', 0)} {zh('\\u6761')}。</p>"
    ),
    (
        f"<p>{html.escape(T_MOD)}：{zh('\\u6a21\\u578b')} {summary.get('glm_mod', 0)} "
        f"{zh('\\u6761')}；{zh('\\u4eba\\u5de5')} {summary.get('gt_mod', 0)} {zh('\\u6761')}；"
        f"{html.escape(T_CONSIST)} {summary.get('tp_mod', 0)} {zh('\\u6761')}。</p>"
    ),
    "</div>",
]

for it in items:
    doi = html.escape(it.get("doi", ""))
    g = it.get("gt", {})
    p = it.get("glm", {})
    c = it.get("cmp", {})
    html_parts.extend(
        [
            "<div class='card'>",
            f"<h2>{doi}</h2>",
            f"<p class='muted'>{html.escape(T_FILE)}：{html.escape(p.get('file', ''))}</p>",
            f"<h3>1) {html.escape(T_MODEL_EXTRACT)}</h3><ul>",
            f"<li>{html.escape(T_DIRECT)}：{len(p.get('direct', []))} {zh('\\u6761')}</li>",
        ]
    )
    for r in p.get("direct", []):
        html_parts.append(
            f"<li>{html.escape(r.get('source', ''))} -> {html.escape(r.get('target', ''))}"
            f"（{html.escape(r.get('direction', ''))}，{html.escape(r.get('verification', ''))}）</li>"
        )
    html_parts.append(f"<li>{html.escape(T_MOD)}：{len(p.get('moderations', []))} {zh('\\u6761')}</li>")
    for r in p.get("moderations", []):
        html_parts.append(
            f"<li>{html.escape(r.get('moderator', ''))} {zh('\\u8c03\\u8282')} "
            f"{html.escape(r.get('moderated_effects', ''))}"
            f"（{html.escape(r.get('direction', ''))}，{html.escape(r.get('verification', ''))}）</li>"
        )
    html_parts.append("</ul>")
    html_parts.append(f"<h3>2) {html.escape(T_GT)}</h3><ul>")
    html_parts.append(f"<li>{html.escape(T_DIRECT)}：{len(g.get('direct_effects', []))} {zh('\\u6761')}</li>")
    for r in g.get("direct_effects", []):
        html_parts.append(
            f"<li>{html.escape(r.get('source', ''))} -> {html.escape(r.get('target', ''))}"
            f"（{html.escape(r.get('direction', ''))}，{html.escape(r.get('verification', ''))}）</li>"
        )
    html_parts.append(f"<li>{html.escape(T_MOD)}：{len(g.get('moderations', []))} {zh('\\u6761')}</li>")
    for r in g.get("moderations", []):
        rel = "; ".join(
            [f"{x.get('source', '')} -> {x.get('target', '')}" for x in (r.get("moderated_effects") or [])]
        )
        html_parts.append(
            f"<li>{html.escape(r.get('moderator', ''))} {zh('\\u8c03\\u8282')} {html.escape(rel)}"
            f"（{html.escape(r.get('direction', ''))}，{html.escape(r.get('verification', ''))}）</li>"
        )
    html_parts.append("</ul>")
    html_parts.append(f"<h3>3) {html.escape(T_DIFF)}</h3><ul>")
    html_parts.append(
        f"<li>{html.escape(T_DIRECT)}：{html.escape(T_CONSIST)} {len(c.get('tp_d', []))} {zh('\\u6761')}，"
        f"{html.escape(T_MODEL_MORE)} {len(c.get('fp_d', []))} {zh('\\u6761')}，"
        f"{html.escape(T_MODEL_MISS)} {len(c.get('fn_d', []))} {zh('\\u6761')}。</li>"
    )
    html_parts.append(
        f"<li>{html.escape(T_MOD)}：{html.escape(T_CONSIST)} {len(c.get('tp_m', []))} {zh('\\u6761')}，"
        f"{html.escape(T_MODEL_MORE)} {len(c.get('fp_m', []))} {zh('\\u6761')}，"
        f"{html.escape(T_MODEL_MISS)} {len(c.get('fn_m', []))} {zh('\\u6761')}。</li>"
    )
    html_parts.append("</ul></div>")

html_parts.append("</body></html>")
HTML_OUT.write_text("".join(html_parts), encoding="utf-8")

print(MD_OUT)
print(HTML_OUT)
