#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Глетчер: стабильная дозагрузка картинок на Яндекс.Диск из modules_info_gletcher.txt.

Что исправлено:
- не падает от временных SSL/Connection ошибок Яндекс.Диска;
- делает несколько повторов загрузки;
- если файл уже есть на Я.Диске — пропускает его;
- пишет отчёт построчно, чтобы прогресс не терялся;
- принимает token.txt и token.txt.txt.

Запуск:
python gletcher_resume_upload_STABLE.py
"""

import csv
import os
import re
import time
from datetime import datetime
from io import BytesIO
from typing import Optional

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODULES_FILE = os.path.join(BASE_DIR, "modules_info_gletcher.txt")
RESULT_CSV = os.path.join(BASE_DIR, "gletcher_result_stable.csv")
LOG_FILE = os.path.join(BASE_DIR, "gletcher_upload_stable_log.txt")

COLLECTION_NAME = "Глетчер"
TECH_IMG_BASE = "https://tech.sborno.ru/img"
YANDEX_BASE_FOLDER = f"disk:/Фиды Глетчер/{COLLECTION_NAME}"

YANDEX_API = "https://cloud-api.yandex.net/v1/disk/resources"
YANDEX_UPLOAD_API = "https://cloud-api.yandex.net/v1/disk/resources/upload"

REQUEST_TIMEOUT = 45
RETRIES = 5
SLEEP_BETWEEN_IMAGES = 0.5

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


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


def request_with_retries(method: str, url: str, *, ok_statuses=None, **kwargs) -> Optional[requests.Response]:
    """Запрос с повторами. Не роняет весь скрипт при временной ошибке сети."""
    if ok_statuses is None:
        ok_statuses = {200, 201, 202, 204, 409, 404}

    last_error = None
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            if r.status_code in ok_statuses:
                return r
            last_error = f"HTTP {r.status_code}: {r.text[:200]}"
        except requests.exceptions.RequestException as e:
            last_error = repr(e)

        wait = min(3 * attempt, 15)
        log(f"⚠️ Попытка {attempt}/{RETRIES} не удалась: {last_error}. Жду {wait} сек.")
        time.sleep(wait)

    log(f"❌ Запрос окончательно не удался: {method} {url} | {last_error}")
    return None


def read_token() -> str:
    for filename in ("token.txt", "token.txt.txt"):
        path = os.path.join(BASE_DIR, filename)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                token = f.read().strip()
            if not token:
                raise SystemExit(f"❌ Файл токена пустой: {path}")
            if filename == "token.txt.txt":
                log("⚠️ Нашёл token.txt.txt. Использую его, но лучше переименовать в token.txt")
            return token
    raise SystemExit(f"❌ Не найден token.txt рядом со скриптом: {BASE_DIR}")


def yandex_headers() -> dict:
    return {"Authorization": f"OAuth {read_token()}"}


def create_yandex_folder(path: str, headers: dict):
    parts = path.replace("disk:/", "").split("/")
    current = "disk:"
    for part in parts:
        current += f"/{part}"
        r = request_with_retries("PUT", YANDEX_API, headers=headers, params={"path": current})
        if not r or r.status_code not in (201, 409):
            log(f"⚠️ Не удалось создать/проверить папку {current}")


def yandex_file_exists(path: str, headers: dict) -> bool:
    r = request_with_retries("GET", YANDEX_API, headers=headers, params={"path": path})
    return bool(r and r.status_code == 200)


def upload_bytes_to_yandex(file_bytes: bytes, yandex_path: str, headers: dict) -> str:
    if yandex_file_exists(yandex_path, headers):
        log(f"⏭️ Уже есть на Диске: {yandex_path}")
        return "exists"

    r = request_with_retries(
        "GET",
        YANDEX_UPLOAD_API,
        headers=headers,
        params={"path": yandex_path, "overwrite": "true"},
        ok_statuses={200},
    )
    if not r:
        return "upload_url_error"

    upload_url = r.json().get("href")
    if not upload_url:
        log(f"❌ В ответе нет href для {yandex_path}")
        return "no_href"

    up = request_with_retries(
        "PUT",
        upload_url,
        data=BytesIO(file_bytes),
        ok_statuses={201, 202},
    )
    if up and up.status_code in (201, 202):
        log(f"✅ Загружено: {yandex_path}")
        return "uploaded"

    log(f"❌ Не удалось загрузить после повторов: {yandex_path}")
    return "upload_error"


def download_image(url: str) -> Optional[bytes]:
    r = request_with_retries(
        "GET",
        url,
        headers=REQUEST_HEADERS,
        verify=False,
        ok_statuses={200, 404, 403},
    )
    if not r or r.status_code != 200:
        return None
    content_type = r.headers.get("Content-Type", "").lower()
    if "image" not in content_type and not r.content.startswith(b"\x89PNG"):
        return None
    return r.content


def read_modules() -> list[dict]:
    if not os.path.exists(MODULES_FILE):
        raise SystemExit(f"❌ Не найден {MODULES_FILE}. Сначала нужен modules_info_gletcher.txt")

    modules = []
    seen = set()
    with open(MODULES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = [x.strip() for x in line.split("|")]
            if len(parts) < 3:
                log(f"⚠️ Пропускаю строку неправильного формата: {line[:150]}")
                continue
            url, title, model = parts[0], parts[1], re.sub(r"\D", "", parts[2])
            if not model:
                log(f"⚠️ Без модели: {title}")
                continue
            key = (url, model)
            if key in seen:
                continue
            seen.add(key)
            modules.append({"url": url, "title": title, "model": model})
    return modules


def append_result(row: list):
    file_exists = os.path.exists(RESULT_CSV)
    with open(RESULT_CSV, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        if not file_exists:
            writer.writerow(["Карточка", "Название", "Модель", "Ссылка на картинку", "Путь ЯД", "Статус"])
        writer.writerow(row)


def main():
    log("🚀 Стабильная дозагрузка Глетчер из modules_info_gletcher.txt")
    modules = read_modules()
    log(f"📄 Модулей в файле: {len(modules)}")

    headers = yandex_headers()
    create_yandex_folder(YANDEX_BASE_FOLDER, headers)

    total_ok = 0
    total_not_found = 0
    total_error = 0

    for m_i, module in enumerate(modules, 1):
        title = module["title"]
        model = module["model"]
        safe_title = clean_filename(title)
        log(f"[{m_i}/{len(modules)}] {model} | {title}")

        for img_i in range(1, 4):
            img_url = f"{TECH_IMG_BASE}/{model}_{img_i}.png"
            filename = f"{safe_title}_{img_i}.png"
            yandex_path = f"{YANDEX_BASE_FOLDER}/{filename}"

            img_bytes = download_image(img_url)
            if img_bytes is None:
                log(f"⚠️ Нет картинки: {img_url}")
                status = "not_found"
                total_not_found += 1
            else:
                status = upload_bytes_to_yandex(img_bytes, yandex_path, headers)
                if status in ("uploaded", "exists"):
                    total_ok += 1
                else:
                    total_error += 1

            append_result([module["url"], title, model, img_url, yandex_path, status])
            time.sleep(SLEEP_BETWEEN_IMAGES)

    log(f"✅ Готово. Модулей: {len(modules)}, успешно/уже было: {total_ok}, нет картинок: {total_not_found}, ошибок загрузки: {total_error}")
    log(f"💾 Отчёт: {RESULT_CSV}")


if __name__ == "__main__":
    main()
