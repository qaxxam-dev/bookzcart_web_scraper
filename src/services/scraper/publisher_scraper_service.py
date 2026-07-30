from typing import Dict
from bs4 import BeautifulSoup


class PublisherScraperService:

    def extract_publisher_list_url(self, html_content: str) -> Dict:
        soup = BeautifulSoup(html_content, "lxml")

        select = soup.select_one("span.pageby select.pageselect")

        if not select:
            return {"list_url": [], "total_url": 0}

        urls = [option["value"] for option in select.find_all("option")]

        return {"list_url": [{"url": url} for url in urls], "total_url": len(urls)}
