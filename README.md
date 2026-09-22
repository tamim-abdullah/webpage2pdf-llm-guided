# WebClip PDF

Clips the current browser page, drops sections unrelated to a topic, saves a PDF.

The LLM only returns section IDs to keep or drop. It never writes any text, so
every word, image, and code block in the PDF comes from the original page.

```
extension/     Chrome extension (captures page HTML)
server/        Python server (extract -> classify -> filter -> PDF)
server/output/ Generated PDFs
```

## 1. Get a Groq API key

Sign up at https://console.groq.com — no credit card required.
Create a key under **API Keys**.

## 2. Set up the server

```bash
cd server
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

Set the key:

```bash
export GROQ_API_KEY="gsk_..."      # Windows PowerShell: $env:GROQ_API_KEY="gsk_..."
```

Run it:

```bash
python app.py
```

Leave this terminal open. It serves on `http://localhost:8000`.

## 3. Load the extension

1. Open `chrome://extensions`
2. Turn on **Developer mode** (top right)
3. Click **Load unpacked**
4. Select the `extension/` folder

## 4. Use it

1. Open any article
2. Click the extension icon
3. Type a topic (or leave blank to use the page title)
4. Click **Generate PDF**

The PDF lands in `server/output/`. The popup shows the path and how many
sections were kept.

## Notes

- The server must be running before you click the button.
- Free tier limits are 30 requests/minute and 6,000 tokens/minute, shared
  across your whole Groq organization. A long page uses 1–3 requests.
- If the model fails or the API is unreachable, every section is kept and you
  still get a complete PDF.
- Section headings and 280-character previews are sent to Groq. Full page text
  and images are not. Avoid using this on confidential or authenticated pages.
- To use a smaller/faster model, change `MODEL` at the top of `app.py` to
  `llama-3.1-8b-instant`.
