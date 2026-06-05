
import json
import re
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

        # safer logging (avoid index crash)
        for i in range(min(5, len(product_chunks))):
            write_log("chunk_html", f"Sample chunk {i}: {product_chunks[i][:500]}")

        return product_chunks

    # --------------------------------
    # Strategy 2: Repeating DOM nodes
    # --------------------------------

    xpaths = [
        "//article",
        "//*[contains(@class,'product')]",
        "//*[contains(@class,'product-card')]",
        "//*[contains(@class,'product-tile')]",
        "//*[contains(@class,'card')]",
        "//*[contains(@class,'tile')]",
        "//*[contains(@data-testid,'product')]",
    ]

    for xpath in xpaths:

        nodes = doc.xpath(xpath)

        if len(nodes) >= 2:

            chunks = []

            for node in nodes:
                try:
                    chunks.append(
                        lhtml.tostring(node, encoding="unicode")
                    )
                except Exception:
                    pass

            if chunks:
                write_log("chunk_html", f"Found {len(chunks)} product chunks using XPath: {xpath}")
                return chunks

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




def extract_custom_field(field, html, parsed_jsonld=None):
    """
    Attempts several strategies to find a field.
    """

    field_name = field["name"].lower()

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
        value = search_jsonld(parsed_jsonld, field_name)
        if value not in (None, "", [], {}):
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    # 2. Meta tags
    value = search_meta(html, field_name)
    if value:
        return value

    # 3. itemprop/id/name attributes
    value = search_attributes(html, field_name)
    if value:
        return value

    # 4. Visible text
    value = search_visible_text(html, field_name)
    if value:
        return value

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