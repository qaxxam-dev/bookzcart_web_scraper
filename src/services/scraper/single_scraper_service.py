import unicodedata
from bs4 import BeautifulSoup
from decimal import Decimal, InvalidOperation

# Pre-build the set of stock CSS classes → status mappings for O(1) lookup
_STOCK_CLASS_MAP = {
    "addtocart": "in_stock",
    "outofstock": "out_of_stock",
    "comingsoon": "coming_soon",
    "preorder": "pre_order",
    "soleorder": "sole_order",
}

# Pre-build the metadata field → CSS class mappings
_FIELD_MAPPINGS = (
    ("author", "author"),
    ("translator", "translator"),
    ("publisher", "publisher"),
    ("no_of_pages", "pages"),
    ("language", "language"),
    ("published_on", "publishedon"),
    ("book_format", "book_format"),
    ("category", "category"),
    ("subject", "subject"),
)


NO_IMAGE_URL = "https://s3.ap-south-1.amazonaws.com/storage.commonfolks.in/images/no-image.jpg"


class SingleScraperService:

    def extract_product_info(self, html_content: str, img_low: str | None = None):
        if img_low and img_low == NO_IMAGE_URL:
            return {}

        # lxml is ~2-5x faster than html.parser (already in requirements.txt)
        soup = BeautifulSoup(html_content, "lxml")

        detail_page = soup.find(class_="detailpage")
        if not detail_page:
            return {}

        result = {}

        # ---------------- Stock (single-pass lookup) ----------------

        # Grab all <span> tags once, check class against the map
        stock_status = None
        for span in detail_page.find_all("span", limit=20):
            span_classes = span.get("class", [])
            for cls in span_classes:
                if cls in _STOCK_CLASS_MAP:
                    stock_status = _STOCK_CLASS_MAP[cls]
                    break
            if stock_status:
                break

        result["stock_info"] = {"status": stock_status} if stock_status else {}

        # ---------------- Title ----------------

        title_elem = detail_page.find("h1", itemprop="name")
        if title_elem:
            title = title_elem.get_text(strip=True)
            title = title.replace(" (Pre-Order)", "")

            # Clean hidden control marks and normalize to modern UTF-8 Unicode
            title = unicodedata.normalize("NFKC", title)
            title = "".join(ch for ch in title if unicodedata.category(ch) != "Cc")

            result["title"] = title

        # ---------------- Subtitle ----------------

        subtitle = detail_page.find("h3", class_="subtitle")
        if subtitle:
            result["sub_title"] = subtitle.get_text(strip=True)

        # ---------------- Price ----------------

        cost = soup.find("h5", class_="cost")
        if cost:
            regular = cost.find("font", class_="mrp")
            sale = cost.find("span", itemprop="price")

            price_text = None
            if regular:
                price_text = regular.get_text(strip=True)
            elif sale:
                price_text = sale.get_text(strip=True)

            if price_text:
                price_text = price_text.replace("₹", "").replace(",", "").strip()
                try:
                    result["regular_price"] = float(Decimal(price_text))
                except (InvalidOperation, ValueError):
                    pass  # Skip malformed prices silently

        # ---------------- Metadata fields (h6 extraction) ----------------

        # Cache all h6 elements once instead of 9 separate DOM traversals
        h6_by_class = {}
        for h6 in detail_page.find_all("h6"):
            h6_classes = h6.get("class", [])
            for cls in h6_classes:
                h6_by_class[cls] = h6

        for key, css_class in _FIELD_MAPPINGS:
            h6 = h6_by_class.get(css_class)
            if h6:
                text = h6.get_text(strip=True)
                if ":" in text:
                    text = text.split(":", 1)[1].strip()
                if text:
                    result[key] = text

        # ---------------- Description ----------------

        description = detail_page.find("div", itemprop="description")
        if description:
            result["description"] = description.get_text(strip=True)

        # ---------------- Images ----------------

        img = detail_page.select_one("div.product_image_main img")
        if img:
            img_src = img.get("src")
            if img_src == NO_IMAGE_URL:
                return {}
            result["img_url_high"] = img_src

        if img_low:
            if img_low == NO_IMAGE_URL:
                return {}
            result["img_url_low"] = img_low
        elif result.get("img_url_high"):
            img_low_calc = result["img_url_high"].replace("images_full", "images")
            if img_low_calc == NO_IMAGE_URL:
                return {}
            result["img_url_low"] = img_low_calc

        if result.get("img_url_high") == NO_IMAGE_URL or result.get("img_url_low") == NO_IMAGE_URL:
            return {}

        return result
