from typing import Dict
from bs4 import BeautifulSoup


class ListScraperService:

    def extract_book_list_single_page(self, html_content: str) -> Dict:
        soup = BeautifulSoup(html_content, "lxml")
        result = {"books": [], "total_books": 0}

        book_container = soup.find("div", class_="productgrid")

        if not book_container:
            return result

        book_items = book_container.find_all("div", class_="item")

        for item in book_items:
            parent_link = item.find("a")
            if parent_link:
                url = parent_link.get("href")

            img = item.find("div", class_="product_list_img")

            if img:
                img_low = img.get("data-src")

            book_data = {
                "url": url,
                "img_low": img_low,
            }

            result["books"].append(book_data)

        result["total_books"] = len(result["books"])

        return result
