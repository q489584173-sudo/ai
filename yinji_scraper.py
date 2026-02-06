#!/usr/bin/env python3
"""Scrape Yinji article pages.

Extracts title, design company, category, downloads page images,
organizes files, and generates an Excel index.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from openpyxl import Workbook


@dataclass
class ArticleData:
    url: str
    title: str
    design_firm: str
    category: str
    image_paths: List[Path]


ILLEGAL_PATH_CHARS = re.compile(r"[\\/:*?\"<>|]")


def sanitize_segment(text: str) -> str:
    cleaned = ILLEGAL_PATH_CHARS.sub(" ", text).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "unknown"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def request_page(url: str, timeout: int = 20) -> str:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text


def parse_text(soup: BeautifulSoup, selectors: Iterable[str]) -> Optional[str]:
    for selector in selectors:
        node = soup.select_one(selector)
        if node and node.get_text(strip=True):
            return node.get_text(strip=True)
    return None


def parse_article(url: str) -> Tuple[str, str, str, List[str]]:
    html = request_page(url)
    soup = BeautifulSoup(html, "html.parser")

    title = parse_text(
        soup,
        [
            "h1",
            ".post-title",
            ".article-title",
            ".entry-title",
        ],
    )
    if not title:
        title = "unknown-title"

    design_firm = parse_text(
        soup,
        [
            ".info .company",
            ".design-company",
            ".designer",
            ".post-meta .company",
        ],
    )
    if not design_firm:
        design_firm = "unknown-firm"

    category = parse_text(
        soup,
        [
            ".category",
            ".categories a",
            ".post-categories a",
            ".post-meta .category",
        ],
    )
    if not category:
        category = "unknown-category"

    image_urls: List[str] = []
    for img in soup.select("img"):
        src = img.get("data-src") or img.get("data-original") or img.get("src")
        if not src:
            continue
        image_urls.append(urljoin(url, src))

    return title, design_firm, category, image_urls


def download_image(url: str, output_dir: Path, index: int) -> Optional[Path]:
    try:
        resp = requests.get(url, stream=True, timeout=20)
        resp.raise_for_status()
    except requests.RequestException:
        return None

    parsed = urlparse(url)
    ext = Path(parsed.path).suffix or ".jpg"
    filename = f"image_{index:03d}{ext}"
    output_path = output_dir / filename

    with output_path.open("wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

    return output_path


def scrape_article(url: str, output_root: Path) -> ArticleData:
    title, design_firm, category, image_urls = parse_article(url)
    safe_title = sanitize_segment(title)
    safe_firm = sanitize_segment(design_firm)
    safe_category = sanitize_segment(category)

    folder_name = f"{safe_title}__{safe_firm}"
    output_dir = output_root / safe_category / folder_name
    ensure_dir(output_dir)

    image_paths: List[Path] = []
    for index, img_url in enumerate(image_urls, start=1):
        path = download_image(img_url, output_dir, index)
        if path:
            image_paths.append(path)

    return ArticleData(
        url=url,
        title=title,
        design_firm=design_firm,
        category=category,
        image_paths=image_paths,
    )


def build_excel(records: List[ArticleData], output_path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "index"
    ws.append(["URL", "Title", "Design Firm", "Category", "Image Count", "Folder"])

    for record in records:
        folder = ""
        if record.image_paths:
            folder = str(record.image_paths[0].parent)
        ws.append(
            [
                record.url,
                record.title,
                record.design_firm,
                record.category,
                len(record.image_paths),
                folder,
            ]
        )

    wb.save(output_path)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Yinji article pages.")
    parser.add_argument("urls", nargs="+", help="Article page URL(s).")
    parser.add_argument(
        "--output",
        default="output",
        help="Root output directory for downloads.",
    )
    parser.add_argument(
        "--excel",
        default=None,
        help="Excel file path. Default: output/index_YYYYMMDD_HHMMSS.xlsx",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    output_root = Path(args.output)
    ensure_dir(output_root)

    records: List[ArticleData] = []
    for url in args.urls:
        record = scrape_article(url, output_root)
        records.append(record)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    excel_path = Path(args.excel) if args.excel else output_root / f"index_{timestamp}.xlsx"
    build_excel(records, excel_path)

    print(f"Saved Excel index to {excel_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
