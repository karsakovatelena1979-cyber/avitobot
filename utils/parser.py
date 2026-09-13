"""Парсинг Авито через ScraperAPI."""

import asyncio
import base64
import json
import logging
import random
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse, urlencode

import httpx
from bs4 import BeautifulSoup

from config import MAX_PHOTOS, PARSER_TIMEOUT, SCRAPER_API_KEY

logger = logging.getLogger(__name__)


class AvitoBlockedError(Exception):
    pass


class AvitoNotFoundError(Exception):
    pass


@dataclass
class AvitoListing:
    title: str = ""
    price: str = ""
    description: str = ""
    category: str = ""
    condition: str = ""
    photos: list[str] = field(default_factory=list)
    photos_base64: list[str] = field(default_factory=list)
    url: str = ""


def is_avito_url(text: str) -> bool:
    return bool(re.search(r"https?://(www\.)?avito\.ru/", text.strip()))


def _clean_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _scraper_url(target_url: str) -> str:
    params = urlencode({
        "api_key": SCRAPER_API_KEY,
        "url": target_url,
        "country_code": "ru",
        "device_type": "desktop",
        "keep_headers": "true",
        "render": "true",
    })
    return f"https://api.scraperapi.com/?{params}"


async def _download_photo(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return base64.b64encode(resp.content).decode("utf-8")
    except Exception as e:
        logger.warning("Фото не скачалось: %s", e)
        return None


def _parse_html(soup: BeautifulSoup, url: str) -> AvitoListing:
    listing = AvitoListing(url=url)

    title_tag = (
        soup.find("h1", {"data-marker": "item-view/title-info"}) or
        soup.find("h1", class_=re.compile(r"title", re.I)) or
        soup.find("h1")
    )
    if title_tag:
        listing.title = title_tag.get_text(strip=True)

    price_tag = soup.find("span", {"data-marker": "item-view/item-price"})
    if not price_tag:
        price_tag = soup.find("span", class_=re.compile(r"price", re.I))
    if price_tag:
        listing.price = price_tag.get_text(strip=True)
    if not listing.price:
        meta = soup.find("meta", {"itemprop": "price"})
        if meta:
            listing.price = meta.get("content", "") + " ₽"

    desc_tag = (
        soup.find("div", {"data-marker": "item-view/item-description"}) or
        soup.find("div", class_=re.compile(r"description", re.I))
    )
    if desc_tag:
        listing.description = desc_tag.get_text(strip=True)

    breadcrumbs = soup.find_all("a", {"data-marker": "breadcrumbs/link"})
    if breadcrumbs:
        listing.category = " / ".join(bc.get_text(strip=True) for bc in breadcrumbs)

    for param in soup.find_all("li", {"data-marker": "item-view/item-params-list/item"}):
        text = param.get_text(strip=True)
        if "состояние" in text.lower():
            listing.condition = text
            break

    photo_urls = []
    og_img = soup.find("meta", {"property": "og:image"})
    if og_img and og_img.get("content"):
        photo_urls.append(og_img["content"])

    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict):
                images = data.get("image", [])
                if isinstance(images, str):
                    images = [images]
                for img_url in images:
                    if img_url not in photo_urls:
                        photo_urls.append(img_url)
                    if len(photo_urls) >= MAX_PHOTOS:
                        break
        except Exception:
            continue

    listing.photos = photo_urls[:MAX_PHOTOS]
    return listing


async def parse_avito(url: str) -> AvitoListing:
    clean_url = _clean_url(url)
    scraper_url = _scraper_url(clean_url)
    logger.info("Запрос через ScraperAPI: %s", clean_url)

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(scraper_url)

            if resp.status_code == 404:
                raise AvitoNotFoundError("404 Not Found")
            if resp.status_code != 200:
                raise AvitoBlockedError(f"ScraperAPI вернул {resp.status_code}")

            soup = BeautifulSoup(resp.text, "lxml")

            if "captcha" in resp.text.lower() and "Подтвердите" in resp.text:
                raise AvitoBlockedError("Капча даже через ScraperAPI")

            listing = _parse_html(soup, url)

            if not listing.title:
                logger.error("Пустой заголовок, html: %s", resp.text[:500])
                raise AvitoBlockedError("Не удалось распарсить страницу")

            for photo_url in listing.photos:
                b64 = await _download_photo(photo_url)
                if b64:
                    listing.photos_base64.append(b64)

            logger.info("Парсинг OK: %s | %s | фото: %d",
                       listing.title[:40], listing.price, len(listing.photos_base64))
            return listing

    except (AvitoBlockedError, AvitoNotFoundError):
        raise
    except Exception as e:
        logger.exception("Ошибка ScraperAPI: %s", e)
        raise AvitoBlockedError(str(e)) from e
