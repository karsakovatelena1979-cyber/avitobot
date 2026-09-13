"""Парсинг объявлений Авито: httpx + BeautifulSoup."""

import asyncio
import base64
import json
import logging
import random
import re
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup

from config import (
    MAX_PHOTOS,
    PARSER_DELAY_MAX,
    PARSER_DELAY_MIN,
    PARSER_TIMEOUT,
)

logger = logging.getLogger(__name__)

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
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]


def _get_headers(ua: str) -> dict:
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.avito.ru/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Ch-Ua": '"Chromium";v="125", "Google Chrome";v="125"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }


def _get_cookies() -> dict:
    """Базовые куки чтобы выглядеть как браузер."""
    return {
        "u": f"{random.randint(10000000, 99999999)}.{random.randint(1000000000, 9999999999)}",
        "v": "2",
        "abp": "1",
    }


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
    pattern = r"https?://(www\.)?avito\.ru/"
    return bool(re.search(pattern, text.strip()))


def _clean_url(url: str) -> str:
    """Убираем UTM-метки — они иногда триггерят защиту."""
    return url.split("?")[0]


async def _download_photo(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        resp = await client.get(url, timeout=10, follow_redirects=True)
        resp.raise_for_status()
        return base64.b64encode(resp.content).decode("utf-8")
    except Exception as e:
        logger.warning("Не удалось скачать фото %s: %s", url, e)
        return None


def _parse_html(soup: BeautifulSoup, url: str) -> AvitoListing:
    listing = AvitoListing(url=url)

    # Заголовок
    title_tag = (
        soup.find("h1", {"data-marker": "item-view/title-info"}) or
        soup.find("h1", class_=re.compile(r"title")) or
        soup.find("h1")
    )
    if title_tag:
        listing.title = title_tag.get_text(strip=True)

    # Цена
    price_tag = (
        soup.find("span", {"data-marker": "item-view/item-price"}) or
        soup.find("span", class_=re.compile(r"price"))
    )
    if price_tag:
        listing.price = price_tag.get_text(strip=True)
    if not listing.price:
        meta_price = soup.find("meta", {"itemprop": "price"})
        if meta_price:
            listing.price = meta_price.get("content", "")

    # Описание
    desc_tag = (
        soup.find("div", {"data-marker": "item-view/item-description"}) or
        soup.find("div", class_=re.compile(r"item-description"))
    )
    if desc_tag:
        listing.description = desc_tag.get_text(strip=True)

    # Категория из хлебных крошек
    breadcrumbs = soup.find_all("a", {"data-marker": "breadcrumbs/link"})
    if breadcrumbs:
        listing.category = " / ".join(bc.get_text(strip=True) for bc in breadcrumbs)
    elif len(url.split("/")) > 4:
        listing.category = url.split("/")[3].replace("_", " ")

    # Состояние
    for param in soup.find_all("li", {"data-marker": "item-view/item-params-list/item"}):
        text = param.get_text(strip=True)
        if "состояние" in text.lower():
            listing.condition = text
            break
    if not listing.condition:
        for li in soup.find_all("li"):
            t = li.get_text(strip=True)
            if re.search(r"(новый|б/у|бу|хорошее|отличное|требует)", t, re.I):
                listing.condition = t
                break

    # Фото
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

    if len(photo_urls) < MAX_PHOTOS:
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if src and any(x in src for x in [".jpg", ".jpeg", ".png", ".webp"]):
                if "avito" in src and src not in photo_urls:
                    photo_urls.append(src)
            if len(photo_urls) >= MAX_PHOTOS:
                break

    listing.photos = photo_urls[:MAX_PHOTOS]
    return listing


async def parse_avito(url: str) -> AvitoListing:
    """Парсит объявление. Retry до 3 раз при 429."""
    clean_url = _clean_url(url)
    max_retries = 3

    for attempt in range(1, max_retries + 1):
        ua = random.choice(FALLBACK_USER_AGENTS)
        delay = random.uniform(PARSER_DELAY_MIN * attempt, PARSER_DELAY_MAX * attempt)
        logger.info("Попытка %d/%d, задержка %.1f сек", attempt, max_retries, delay)
        await asyncio.sleep(delay)

        try:
            async with httpx.AsyncClient(
                headers=_get_headers(ua),
                cookies=_get_cookies(),
                timeout=PARSER_TIMEOUT,
                follow_redirects=True,
            ) as client:
                resp = await client.get(clean_url)

                if resp.status_code == 429:
                    wait = 10 * attempt
                    logger.warning("429 на попытке %d, жду %d сек", attempt, wait)
                    if attempt == max_retries:
                        raise AvitoBlockedError(f"429 после {max_retries} попыток")
                    await asyncio.sleep(wait)
                    continue

                if resp.status_code == 403:
                    raise AvitoBlockedError("403 Forbidden")

                if resp.status_code == 404:
                    raise AvitoNotFoundError("404 Not Found")

                resp.raise_for_status()

                if "captcha" in resp.text.lower() and "Подтвердите" in resp.text:
                    raise AvitoBlockedError("captcha detected")

                soup = BeautifulSoup(resp.text, "lxml")
                listing = _parse_html(soup, url)

                # Скачиваем фото
                for photo_url in listing.photos:
                    b64 = await _download_photo(client, photo_url)
                    if b64:
                        listing.photos_base64.append(b64)

                logger.info(
                    "Парсинг OK: title=%s, price=%s, photos=%d",
                    listing.title[:50] if listing.title else "?",
                    listing.price,
                    len(listing.photos_base64),
                )
                return listing

        except (AvitoBlockedError, AvitoNotFoundError):
            raise
        except Exception as e:
            logger.warning("Ошибка на попытке %d: %s", attempt, e)
            if attempt == max_retries:
                raise

    raise AvitoBlockedError("Все попытки исчерпаны")
