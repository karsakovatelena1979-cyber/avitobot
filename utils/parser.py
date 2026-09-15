"""Парсинг Авито через curl_cffi + резидентные прокси Webshare."""

import asyncio
import base64
import json
import logging
import random
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse

from curl_cffi import requests as cf_requests
from bs4 import BeautifulSoup

from config import MAX_PHOTOS, PARSER_TIMEOUT

logger = logging.getLogger(__name__)

PROXIES = [
    "31.59.20.176:6754:eugfttlg:vtxc4mbymjp0",
    "45.38.107.97:6014:eugfttlg:vtxc4mbymjp0",
    "198.105.121.200:6462:eugfttlg:vtxc4mbymjp0",
    "64.137.96.74:6641:eugfttlg:vtxc4mbymjp0",
    "198.23.243.226:6361:eugfttlg:vtxc4mbymjp0",
    "38.154.185.97:6370:eugfttlg:vtxc4mbymjp0",
    "84.247.60.125:6095:eugfttlg:vtxc4mbymjp0",
    "142.111.67.146:5611:eugfttlg:vtxc4mbymjp0",
    "191.96.254.138:6185:eugfttlg:vtxc4mbymjp0",
    "31.58.9.4:6077:eugfttlg:vtxc4mbymjp0",
]


def _get_proxy_url() -> str:
    p = random.choice(PROXIES)
    host, port, user, pwd = p.split(":")
    return f"http://{user}:{pwd}@{host}:{port}"


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


def _parse_html(html: str, url: str) -> AvitoListing:
    soup = BeautifulSoup(html, "lxml")
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


def _fetch_sync(url: str, proxy: str) -> cf_requests.Response:
    return cf_requests.get(
        url,
        impersonate="chrome120",
        proxies={"https": proxy},
        timeout=30,
        headers={
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.avito.ru/",
        },
    )


def _fetch_photo_sync(url: str) -> str | None:
    try:
        resp = cf_requests.get(url, impersonate="chrome120", timeout=10)
        resp.raise_for_status()
        return base64.b64encode(resp.content).decode("utf-8")
    except Exception as e:
        logger.warning("Фото не скачалось: %s", e)
        return None


async def parse_avito(url: str) -> AvitoListing:
    clean_url = _clean_url(url)
    last_error = None

    for attempt in range(1, 4):
        proxy = _get_proxy_url()
        logger.info("Попытка %d, прокси: %s", attempt, proxy.split("@")[1])
        await asyncio.sleep(random.uniform(1, 3))

        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, _fetch_sync, clean_url, proxy)

            if resp.status_code == 404:
                raise AvitoNotFoundError("404")

            if resp.status_code in (403, 429):
                logger.warning("Статус %d на попытке %d", resp.status_code, attempt)
                last_error = f"Статус {resp.status_code}"
                continue

            if resp.status_code != 200:
                last_error = f"HTTP {resp.status_code}"
                continue

            html = resp.text
            if "captcha" in html.lower() and "Подтвердите" in html:
                logger.warning("Капча на попытке %d", attempt)
                last_error = "капча"
                continue

            listing = _parse_html(html, url)

            if not listing.title:
                logger.warning("Пустой заголовок на попытке %d", attempt)
                last_error = "пустой заголовок"
                continue

            for photo_url in listing.photos:
                b64 = await loop.run_in_executor(None, _fetch_photo_sync, photo_url)
                if b64:
                    listing.photos_base64.append(b64)

            logger.info("OK: %s | %s | фото: %d",
                       listing.title[:40], listing.price, len(listing.photos_base64))
            return listing

        except AvitoNotFoundError:
            raise
        except AvitoBlockedError:
            raise
        except Exception as e:
            logger.warning("Ошибка попытки %d: %s", attempt, e)
            last_error = str(e)
            continue

    raise AvitoBlockedError(f"Не удалось после 3 попыток. Причина: {last_error}")
