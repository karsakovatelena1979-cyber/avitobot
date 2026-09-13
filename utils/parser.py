"""Парсинг Авито через несколько методов с fallback."""

import asyncio
import base64
import json
import logging
import random
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

import httpx
from bs4 import BeautifulSoup

from config import MAX_PHOTOS, PARSER_TIMEOUT

logger = logging.getLogger(__name__)

MOBILE_USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 13; SM-A536B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 12; Redmi Note 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
]


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
    """Убираем UTM и лишние параметры."""
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _extract_item_id(url: str) -> str | None:
    """Извлекаем ID объявления из URL."""
    match = re.search(r"_(\d{7,12})(?:\?|$|/)", url)
    return match.group(1) if match else None


async def _try_api(item_id: str) -> AvitoListing | None:
    """Пробуем неофициальный API Авито."""
    api_url = f"https://api.avito.ru/core/v1/items/{item_id}/"
    headers = {
        "User-Agent": random.choice(MOBILE_USER_AGENTS),
        "Accept": "application/json",
        "Origin": "https://www.avito.ru",
        "Referer": "https://www.avito.ru/",
    }
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(api_url, headers=headers)
            if resp.status_code != 200:
                logger.info("API вернул %d", resp.status_code)
                return None
            data = resp.json()
            listing = AvitoListing()
            listing.title = data.get("title", "")
            listing.price = str(data.get("priceDetailed", {}).get("value", "")) + " ₽"
            listing.description = data.get("description", "")
            listing.category = data.get("category", {}).get("name", "")
            images = data.get("images", [])
            listing.photos = [img.get("864x864", img.get("640x480", "")) for img in images[:MAX_PHOTOS]]
            return listing
    except Exception as e:
        logger.warning("API метод не сработал: %s", e)
        return None


async def _try_mobile_web(url: str) -> AvitoListing | None:
    """Парсим мобильную версию — она легче защищена."""
    mobile_url = url.replace("www.avito.ru", "m.avito.ru")
    ua = random.choice(MOBILE_USER_AGENTS)
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Referer": "https://m.avito.ru/",
    }
    try:
        await asyncio.sleep(random.uniform(3, 7))
        async with httpx.AsyncClient(
            headers=headers,
            timeout=PARSER_TIMEOUT,
            follow_redirects=True,
        ) as client:
            resp = await client.get(mobile_url)
            if resp.status_code in (429, 403):
                logger.warning("Мобильная версия вернула %d", resp.status_code)
                return None
            if resp.status_code == 404:
                raise AvitoNotFoundError("404")
            resp.raise_for_status()

            if "captcha" in resp.text.lower() and "Подтвердите" in resp.text:
                return None

            soup = BeautifulSoup(resp.text, "lxml")
            listing = AvitoListing(url=url)

            h1 = soup.find("h1")
            if h1:
                listing.title = h1.get_text(strip=True)

            for sel in [
                {"data-marker": "item-view/item-price"},
                {"class": re.compile(r"price")},
            ]:
                tag = soup.find("span", sel)
                if tag:
                    listing.price = tag.get_text(strip=True)
                    break
            if not listing.price:
                meta = soup.find("meta", {"itemprop": "price"})
                if meta:
                    listing.price = meta.get("content", "")

            for sel in [
                {"data-marker": "item-view/item-description"},
                {"class": re.compile(r"description")},
            ]:
                tag = soup.find("div", sel)
                if tag:
                    listing.description = tag.get_text(strip=True)
                    break

            og_img = soup.find("meta", {"property": "og:image"})
            if og_img and og_img.get("content"):
                listing.photos.append(og_img["content"])

            if listing.title:
                return listing
            return None
    except AvitoNotFoundError:
        raise
    except Exception as e:
        logger.warning("Мобильный парсинг не сработал: %s", e)
        return None


async def _download_photo(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return base64.b64encode(resp.content).decode("utf-8")
    except Exception as e:
        logger.warning("Фото не скачалось: %s", e)
        return None


async def parse_avito(url: str) -> AvitoListing:
    """Парсит объявление: сначала API, потом мобильная версия."""
    clean_url = _clean_url(url)
    item_id = _extract_item_id(url)

    # Метод 1: неофициальный API
    if item_id:
        logger.info("Пробуем API метод, item_id=%s", item_id)
        listing = await _try_api(item_id)
        if listing and listing.title:
            listing.url = url
            for photo_url in listing.photos:
                if photo_url:
                    b64 = await _download_photo(photo_url)
                    if b64:
                        listing.photos_base64.append(b64)
            logger.info("API метод сработал: %s", listing.title[:50])
            return listing

    # Метод 2: мобильная версия
    logger.info("Пробуем мобильную версию")
    listing = await _try_mobile_web(clean_url)
    if listing and listing.title:
        for photo_url in listing.photos:
            if photo_url:
                b64 = await _download_photo(photo_url)
                if b64:
                    listing.photos_base64.append(b64)
        logger.info("Мобильный метод сработал: %s", listing.title[:50])
        return listing

    # Всё заблокировано
    raise AvitoBlockedError("Авито блокирует запросы с этого сервера. Попробуй скинуть текст объявления вручную.")
