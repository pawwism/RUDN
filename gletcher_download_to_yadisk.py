#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Глетчер: сбор модулей с suraopt.ru и загрузка 3 картинок каждого модуля на Яндекс.Диск.

Что делает:
1) Заходит на https://suraopt.ru/kuhni/kollekcii/gletcher?page=N
2) Собирает ссылки на карточки модулей.
3) В каждой карточке берёт название и номер модели, например 2000000003030.
4) Формирует прямые ссылки:
   https://tech.sborno.ru/img/{model}_1.png
   https://tech.sborno.ru/img/{model}_2.png
   https://tech.sborno.ru/img/{model}_3.png
5) Загружает картинки на Яндекс.Диск с именами:
   <Название модуля>_1.png, <Название модуля>_2.png, <Название модуля>_3.png
6) Пишет modules_info_gletcher.txt и gletcher_result.csv для проверки.

Перед запуском:
- положи рядом файл token.txt с OAuth-токеном Яндекс.Диска
- установи зависимости:
  pip install requests beautifulsoup4

"""

import csv
import os
import re
import time
from datetime import datetime
from io import BytesIO
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup

# На некоторых Windows/Python requests не принимает сертификат suraopt.ru.
# Для сайта-источника отключаем проверку SSL, чтобы парсер не падал.
# Для Яндекс.Диска проверка SSL остаётся обычной.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
SSL_VERIFY_SOURCE_SITE = False

# ================== НАСТРОЙКИ ==================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(BASE_DIR, "token.txt")
LOG_FILE = os.path.join(BASE_DIR, "gletcher_log.txt")
MODULES_FILE = os.path.join(BASE_DIR, "modules_info_gletcher.txt")
RESULT_CSV = os.path.join(BASE_DIR, "gletcher_result.csv")

COLLECTION_NAME = "Глетчер"
COLLECTION_SLUG = "gletcher"
COLLECTION_URL = f"https://suraopt.ru/kuhni/kollekcii/{COLLECTION_SLUG}"
TECH_IMG_BASE = "https://tech.sborno.ru/img"

YANDEX_BASE_FOLDER = f"disk:/Фиды/{COLLECTION_NAME}"

MAX_PAGES = 300
EMPTY_PAGE_LIMIT = 3
PAGE_DELAY = 0.4
REQUEST_TIMEOUT = 25
# Selenium в этой версии не нужен — используется обычный requests

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

YANDEX_API = "https://cloud-api.yandex.net/v1/disk/resources"
YANDEX_UPLOAD_API = "https://cloud-api.yandex.net/v1/disk/resources/upload"
# =================================================


def log(message: str):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def clean_filename(text: str, max_len: int = 160) -> str:
    text = re.sub(r"[<>:\"/\\|?*]", "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("ё", "е").replace("Ё", "Е")
    return text[:max_len].rstrip(" ._")


def normalize_url(href: str) -> str | None:
    if not href:
        return None
    full = urljoin("https://suraopt.ru", href)
    # убираем лишний параметр page, если сайт его добавляет в карточку
    full = re.sub(r"([?&])page=\d+&?", r"\1", full).rstrip("?&")
    return full


def get_html(url: str) -> str:
    r = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT, verify=SSL_VERIFY_SOURCE_SITE)
    r.raise_for_status()
    return r.text


def extract_product_links_from_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if "product_id=" not in href:
            continue
        full = normalize_url(href)
        if full:
            links.append(full)
    return links


def collect_with_requests() -> list[str]:
    """Собирает карточки по страницам коллекции через обычные requests."""
    unique = {}
    empty_pages = 0

    for page in range(1, MAX_PAGES + 1):
        url = f"{COLLECTION_URL}?page={page}"
        try:
            html = get_html(url)
        except Exception as e:
            log(f"⚠️ Не удалось открыть страницу {page}: {e}")
            empty_pages += 1
            if empty_pages >= EMPTY_PAGE_LIMIT:
                break
            continue

        links = extract_product_links_from_html(html)
        log(f"Страница {page}: найдено ссылок {len(links)}")

        if not links:
            empty_pages += 1
            if empty_pages >= EMPTY_PAGE_LIMIT:
                log(f"Пустых страниц подряд: {EMPTY_PAGE_LIMIT}. Останавливаюсь.")
                break
        else:
            empty_pages = 0

        for link in links:
            m = re.search(r"product_id=(\d+)", link)
            key = m.group(1) if m else link
            unique[key] = link

        time.sleep(PAGE_DELAY)

    return list(unique.values())



def extract_title_and_model(product_url: str) -> tuple[str, str]:
    """Из карточки товара достаёт название и номер модели."""
    html = get_html(product_url)
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    h1 = soup.select_one("h1")
    if h1:
        title = h1.get_text(" ", strip=True)

    if not title:
        # часто на сайте название дублируется в meta og:title
        og = soup.select_one('meta[property="og:title"]')
        if og and og.get("content"):
            title = og["content"].strip()

    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)

    page_text = soup.get_text(" ", strip=True)

    # Главный вариант по скрину: "Модель: 2000000003030"
    model = ""
    patterns = [
        r"Модель[:\s]*([0-9]{10,15})",
        r"Артикул[:\s]*([0-9]{10,15})",
        r"\b(20\d{11})\b",
        r"\b([0-9]{13})\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, page_text, flags=re.IGNORECASE)
        if m:
            model = m.group(1)
            break

    return title.strip(), model.strip()


def read_token() -> str:
    if not os.path.exists(TOKEN_FILE):
        raise SystemExit(
            f"❌ Не найден token.txt рядом со скриптом: {TOKEN_FILE}\n"
            "Создай token.txt и вставь туда OAuth-токен Яндекс.Диска одной строкой."
        )
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        token = f.read().strip()
    if not token:
        raise SystemExit("❌ token.txt пустой")
    return token


def yandex_headers() -> dict:
    token = read_token()
    return {"Authorization": f"OAuth {token}"}


def create_yandex_folder(path: str, headers: dict):
    # создаём вложенно: disk:/Фиды, disk:/Фиды/Глетчер
    parts = path.replace("disk:/", "").split("/")
    current = "disk:"
    for part in parts:
        current += f"/{part}"
        r = requests.put(YANDEX_API, headers=headers, params={"path": current}, timeout=REQUEST_TIMEOUT)
        if r.status_code not in (201, 409):
            log(f"⚠️ Не удалось создать папку {current}: {r.status_code} {r.text[:200]}")


def yandex_file_exists(path: str, headers: dict) -> bool:
    r = requests.get(YANDEX_API, headers=headers, params={"path": path}, timeout=REQUEST_TIMEOUT)
    return r.status_code == 200


def upload_bytes_to_yandex(file_bytes: bytes, yandex_path: str, headers: dict):
    if yandex_file_exists(yandex_path, headers):
        log(f"⏭️ Уже есть на Диске: {yandex_path}")
        return "exists"

    r = requests.get(
        YANDEX_UPLOAD_API,
        headers=headers,
        params={"path": yandex_path, "overwrite": "true"},
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code != 200:
        log(f"❌ Не получил upload URL для {yandex_path}: {r.status_code} {r.text[:300]}")
        return "upload_url_error"

    upload_url = r.json().get("href")
    if not upload_url:
        log(f"❌ В ответе нет href для {yandex_path}")
        return "no_href"

    up = requests.put(upload_url, data=BytesIO(file_bytes), timeout=REQUEST_TIMEOUT)
    if up.status_code in (201, 202):
        log(f"✅ Загружено: {yandex_path}")
        return "uploaded"

    log(f"❌ Ошибка загрузки {yandex_path}: {up.status_code} {up.text[:300]}")
    return "upload_error"


def download_image(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT, verify=SSL_VERIFY_SOURCE_SITE)
        if r.status_code != 200:
            return None
        content_type = r.headers.get("Content-Type", "").lower()
        if "image" not in content_type and not r.content.startswith(b"\x89PNG"):
            return None
        return r.content
    except Exception:
        return None


def main():
    log("🚀 Старт: Глетчер")

    product_links = collect_with_requests()

    if not product_links:
        raise SystemExit("❌ Не найдено ни одной карточки модуля")

    log(f"✅ Уникальных модулей найдено: {len(product_links)}")

    modules = []
    for i, url in enumerate(product_links, 1):
        try:
            title, model = extract_title_and_model(url)
            if not title:
                title = f"module_{i}"
            if not model:
                log(f"⚠️ [{i}/{len(product_links)}] Не нашёл модель: {url}")
            else:
                log(f"[{i}/{len(product_links)}] {model} | {title}")
            modules.append({"url": url, "title": title, "model": model})
        except Exception as e:
            log(f"❌ Ошибка карточки {url}: {e}")
        time.sleep(PAGE_DELAY)

    # сохраняем список модулей
    with open(MODULES_FILE, "w", encoding="utf-8") as f:
        for m in modules:
            f.write(f'{m["url"]} | {m["title"]} | {m["model"]}\n')
    log(f"💾 Список модулей сохранён: {MODULES_FILE}")

    headers = yandex_headers()
    create_yandex_folder(YANDEX_BASE_FOLDER, headers)

    result_rows = []
    total_images = 0

    for m_i, module in enumerate(modules, 1):
        title = module["title"]
        model = re.sub(r"\D", "", module["model"] or "")
        if not model:
            result_rows.append([module["url"], title, "", "", "", "no_model"])
            continue

        safe_title = clean_filename(title)

        for img_i in range(1, 4):
            img_url = f"{TECH_IMG_BASE}/{model}_{img_i}.png"
            filename = f"{safe_title}_{img_i}.png"
            yandex_path = f"{YANDEX_BASE_FOLDER}/{filename}"

            img_bytes = download_image(img_url)
            if img_bytes is None:
                log(f"⚠️ Нет картинки: {img_url}")
                status = "not_found"
            else:
                status = upload_bytes_to_yandex(img_bytes, yandex_path, headers)
                total_images += 1 if status in ("uploaded", "exists") else 0

            result_rows.append([module["url"], title, model, img_url, yandex_path, status])
            time.sleep(0.3)

    with open(RESULT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Карточка", "Название", "Модель", "Ссылка на картинку", "Путь ЯД", "Статус"])
        writer.writerows(result_rows)

    log(f"✅ Готово. Обработано модулей: {len(modules)}, картинок найдено/загружено: {total_images}")
    log(f"💾 Отчёт: {RESULT_CSV}")


if __name__ == "__main__":
    main()
