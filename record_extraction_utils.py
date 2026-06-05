
import json
import re
from bs4 import BeautifulSoup
from lxml import html as lhtml

def parse_jsonld(html):
    """
    Parse JSON-LD once and return all structured objects.
    Handles:
    - multiple script blocks
    - lists
    - invalid blocks safely
    """

    jsonld_blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.S | re.I
    )
    write_log("parse_jsonld", f"Found {len(jsonld_blocks)} JSON-LD script blocks")

    data_list = []

    for block in jsonld_blocks:
        try:
            data = json.loads(block)
            data_list.append(data)
        except Exception:
            continue

    return data_list

def chunk_html(html):
    """
    Returns one chunk per product/listing.
    Tries both JSON-LD and DOM strategies, returning whichever finds more products.
    """

    try:
        doc = lhtml.fromstring(html)
    except Exception:
        return [html]

    # --------------------------------
    # Strategy 1: JSON-LD Products
    # --------------------------------

    product_chunks = []

    jsonld_data = parse_jsonld(html)

    for data in jsonld_data:
        products = extract_products_from_jsonld(data)

        for product in products:
            product_chunks.append(
                json.dumps(product, ensure_ascii=False)
            )

    if product_chunks:
        write_log("chunk_html", f"Found {len(product_chunks)} product chunks using JSON-LD strategy")

    # --------------------------------
    # Strategy 2: Repeating DOM nodes (BeautifulSoup)
    # --------------------------------

    soup = BeautifulSoup(html, "html.parser")

    selectors = [
        ("article",             lambda s: s.find_all("article")),
        ("class~product",       lambda s: s.find_all(class_=re.compile(r"product", re.I))),
        ("class~card",          lambda s: s.find_all(class_=re.compile(r"\bcard\b", re.I))),
        ("class~tile",          lambda s: s.find_all(class_=re.compile(r"\btile\b", re.I))),
        ("data-testid~product", lambda s: s.find_all(attrs={"data-testid": re.compile(r"product", re.I)})),
    ]

    dom_chunks = []

    for label, finder in selectors:
        tags = finder(soup)

        if len(tags) >= 2:
            # Keep the depth level with the most matches — this finds the individual
            # product cards rather than their outermost container.
            from collections import Counter
            tag_depths = [(t, len(list(t.parents))) for t in tags]
            depth_counts = Counter(d for _, d in tag_depths)
            best_depth = min(d for d, count in depth_counts.items() if count >= 2)
            tags = [t for t, d in tag_depths if d == best_depth]

            chunks = [str(tag) for tag in tags]
            chunks = [c for c in chunks if score_chunk(c) > 0]

            if chunks:
                write_log("chunk_html", f"Found {len(chunks)} product chunks using selector: {label}")
                for c in chunks:
                    write_log("extracted_chunks", c)
                dom_chunks = chunks
                break

    # Merge both: JSON-LD first (richer, structured), then DOM chunks for products
    # not covered by JSON-LD. Deduplicate by SKU to avoid double-counting the
    # products that appear in both.
    if product_chunks or dom_chunks:
        # Collect SKUs already covered by JSON-LD chunks
        jsonld_skus = set()
        for chunk in product_chunks:
            try:
                obj = json.loads(chunk)
                sku = obj.get("sku") or obj.get("SKU") or obj.get("productID")
                if sku:
                    jsonld_skus.add(str(sku).strip().lower())
            except Exception:
                pass

        # Only add DOM chunks that don't duplicate a JSON-LD SKU
        merged = list(product_chunks)
        for chunk in dom_chunks:
            if jsonld_skus:
                chunk_lower = chunk.lower()
                if any(sku in chunk_lower for sku in jsonld_skus):
                    continue
            merged.append(chunk)

        write_log("chunk_html", f"Merged {len(product_chunks)} JSON-LD + {len(dom_chunks)} DOM = {len(merged)} chunks after dedup")
        return merged

    return [html]

def extract_products_from_jsonld(obj):
    """
    Recursively find Product objects.
    """

    products = []

    if isinstance(obj, dict):

        if obj.get("@type") == "Product":
            products.append(obj)

        for value in obj.values():
            products.extend(extract_products_from_jsonld(value))

    elif isinstance(obj, list):

        for item in obj:
            products.extend(extract_products_from_jsonld(item))

    return products

def score_chunk(chunk):
    """
    Estimate whether chunk contains product data.
    """

    lower = chunk.lower()

    score = 0

    indicators = [
        "price",
        "sku",
        "brand",
        "product",
        "offers",
        "availability",
        "$",
        "add to cart",
        "buy now"
    ]

    for indicator in indicators:
        if indicator in lower:
            score += 1

    return score

def find_key_recursive(obj, target_key):
    """
    Recursively search dictionaries/lists for a key.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():

            if key.lower() == target_key:
                return value

            found = find_key_recursive(value, target_key)
            if found not in (None, "", [], {}):
                return found

    elif isinstance(obj, list):
        for item in obj:
            found = find_key_recursive(item, target_key)
            if found not in (None, "", [], {}):
                return found

    return None


def search_jsonld(parsed_jsonld, field_name):
    """
    Look for field in already-parsed JSON-LD objects.
    """

    field_name_lower = field_name.lower()

    def search(obj):
        if isinstance(obj, dict):

            for k, v in obj.items():

                if k.lower() == field_name_lower:
                    if v not in (None, "", [], {}):
                        return v

                result = search(v)
                if result not in (None, "", [], {}):
                    return result

        elif isinstance(obj, list):

            for item in obj:
                result = search(item)
                if result not in (None, "", [], {}):
                    return result

        return None

    for obj in parsed_jsonld:
        result = search(obj)
        if result not in (None, "", [], {}):
            return result

    return ""


def search_meta(html, field_name):
    """
    Search meta tags.
    """

    patterns = [
        rf'<meta[^>]+name=["\']{re.escape(field_name)}["\'][^>]+content=["\'](.*?)["\']',
        rf'<meta[^>]+property=["\']{re.escape(field_name)}["\'][^>]+content=["\'](.*?)["\']',
        rf'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']{re.escape(field_name)}["\']',
        rf'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']{re.escape(field_name)}["\']',
    ]

    for pattern in patterns:
        m = re.search(pattern, html, re.I | re.S)
        if m:
            return m.group(1).strip()

    return ""


def search_attributes(html, field_name):
    """
    Search elements with matching itemprop, id, name, or data-* attributes.
    """

    try:
        doc = lhtml.fromstring(html)

        xpaths = [
            f'//*[@itemprop="{field_name}"]',
            f'//*[@id="{field_name}"]',
            f'//*[@name="{field_name}"]',
            f'//*[@data-field="{field_name}"]',
            f'//*[@data-testid="{field_name}"]',
        ]

        for xpath in xpaths:
            matches = doc.xpath(xpath)

            for el in matches:
                text = " ".join(el.xpath(".//text()")).strip()

                if text:
                    return text

                value = el.get("content") or el.get("value")
                if value:
                    return value

    except Exception:
        pass

    return ""


def search_visible_text(html, field_name):
    """
    Look for patterns like:
    Brand: Nike
    Color: Red
    SKU - ABC123
    """

    try:
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)

        patterns = [
            rf'{re.escape(field_name)}\s*:\s*([^|,\n\r]+)',
            rf'{re.escape(field_name)}\s*-\s*([^|,\n\r]+)',
        ]

        for pattern in patterns:
            m = re.search(pattern, text, re.I)

            if m:
                return m.group(1).strip()

    except Exception:
        pass

    return ""


def search_css_class(html, aliases):
    """
    Find elements whose class attribute contains any of the alias terms.
    Handles BEM-style naming like product-card__title, product-price, etc.
    Returns the text content of the first match.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
        for alias in aliases:
            matches = soup.find_all(class_=re.compile(alias, re.I))
            for el in matches:
                text = el.get_text(separator=" ").strip()
                if text:
                    return text
    except Exception:
        pass
    return ""


# Maps user-defined field names to the JSON-LD/schema.org keys they correspond to.
# Each entry lists all names to try, most-specific first.
FIELD_ALIASES = {
    "title":       ["name", "title"],
    "name":        ["name", "title"],
    "price":       ["price", "lowprice"],
    "image":       ["image", "img","photo", "thumbnail"],
    "image_url":   ["image", "img", "photo", "thumbnail"],
    "imageurl":   ["image", "img", "photo", "thumbnail"],
    "description": ["description", "abstract", "descr"],
    "brand":       ["brand", "manufacturer", "publisher"],
    "sku":         ["sku", "productid", "mpn", "gtin13", "gtin12"],
    "url":         ["url", "link"],
    "rating":      ["ratingvalue", "rating"],
    "review_count":["reviewcount", "ratingcount"],
    "availability":["availability", "itemcondition"],
    "color":       ["color", "colour"],
    "category":    ["category", "breadcrumb"],
}


def extract_custom_field(field, html, parsed_jsonld=None):
    """
    Attempts several strategies to find a field.
    """

    field_name = field["name"].lower()
    aliases = FIELD_ALIASES.get(field_name, [field_name])

    # 0. JSON-LD — either passed in, or auto-detected when the chunk itself is JSON
    #    (chunk_html Strategy 1 returns json.dumps(product) strings, not HTML)
    if parsed_jsonld is None:
        try:
            obj = json.loads(html)
            if isinstance(obj, dict):
                parsed_jsonld = [obj]
        except (json.JSONDecodeError, ValueError):
            pass

    if parsed_jsonld:
        for alias in aliases:
            value = search_jsonld(parsed_jsonld, alias)
            if value not in (None, "", [], {}):
                return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    # 2. Meta tags — try aliases then original name
    for name in aliases + [field_name]:
        value = search_meta(html, name)
        if value:
            return value

    # 3. itemprop/id/name attributes
    for name in aliases + [field_name]:
        value = search_attributes(html, name)
        if value:
            return value

    # 4. Visible text — use original field name (human-readable label on page)
    value = search_visible_text(html, field_name)
    if value:
        return value

    # 5. CSS class-based — find elements whose class contains the field name or alias
    #    Handles BEM naming like product-card__title, product-price, etc.
    value = search_css_class(html, aliases + [field_name])
    if value:
        return value

    # 6. Image src — for image fields, grab the first <img> src in the chunk
    if field_name in ("image", "image_url", "img"):
        m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.I)
        if m:
            return m.group(1)

    write_log("extract_custom_field", f"Could not find value for field '{field['name']}' in chunk {html}.")
    return ""

def find_missing_fields(row: dict, custom_fields: list[dict]) -> list[dict]:
    missing_fields = []
    seen = set()

    required_fields = [
        field
        for field in custom_fields
        if field.get("required")
    ]

    for record in row.get("records", []):

        for field in required_fields:

            value = record.get(field["name"])

            if value in (None, "", [], {}):

                field_name = field["name"]

                if field_name not in seen:
                    missing_fields.append(field)
                    seen.add(field_name)

    return missing_fields

def extract_records_from_page(html: str, custom_fields: list[dict]) -> str:
    """Extract multiple records from the page HTML and return as JSON string."""
    record = {}
    for field in custom_fields:
        record[field["name"]] = extract_custom_field(field, html)
    return json.dumps(record, ensure_ascii=False)

from datetime import datetime

def write_log(job_id: str, message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    line = f"[{timestamp}] {message}\n"

    with open(f"logs/{job_id}.log", "a", encoding="utf-8") as f:
        f.write(line)