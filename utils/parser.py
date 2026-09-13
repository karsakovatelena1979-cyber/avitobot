"""Парсинг объявлений Авито: httpx + BeautifulSoup.

- Ротация User-Agent (10+ штук)
- Случайная задержка 1-3 секунды
- Парсинг: заголовок, цена, описание, категория, состояние, фото
- Обработка блокировок (403/captcha)
"""

import asyncio
import base64
import logging
import random
import re
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

from config import (
    MAX_PHOTOS,
    PARSER_DELAY_MAX,
    PARSER_DELAY_MIN,
    PARSER_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Резервный список UA (на случай если fake-useragent не сработает)
FALLBACK_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 OPR/110.0.0.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
]

try:
    _ua = UserAgent()
except Exception:
    _ua = None


def _get_user_agent() -> str:
    """Возвращает случайный User-Agent."""
    if _ua:
        try:
            return _ua.random
        except Exception:
            pass
    return random.choice(FALLBACK_USER_AGENTS)


def _get_headers() -> dict:
    return {
        "User-Agent": _get_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.avito.ru/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Cache-Control": "max-age=0",
    }


class AvitoBlockedError(Exception):
    """Авито заблокировал запрос (403/captcha)."""
    pass


class AvitoNotFoundError(Exception):
    """Объявление не найдено (404)."""
    pass


@dataclass
class AvitoListing:
    """Распарсенное объявление."""
    title: str = ""
    price: str = ""
    description: str = ""
    category: str = ""
    condition: str = ""
    photos: list[str] = field(default_factory=list)  # URL фото
    photos_base64: list[str] = field(default_factory=list)  # base64-encoded bytes
    url: str = ""


def is_avito_url(text: str) -> bool:
    """Проверяет что текст — ссылка на Авито."""
    pattern = r"https?://(www\.)?avito\.ru/"
    return bool(re.search(pattern, text.strip()))


async def _download_photo(client: httpx.AsyncClient, url: str) -> str | None:
    """Скачивает фото и возвращает base64. None при ошибке."""
    try:
        resp = await client.get(url, timeout=PARSER_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        return base64.b64encode(resp.content).decode("utf-8")
    except Exception as e:
        logger.warning("Не удалось скачать фото %s: %s", url, e)
        return None


async def parse_avito(url: str) -> AvitoListing:
    """Парсит объявление Авито. Бросает AvitoBlockedError / AvitoNotFoundError."""
    # Случайная задержка 1-3 секунды (имитация человека)
    delay = random.uniform(PARSER_DELAY_MIN, PARSER_DELAY_MAX)
    logger.info("Задержка перед запросом: %.1f сек", delay)
    await asyncio.sleep(delay)

    listing = AvitoListing(url=url)
    headers = _get_headers()

    async with httpx.AsyncClient(
        headers=headers,
        timeout=PARSER_TIMEOUT,
        follow_redirects=True,
    ) as client:
        resp = await client.get(url)

        if resp.status_code == 403:
            logger.error("Авито вернул 403 — блокировка/капча")
            raise AvitoBlockedError("403 Forbidden")
        if resp.status_code == 404:
            logger.error("Объявление не найдено: %s", url)
            raise AvitoNotFoundError("404 Not Found")
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        # Проверка на капчу в HTML
        if "captcha" in resp.text.lower() or "smartcaptcha" in resp.text.lower():
            if "Подтвердите, что вы не робот" in resp.text:
                logger.error("Обнаружена капча в HTML")
                raise AvitoBlockedError("captcha detected")

        # === ЗАГОЛОВОК ===
        title_tag = (
            soup.find("h1", {"data-marker": "item-view/title-info"}) or
            soup.find("h1", class_=re.compile(r"title")) or
            soup.find("h1")
        )
        if title_tag:
            listing.title = title_tag.get_text(strip=True)

        # === ЦЕННА ===
        price_tag = (
            soup.find("span", {"data-marker": "item-view/item-price"}) or
            soup.find("span", class_=re.compile(r"price")) or
            soup.find("meta", {"itemprop": "price"})
        )
        if price_tag:
            if price_tag.name == "meta":
                listing.price = price_tag.get("content", "")
            else:
                listing.price = price_tag.get_text(strip=True)
        if not listing.price:
            meta_price = soup.find("meta", {"itemprop": "price"})
            if meta_price:
                listing.price = meta_price.get("content", "")

        # === ОПИСАНИЕ ===
        desc_tag = (
            soup.find("div", {"data-marker": "item-view/item-description"}) or
            soup.find("div", class_=re.compile(r"item-description")) or
            soup.find("p", {"data-marker": "item-view/item-description"})
        )
        if desc_tag:
            listing.description = desc_tag.get_text(strip=True)

        # === КАТЕГОРИЯ ===
        breadcrumbs = soup.find_all("a", {"data-marker": "breadcrumbs/link"})
        if breadcrumbs:
            listing.category = " / ".join(bc.get_text(strip=True) for bc in breadcrumbs)
        else:
            cat_meta = soup.find("meta", {"property": "og:type"})
            # fallback: берём из URL
            url_parts = url.split("/")
            if len(url_parts) > 4:
                listing.category = url_parts[3].replace("_", " ")

        # === СОСТОЯНИЕ ===
        params = soup.find_all("li", {"data-marker": "item-view/item-params-list/item"})
        for param in params:
            text = param.get_text(strip=True)
            if "состояние" in text.lower():
                listing.condition = text
                break
        if not listing.condition:
            # Попробуем найти в параметрах
            for li in soup.find_all("li"):
                t = li.get_text(strip=True)
                if re.search(r"(новый|б/у|бу|хорошее|отличное|требует)", t, re.I):
                    listing.condition = t
                    break

        # === ФОТО (первые 3) ===
        photo_urls = []
        # Метод 1: img теги с data-marker
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if src and ("avito" in src or src.startswith("http")):
                if any(x in src for x in [".jpg", ".jpeg", ".png", ".webp"]):
                    if src not in photo_urls:
                        photo_urls.append(src)
            if len(photo_urls) >= MAX_PHOTOS:
                break

        # Метод 2: meta og:image
        if len(photo_urls) < MAX_PHOTOS:
            og_img = soup.find("meta", {"property": "og:image"})
            if og_img and og_img.get("content"):
                src = og_img["content"]
                if src not in photo_urls:
                    photo_urls.append(src)

        # Метод 3: JSON-LD
        if len(photo_urls) < MAX_PHOTOS:
            for script in soup.find_all("script", {"type": "application/ld+json"}):
                try:
                    import json
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

        # Скачиваем фото как bytes → base64
        for photo_url in listing.photos:
            b64 = await _download_photo(client, photo_url)
            if b64:
                listing.photos_base64.append(b64)

    logger.info(
        "Парсинг завершён: title=%s, price=%s, photos=%d",
        listing.title[:50] if listing.title else "?",
        listing.price,
        len(listing.photos_base64),
    )
    return listing
