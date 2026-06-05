PRODUCT_SCHEMA = {
    "name": None,
    "price": None,
    "currency": None,
    "brand": None,
    "sku": None,
    "availability": None,
    "image": None,
    "source": None,   # jsonld | dom
    "confidence": 0.0
}
def parse_jsonld(html):
    import json, re

    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.S | re.I
    )

    data = []
    for b in blocks:
        try:
            data.append(json.loads(b))
        except Exception:
            continue

    return data
def expand_jsonld(obj):
    results = []

    if isinstance(obj, dict):

        if "@graph" in obj and isinstance(obj["@graph"], list):
            for item in obj["@graph"]:
                results.extend(expand_jsonld(item))
        else:
            results.append(obj)

    elif isinstance(obj, list):
        for item in obj:
            results.extend(expand_jsonld(item))

    return results

def extract_products(obj):
    products = []

    if isinstance(obj, dict):

        if obj.get("@type") == "Product":
            products.append(obj)

        for v in obj.values():
            products.extend(extract_products(v))

    elif isinstance(obj, list):
        for item in obj:
            products.extend(extract_products(item))

    return products

def normalize_product(obj):
    product = {
        "name": obj.get("name"),
        "price": None,
        "currency": None,
        "brand": None,
        "sku": obj.get("sku"),
        "availability": None,
        "image": None,
        "source": "jsonld",
        "confidence": 0.9
    }

    # image
    img = obj.get("image")
    if isinstance(img, list):
        product["image"] = img[0]
    else:
        product["image"] = img

    # brand
    brand = obj.get("brand")
    if isinstance(brand, dict):
        product["brand"] = brand.get("name")
    else:
        product["brand"] = brand

    # offers (most important part)
    offers = obj.get("offers")

    if isinstance(offers, dict):
        product["price"] = offers.get("price")
        product["currency"] = offers.get("priceCurrency")
        product["availability"] = offers.get("availability")

    elif isinstance(offers, list) and offers:
        first = offers[0]
        if isinstance(first, dict):
            product["price"] = first.get("price")
            product["currency"] = first.get("priceCurrency")
            product["availability"] = first.get("availability")

    return product

from lxml import html as lhtml

def extract_dom_fields(node):
    def text(xpath):
        res = node.xpath(xpath)
        return res[0].strip() if res else None

    return {
        "name": text(".//h1//text()") or text(".//*[contains(@class,'title')]//text()"),
        "price": text(".//*[contains(@class,'price')]//text()"),
        "image": node.xpath(".//img/@src")[0] if node.xpath(".//img/@src") else None,
        "source": "dom",
        "confidence": 0.5
    }

def merge_product(base, extra):
    for k, v in extra.items():
        if base.get(k) in (None, "", [], {}):
            base[k] = v
    return base

def extract_products_from_html(html):
    try:
        doc = lhtml.fromstring(html)
    except Exception:
        return []

    products = []

    # ----------------------------
    # 1. JSON-LD FIRST (PRIMARY)
    # ----------------------------
    jsonld_blocks = parse_jsonld(html)

    for block in jsonld_blocks:
        for obj in expand_jsonld(block):

            for p in extract_products(obj):

                normalized = normalize_product(p)
                products.append(normalized)

    # ----------------------------
    # 2. DOM fallback ONLY if needed
    # ----------------------------
    if not products:

        nodes = doc.xpath(
            "//article | "
            "//*[contains(@class,'product')] | "
            "//*[contains(@data-testid,'product')]"
        )

        for node in nodes:

            dom_data = extract_dom_fields(node)

            if dom_data.get("name"):
                products.append(dom_data)

    return products

def score_product(p):
    score = 0

    if p.get("name"): score += 2
    if p.get("price"): score += 3
    if p.get("brand"): score += 1
    if p.get("image"): score += 1
    if p.get("sku"): score += 1

    return score / 8