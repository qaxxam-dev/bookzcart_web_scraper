from typing import Dict
from bs4 import BeautifulSoup


class TaxonomyScraperService:

    def _extract_detailed_from_container(self, container) -> Dict:
        result = {"taxonomise": [], "total_taxonomise": 0}
        if not container:
            return result

        h2_headers = container.find_all("h2")

        # Find the first alphabetical header (A, B, C, etc.) after Featured
        start_index = -1
        for i, h2 in enumerate(h2_headers):
            header_text = h2.get_text(strip=True)
            # Skip Featured
            if header_text == "Featured":
                continue
            # Found first alphabetical header
            if len(header_text) == 1 and header_text.isalpha():
                start_index = i
                break

        if start_index != -1:
            starting_h2 = h2_headers[start_index]
            found_start = False
        else:
            starting_h2 = h2_headers[0] if h2_headers else None
            found_start = True if not starting_h2 else False

        all_item_divs = container.find_all("div", class_="item")

        for item_div in all_item_divs:
            if not found_start:
                if starting_h2 and item_div.find_previous("h2") == starting_h2:
                    found_start = True
                else:
                    continue

            a_tag = item_div.find("a", href=True)
            if not a_tag and item_div.parent and item_div.parent.name == "a":
                a_tag = item_div.parent

            href = a_tag.get("href", "") if a_tag else ""
            slug = href.rstrip("/").split("/")[-1] if href else ""

            h4 = item_div.find("h4")
            if h4:
                font_tag = h4.find("font")
                tamil_name = font_tag.get_text(strip=True) if font_tag else ""
                if font_tag:
                    font_tag.extract()
                english_name = h4.get_text(strip=True)

                taxonomy_data = {
                    "english_name": english_name,
                    "tamil_name": tamil_name,
                    "slug": slug,
                }

                result["taxonomise"].append(taxonomy_data)

        result["total_taxonomise"] = len(result["taxonomise"])
        return result

    def extract_taxonomise_authors_detailed(self, html_content: str) -> Dict:
        soup = BeautifulSoup(html_content, "lxml")
        container = soup.find("div", class_="author_list_page")
        return self._extract_detailed_from_container(container)

    def extract_taxonomise_publishers_detailed(self, html_content: str) -> Dict:
        soup = BeautifulSoup(html_content, "lxml")
        container = soup.find("div", class_="publisher_list_page")
        return self._extract_detailed_from_container(container)