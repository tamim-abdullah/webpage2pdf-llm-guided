import base64
import json
import os
import pathlib
import re
import time
from urllib.parse import urljoin

import requests
import trafilatura
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
from flask_cors import CORS
from openai import OpenAI
from playwright.sync_api import sync_playwright

OUT_DIR = pathlib.Path(__file__).parent / "output"
OUT_DIR.mkdir(exist_ok=True)

MODEL = "llama-3.3-70b-versatile"
BATCH = 15

groq = OpenAI(
    api_key=os.environ["GROQ_API_KEY"],
    base_url="https://api.groq.com/openai/v1",
)

PROMPT = """You select which sections of an article belong in a focused PDF.

TOPIC: {topic}

KEEP sections with substantive content on the topic: analysis, technical
detail, data, procedures, indicators of compromise, code, diagrams, tables.
DROP: author bios, related-article lists, newsletter or subscribe prompts,
comments, publisher marketing, social links, unrelated subjects.

If unsure, KEEP.

Return only JSON: {{"decisions":[{{"id":"u0","d":"KEEP"}}]}}

SECTIONS:
{sections}"""

PRINT_CSS = """
@page { size: A4; margin: 18mm 15mm; }
body { font: 11pt/1.55 Georgia, serif; color: #111; max-width: 46em; }
h1, h2, h3 { font-family: system-ui, sans-serif; line-height: 1.25; break-after: avoid; }
h1 { font-size: 19pt; } h2 { font-size: 14pt; } h3 { font-size: 12pt; }
p { orphans: 3; widows: 3; }
figure, table, pre, img, blockquote { break-inside: avoid; }
img { max-width: 100%; height: auto; }
pre { white-space: pre-wrap; font-size: 9pt; background: #f5f5f5;
      padding: 8px; border-radius: 3px; }
code { font-size: 9.5pt; }
table { border-collapse: collapse; width: 100%; font-size: 9.5pt; }
th, td { border: 1px solid #bbb; padding: 4px 6px; text-align: left; }
"""


def extract(html, url):
    """Strip boilerplate, keep images and tables."""
    out = trafilatura.extract(
        html,
        url=url,
        output_format="html",
        include_images=True,
        include_tables=True,
        include_formatting=True,
        include_links=False,
        favor_recall=True,
    )
    if not out:
        return None
    soup = BeautifulSoup(out, "html.parser")
    # Some trafilatura versions emit <graphic> instead of <img>.
    for g in soup.find_all("graphic"):
        img = soup.new_tag("img")
        img["src"] = g.get("src", "")
        g.replace_with(img)
    return soup


def chunk(soup):
    """Group top-level elements into sections at heading boundaries."""
    root = soup.body or soup
    units, cur = [], None
    for el in root.find_all(recursive=False):
        is_head = el.name in ("h1", "h2", "h3")
        if cur is None or is_head:
            if cur is not None:
                units.append(cur)
            cur = {
                "id": f"u{len(units)}",
                "heading": el.get_text(strip=True) if is_head else "",
                "els": [],
            }
        cur["els"].append(el)
    if cur is not None:
        units.append(cur)
    return units


def digest(units):
    """Compact view of each section. This is the only thing the model sees."""
    rows = []
    for u in units:
        text = " ".join(e.get_text(" ", strip=True) for e in u["els"])
        tags = set()
        for e in u["els"]:
            tags.add(e.name)
            tags.update(c.name for c in e.find_all())
        rows.append({
            "id": u["id"],
            "h": u["heading"],
            "w": len(text.split()),
            "has": [t for t in ("img", "pre", "code", "table") if t in tags],
            "txt": text[:280],
        })
    return rows


def classify(rows, topic):
    """Ask the model for KEEP/DROP ids. Returns [] on failure (fail open)."""
    decisions = []
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        msg = PROMPT.format(topic=topic, sections=json.dumps(batch, ensure_ascii=False))
        for attempt in range(3):
            try:
                r = groq.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": msg}],
                    response_format={"type": "json_object"},
                    temperature=0,
                )
                decisions += json.loads(r.choices[0].message.content).get("decisions", [])
                break
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    time.sleep(5 * 2 ** attempt)
                else:
                    print(f"classify failed: {e}")
                    break
    return decisions


def apply_decisions(units, decisions):
    """Missing id -> KEEP. Over-aggressive result -> keep everything."""
    verdict = {d["id"]: d["d"] for d in decisions if isinstance(d, dict) and "id" in d}
    kept = [u for u in units if verdict.get(u["id"], "KEEP") == "KEEP"]
    if not kept or len(kept) < len(units) * 0.3:
        return units
    return kept


def inline_images(units, base_url):
    """Convert every image to a data URI, drop the ones that fail."""
    headers = {"User-Agent": "Mozilla/5.0", "Referer": base_url}
    for u in units:
        for el in u["els"]:
            imgs = [el] if el.name == "img" else el.find_all("img")
            for img in imgs:
                src = img.get("src", "")
                if not src or src.startswith("data:"):
                    continue
                try:
                    r = requests.get(urljoin(base_url, src), headers=headers, timeout=10)
                    r.raise_for_status()
                    mime = r.headers.get("content-type", "image/png").split(";")[0]
                    b64 = base64.b64encode(r.content).decode()
                    img["src"] = f"data:{mime};base64,{b64}"
                    for attr in ("srcset", "data-src", "loading"):
                        img.attrs.pop(attr, None)
                except Exception:
                    img.decompose()


def render_pdf(units, title, url, path):
    body = "".join(str(e) for u in units for e in u["els"])
    html = (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title><style>{PRINT_CSS}</style></head>"
        f"<body><h1>{title}</h1>"
        f"<p style='font-size:8.5pt;color:#666'>{url}</p>"
        f"{body}</body></html>"
    )
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="load")
        page.pdf(path=str(path), format="A4", print_background=True)
        browser.close()


app = Flask(__name__)
CORS(app)


@app.post("/clip")
def clip():
    data = request.get_json(force=True)
    url = data.get("url", "")
    title = data.get("title", "page")
    topic = data.get("topic") or title

    soup = extract(data["html"], url)
    if soup is None:
        return jsonify({"error": "Could not extract article content"}), 422

    units = chunk(soup)
    if not units:
        return jsonify({"error": "No content found"}), 422

    kept = apply_decisions(units, classify(digest(units), topic))
    inline_images(kept, url)

    name = re.sub(r"[^\w\s-]", "", title).strip()[:60] or "clip"
    name = re.sub(r"\s+", "_", name)
    path = OUT_DIR / f"{name}.pdf"
    render_pdf(kept, title, url, path)

    return jsonify({"file": str(path), "kept": len(kept), "total": len(units)})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, threaded=False)
