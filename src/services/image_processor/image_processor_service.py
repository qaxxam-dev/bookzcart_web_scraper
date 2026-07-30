import os
import re
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

import httpx
from PIL import Image
from pathlib import Path

# Pre-compile the filename validation regex
_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class ImageProcessorService:

    BASE_DIR = Path(__file__).resolve().parent
    DEFAULT_OUTPUT_DIR = BASE_DIR / "output"

    def __init__(self):
        # Persistent HTTP client with connection pooling for image downloads
        self._client = httpx.Client(timeout=30.0, follow_redirects=True)

    @staticmethod
    def _download_image_bytes(client: httpx.Client, url: str) -> bytes:
        """Download image and return raw bytes (no disk I/O)."""
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content

    def process_watermark(
        self,
        front_url: str,
        back_url: str,
        file_name: str,
        cut_width_pct: float = 20,
        cut_height_pct: float = 20,
        output_dir: str = DEFAULT_OUTPUT_DIR,
        webp_quality: int = 99,
    ) -> str:
        # --- Validate file name ---
        if not _FILENAME_RE.match(file_name):
            raise ValueError("Invalid file name format")

        os.makedirs(output_dir, exist_ok=True)

        # --- Download both images concurrently, directly into memory ---
        with ThreadPoolExecutor(max_workers=2) as pool:
            front_future = pool.submit(
                self._download_image_bytes, self._client, front_url
            )
            back_future = pool.submit(
                self._download_image_bytes, self._client, back_url
            )

        front_bytes = front_future.result()
        back_bytes = back_future.result()

        # --- Open from memory (no temp files, no disk cleanup needed) ---
        front_img = Image.open(BytesIO(front_bytes)).convert("RGBA")
        back_img = Image.open(BytesIO(back_bytes)).convert("RGBA")

        W, H = front_img.size  # canvas size = front image size

        # --- Clamp percentages ---
        cut_width_pct = max(0.0, min(100.0, cut_width_pct))
        cut_height_pct = max(0.0, min(100.0, cut_height_pct))

        # --- Percent -> pixels, bounded ---
        cut_w = int((cut_width_pct / 100.0) * W)
        cut_h = int((cut_height_pct / 100.0) * H)
        cut_w = max(0, min(W, cut_w))
        cut_h = max(0, min(H, cut_h))

        # --- Build output canvas ---
        out = Image.new("RGBA", (W, H), (0, 0, 0, 0))

        # 1) back scaled to canvas, drawn first
        back_resized = back_img.resize((W, H), Image.LANCZOS)
        out.alpha_composite(back_resized, (0, 0))

        # 2) front drawn on top
        out.alpha_composite(front_img, (0, 0))

        # 3) bottom-left cut window revealing back image again
        if cut_w > 0 and cut_h > 0:
            scale_x = back_img.width / W
            scale_y = back_img.height / H
            src_w = round(cut_w * scale_x)
            src_h = round(cut_h * scale_y)
            src_x = 0
            src_y = back_img.height - src_h

            region_src = back_img.crop((src_x, src_y, src_x + src_w, src_y + src_h))
            region = region_src.resize((cut_w, cut_h), Image.LANCZOS)

            dst_x, dst_y = 0, H - cut_h
            out.alpha_composite(region, (dst_x, dst_y))

        # --- Save as compressed WEBP ---
        output_path = os.path.join(output_dir, f"{file_name}.webp")
        out.save(output_path, format="WEBP", quality=webp_quality, method=6)

        return output_path

    def delete_output_image(self, image_path: str | Path) -> None:
        """Delete a generated output image if it exists."""
        try:
            path = Path(image_path)
            if path.exists():
                path.unlink()
        except Exception as exc:
            print(f"Failed to delete image {image_path}: {exc}")
