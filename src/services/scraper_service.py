import httpx
import unicodedata
from fastapi import HTTPException
from bs4 import BeautifulSoup
from decimal import Decimal


class ScraperService:
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    @staticmethod
    def http_get_content(url: str):
        try:
            response = httpx.get(
                url=url,
                timeout=30.0,
                headers=ScraperService.HEADERS,
                follow_redirects=True,
            )
            response.raise_for_status()

            return response.status_code, response.text

        except httpx.RequestError as e:
            raise HTTPException(status_code=400, detail=f"Error fetching URL: {e}")

    @staticmethod
    def extract_product_info(html_content: str):
        soup = BeautifulSoup(html_content, "html.parser")

        result = {}
        detail_page = soup.find(class_="detailpage")

        if not detail_page:
            return result

        # ---------------- Stock ----------------

        stock_info = {}

        if detail_page.find("span", class_="addtocart"):
            stock_info["status"] = "in_stock"
        elif detail_page.find("span", class_="outofstock"):
            stock_info["status"] = "out_of_stock"
        elif detail_page.find("span", class_="comingsoon"):
            stock_info["status"] = "coming_soon"
        elif detail_page.find("span", class_="preorder"):
            stock_info["status"] = "pre_order"
        elif detail_page.find("span", class_="soleorder"):
            stock_info["status"] = "sole_order"

        result["stock_info"] = stock_info

        # ---------------- Title ----------------

        title_elem = detail_page.find("h1", itemprop="name")
        if title_elem:
            title = title_elem.get_text(strip=True)
            title = title.replace(" (Pre-Order)", "")

            # Clean hidden control marks and normalize to modern UTF-8 Unicode
            title = unicodedata.normalize("NFKC", title)
            title = "".join(ch for ch in title if unicodedata.category(ch) != "Cc")

            result["title"] = title

            # Debug
        print("\nTITLE:", repr(title))
        print("CODEPOINTS:", [hex(ord(c)) for c in title])

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

                result["regular_price"] = float(Decimal(price_text))

        # ---------------- Helper ----------------

        def extract_h6(css_class):
            elem = detail_page.find("h6", class_=css_class)
            if elem:
                text = elem.get_text(strip=True)
                if ":" in text:
                    return text.split(":", 1)[1].strip()
                return text
            return None

        mappings = {
            "author": ("author"),
            "translator": ("translator"),
            "publisher": ("publisher"),
            "no_of_pages": ("pages"),
            "language": ("language"),
            "published_on": ("publishedon"),
            "book_format": ("book_format"),
            "category": ("category"),
            "subject": ("subject"),
        }

        for key, (cls) in mappings.items():
            value = extract_h6(cls)
            if value:
                result[key] = value

        description = detail_page.find("div", itemprop="description")

        if description:
            result["description"] = description.get_text(strip=True)

        return result
