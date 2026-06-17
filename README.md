# Site Crawler

A web-based crawler that extracts structured data from websites and exports it to Excel. Define the fields you want (title, price, SKU, etc.), point it at a site, and get a spreadsheet back.

---

## What it does

- Crawls pages via **Spider mode** (follows internal links from a starting URL) or **Sitemap mode** (reads a sitemap.xml, .txt, or .csv of URLs)
- Extracts **custom fields** you define from each page — using JSON-LD, meta tags, DOM attributes, and visible text
- Automatically falls back through four fetch tiers when pages block bots (direct → ScrapingBee premium → ScrapingBee stealth → Claude API)
- Exports results to a formatted **.xlsx file**

---

## Setup

**Install dependencies**

```bash
pip install crawl4ai aiohttp lxml flask openpyxl beautifulsoup4 pandas
```

**Set environment variables** (copy `.env` and fill in your keys)

```env
SCRAPINGBEE_API_KEY=your_key_here   # optional — enables anti-bot fallback
CLAUDE_API_URL=http://...           # optional — enables AI extraction fallback
```

**Run the server**

```bash
python server.py
```

Then open [http://localhost:5000](http://localhost:5000).

---

## How to use

### 1. Choose a crawl mode

| Mode | When to use |
|------|-------------|
| **Spider** | You have a starting URL and want to follow links across the site |
| **Sitemap** | You have a sitemap.xml URL, or a .txt/.csv file of URLs to crawl |

### 2. Add fields

Click **Add Field** to define what data to pull from each page. Each field has:

- **Name** — what you want to call the column (e.g. `price`, `sku`, `itemurl`)
- **Type** — string, number, etc.
- **Required** — if checked, records missing this field will be dropped

Common field names are recognized automatically and mapped to schema.org equivalents (e.g. `imageurl` → finds the `image` property in JSON-LD).

### 3. Configure the job

- **Spider mode**: Enter the starting URL and set a page limit
- **Sitemap mode**: Enter a sitemap URL or upload a .xml / .txt / .csv file

Give your job an output filename, then click **Start**.

### 4. Download results

Progress is shown in real time. When the job finishes, download the `.xlsx` file. Each row is one page, with your custom fields extracted into a `records` JSON column (one object per product/listing found on the page).

---

## Fetch strategy

The crawler tries four methods in order, using the next only if the previous is blocked:

1. **Direct crawl** via Crawl4AI (free, fast)
2. **ScrapingBee premium proxy** (~5 credits/request)
3. **ScrapingBee stealth proxy** (~75 credits/request)
4. **Claude API** — AI-based extraction, also handles PDFs

Tiers 2–4 require the corresponding keys in your environment.

---

## Deployment

The repo includes config for Railway (`railway.json`, `nixpacks.toml`) and Docker (`Dockerfile`). Set `SCRAPINGBEE_API_KEY` and `CLAUDE_API_URL` as environment variables in your deployment — the UI key fields are ignored when server-side env vars are present.

```bash
# Docker
docker build -t site-crawler .
docker run -p 5000:5000 \
  -e SCRAPINGBEE_API_KEY=... \
  -e CLAUDE_API_URL=... \
  site-crawler
```
