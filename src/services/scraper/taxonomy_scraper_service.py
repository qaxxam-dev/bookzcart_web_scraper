from typing import Dict
from bs4 import BeautifulSoup


class TaxonomyScraperService:

    def extract_taxonomise_detailed(self, html_content: str) -> Dict:
        soup = BeautifulSoup(html_content, "lxml")
        result = {"taxonomise": [], "total_taxonomise": 0}

        taxonomy_container = soup.find("div", class_="author_list_page")

        if not taxonomy_container:
            return result

        # Find all h2 headers
        h2_headers = taxonomy_container.find_all("h2")

        # Find the first alphabetical header (A, B, C, etc.) after Featured
        start_index = -1
        for i, h2 in enumerate(h2_headers):
            header_text = h2.get_text(strip=True)
            # Skip Featured and any non-alphabetical single letters
            if header_text == "Featured":
                continue
            # Found first alphabetical header
            if len(header_text) == 1 and header_text.isalpha():
                start_index = i
                break

        if start_index == -1:
            return result

        # Get all items from the first alphabetical header onwards
        # Find all a tags that contain div.item
        all_items = taxonomy_container.find_all("a")

        # Find the first item after the starting h2
        starting_h2 = h2_headers[start_index]
        found_start = False

        for item in all_items:
            # Check if this item comes after the starting h2
            if not found_start:
                # Check if this is the starting h2 or after it
                if item.find_previous("h2") == starting_h2:
                    found_start = True
                else:
                    continue

            item_div = item.find("div", class_="item")
            if item_div:
                h4 = item_div.find("h4")
                if h4:
                    # Extract the href and get slug
                    href = item.get("href", "")
                    slug = href.split("/")[-1] if href else ""

                    # Extract name logic
                    contents = h4.contents
                    name_parts = []
                    for content in contents:
                        if isinstance(content, str):
                            if content.strip():
                                name_parts.append(content.strip())
                        elif content.name == "font":
                            name_parts.append(content.get_text(strip=True))

                    if len(name_parts) >= 2:
                        english_name = name_parts[0]
                        tamil_name = name_parts[1]
                    else:
                        text_parts = h4.get_text(separator="|", strip=True).split("|")
                        text_parts = [p.strip() for p in text_parts if p.strip()]
                        english_name = text_parts[0] if len(text_parts) > 0 else ""
                        tamil_name = text_parts[1] if len(text_parts) > 1 else ""

                    taxonomy_data = {
                        "english_name": english_name,
                        "tamil_name": tamil_name,
                        "slug": slug,  # Added slug field
                    }

                    result["taxonomise"].append(taxonomy_data)

        result["total_taxonomise"] = len(result["taxonomise"])
        return result
