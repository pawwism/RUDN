#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Глетчер: дозагрузка ТОЛЬКО недостающих фото в ГОТОВУЮ папку 3 цветов.

ВАЖНО: эта версия исправляет путь к Яндекс.Диску.
У тебя по скрину папка называется не disk:/Фиды/..., а:
    disk:/Фиды Глетчер/Глетчер_ИТОГ_3_цвета

Скрипт НЕ должен перекачивать всё заново:
1) сначала находит готовую итоговую папку;
2) проверяет наличие файла в нужной цветовой папке;
3) если файл уже есть — пропускает;
4) если файла нет — пробует скопировать из старой исходной папки;
5) если старого файла нет — скачивает с tech.sborno.ru.

Запуск:
    python gletcher_resume_upload_3_colors_FINAL_FIXED_PATH.py

Рядом должны лежать:
- token.txt
- modules_info_gletcher_3_colors_clean.txt
"""

import csv
import os
import re
import time
from datetime import datetime
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODULES_FILE_CANDIDATES = [
    os.path.join(BASE_DIR, "modules_info_gletcher_3_colors_clean.txt"),
    os.path.join(BASE_DIR, "modules_info_gletcher.txt"),
]

RESULT_CSV = os.path.join(BASE_DIR, "gletcher_3_colors_missing_upload_FIXED_report.csv")
LOG_FILE = os.path.join(BASE_DIR, "gletcher_3_colors_missing_upload_FIXED_log.txt")

TECH_IMG_BASE = "https://tech.sborno.ru/img"

# Новый правильный путь по твоему скрину: корневая папка называется "Фиды Глетчер".
# На всякий случай оставлен второй вариант, если у кого-то структура старая через /.
TARGET_BASE_CANDIDATES = [
    "disk:/Фиды Глетчер/Глетчер_ИТОГ_3_цвета",
    "disk:/Фиды/Глетчер_ИТОГ_3_цвета",
]

# Где могут лежать старые файлы со старыми названиями. Если не найдёт — просто скачает недостающее с сервера.
OLD_SOURCE_BASE_CANDIDATES = [
    "disk:/Фиды Глетчер/Глетчер",
    "disk:/Фиды/Глетчер",
    "disk:/Глетчер",
]

YANDEX_API = "https://cloud-api.yandex.net/v1/disk/resources"
YANDEX_UPLOAD_API = "https://cloud-api.yandex.net/v1/disk/resources/upload"
YANDEX_COPY_API = "https://cloud-api.yandex.net/v1/disk/resources/copy"

REQUEST_TIMEOUT = 60
RETRIES = 5
SLEEP_BETWEEN_IMAGES = 0.25

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

KEEP_COLOR_MAP: List[Tuple[List[str], str]] = [
    (["БЕЛ/МРН/СИЛК", "БЕЛ_МРН_СИЛК"], "АНД_СИЛК"),
    (["БЕЛ/МРН", "БЕЛ_МРН"], "МРН_СИЛК"),
    (["БЕЛ/ГНР", "БЕЛ_ГНР"], "ГНР_СИЛК"),
]

DROP_COLOR_TOKENS = [
    "ДБК/МРН/СИЛК", "ДБК_МРН_СИЛК",
    "ДБК/ГНР", "ДБК_ГНР",
    "ДБК/МРН", "ДБК_МРН",
]


def log(message: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def clean_filename(text: str, max_len: int = 170) -> str:
    text = re.sub(r"[<>:\"/\\|?*]", "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("ё", "е").replace("Ё", "Е")
    return text[:max_len].rstrip(" ._")


def request_with_retries(method: str, url: str, *, ok_statuses=None, **kwargs) -> Optional[requests.Response]:
    if ok_statuses is None:
        ok_statuses = {200, 201, 202, 204, 404, 409}

    last_error = None
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            if r.status_code in ok_statuses:
                return r
            last_error = f"HTTP {r.status_code}: {r.text[:300]}"
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
            return token
    raise SystemExit(f"❌ Не найден token.txt рядом со скриптом: {BASE_DIR}")


def yandex_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"OAuth {token}"}


def yandex_exists(path: str, headers: Dict[str, str]) -> bool:
    r = request_with_retries("GET", YANDEX_API, headers=headers, params={"path": path, "fields": "type"})
    return bool(r and r.status_code == 200)


def ensure_folder_exact(path: str, headers: Dict[str, str]) -> bool:
    """Создаёт только конкретную папку. Родителя не трогает, чтобы не плодить ошибочные папки."""
    if yandex_exists(path, headers):
        return True
    r = request_with_retries("PUT", YANDEX_API, headers=headers, params={"path": path}, ok_statuses={201, 409, 404})
    if r and r.status_code in (201, 409):
        return True
    log(f"⚠️ Не удалось создать папку: {path}")
    return False


def detect_target_base(headers: Dict[str, str]) -> str:
    for candidate in TARGET_BASE_CANDIDATES:
        log(f"🔎 Проверяю итоговую папку: {candidate}")
        if yandex_exists(candidate, headers):
            log(f"✅ Нашла итоговую папку: {candidate}")
            return candidate

    raise SystemExit(
        "❌ Не нашла итоговую папку. Скрипт остановлен, чтобы не перекачивать всё мимо.\n"
        "Проверь, как точно называется папка на Яндекс.Диске. По твоему скрину должно быть:\n"
        "disk:/Фиды Глетчер/Глетчер_ИТОГ_3_цвета"
    )


def yandex_copy(src_path: str, dst_path: str, headers: Dict[str, str]) -> str:
    r = request_with_retries(
        "POST",
        YANDEX_COPY_API,
        headers=headers,
        params={"from": src_path, "path": dst_path, "overwrite": "true"},
        ok_statuses={201, 202, 404, 409},
    )
    if not r:
        return "copy_request_error"
    if r.status_code in (201, 202):
        log(f"✅ Скопировано из старой папки: {dst_path}")
        return "copied_from_old_folder"
    if r.status_code == 404:
        return "old_source_not_found"
    return f"copy_error_{r.status_code}"


def upload_bytes_to_yandex(file_bytes: bytes, yandex_path: str, headers: Dict[str, str]) -> str:
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
        log(f"✅ Скачано и загружено: {yandex_path}")
        return "downloaded_and_uploaded"

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


def choose_modules_file() -> str:
    for path in MODULES_FILE_CANDIDATES:
        if os.path.exists(path):
            return path
    raise SystemExit("❌ Не найден modules_info_gletcher_3_colors_clean.txt или modules_info_gletcher.txt рядом со скриптом")


def detect_new_color_and_title(title: str) -> Tuple[Optional[str], Optional[str], str]:
    title_upper = title.upper()

    for bad in DROP_COLOR_TOKENS:
        if bad in title_upper:
            return None, None, "skipped_dark_color"

    for old_variants, new_color in KEEP_COLOR_MAP:
        for old in old_variants:
            if old in title:
                new_title = title.replace(old, new_color)
                return new_color, new_title, "keep"
            if old.upper() in title_upper:
                new_title = re.sub(re.escape(old), new_color, title, flags=re.IGNORECASE)
                return new_color, new_title, "keep"

    return None, None, "unknown_color"


def read_modules() -> List[Dict[str, str]]:
    modules_file = choose_modules_file()
    log(f"📄 Использую файл модулей: {os.path.basename(modules_file)}")

    modules: List[Dict[str, str]] = []
    seen = set()
    with open(modules_file, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            parts = [x.strip() for x in raw.split("|")]
            if len(parts) < 3:
                log(f"⚠️ Пропускаю строку неправильного формата: {raw[:150]}")
                continue
            url, title, model = parts[0], parts[1], re.sub(r"\D", "", parts[2])
            if not model:
                log(f"⚠️ Без модели: {title}")
                continue

            new_color, new_title, status = detect_new_color_and_title(title)
            if status != "keep" or not new_color or not new_title:
                continue

            key = (model, new_color, new_title)
            if key in seen:
                continue
            seen.add(key)
            modules.append({
                "url": url,
                "title": title,
                "model": model,
                "new_color": new_color,
                "new_title": new_title,
            })
    return modules


def append_result(row: List[str]) -> None:
    file_exists = os.path.exists(RESULT_CSV)
    with open(RESULT_CSV, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        if not file_exists:
            writer.writerow([
                "Карточка",
                "Старое название",
                "Новое название",
                "Модель",
                "Цветовая папка",
                "Картинка",
                "Целевой путь ЯД",
                "Статус",
            ])
        writer.writerow(row)


def main() -> None:
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("")

    log("🚀 Дозагрузка недостающих фото Глетчер в готовую структуру 3 цветов — FIXED PATH")

    token = read_token()
    headers = yandex_headers(token)

    target_base = detect_target_base(headers)

    # Проверяем/создаём только цветовые подпапки внутри реально найденной итоговой папки.
    for _, new_color in KEEP_COLOR_MAP:
        ensure_folder_exact(f"{target_base}/{new_color}", headers)

    modules = read_modules()
    log(f"📄 Модулей к проверке по 3 цветам: {len(modules)}")

    stats = {
        "exists_in_final": 0,
        "copied_from_old_folder": 0,
        "downloaded_and_uploaded": 0,
        "not_found_on_server": 0,
        "errors": 0,
    }

    for m_i, module in enumerate(modules, 1):
        old_title = module["title"]
        new_title = module["new_title"]
        model = module["model"]
        new_color = module["new_color"]

        old_safe_title = clean_filename(old_title)
        new_safe_title = clean_filename(new_title)

        log(f"[{m_i}/{len(modules)}] {model} | {new_color} | {new_title}")

        for img_i in range(1, 4):
            img_url = f"{TECH_IMG_BASE}/{model}_{img_i}.png"
            target_filename = f"{new_safe_title}_{img_i}.png"
            target_path = f"{target_base}/{new_color}/{target_filename}"

            if yandex_exists(target_path, headers):
                log(f"⏭️ Уже есть в итоговой папке, не скачиваю: {target_path}")
                status = "exists_in_final"
                stats[status] += 1
                append_result([module["url"], old_title, new_title, model, new_color, img_url, target_path, status])
                continue

            # Только если файла реально нет в итоговой папке — ищем старый файл.
            copied = False
            old_filename = f"{old_safe_title}_{img_i}.png"
            for old_base in OLD_SOURCE_BASE_CANDIDATES:
                old_source_path = f"{old_base}/{old_filename}"
                if yandex_exists(old_source_path, headers):
                    status = yandex_copy(old_source_path, target_path, headers)
                    if status == "copied_from_old_folder":
                        stats["copied_from_old_folder"] += 1
                        append_result([module["url"], old_title, new_title, model, new_color, img_url, target_path, status])
                        copied = True
                        break
            if copied:
                continue

            img_bytes = download_image(img_url)
            if img_bytes is None:
                log(f"⚠️ Нет картинки на сервере: {img_url}")
                status = "not_found_on_server"
                stats[status] += 1
            else:
                status = upload_bytes_to_yandex(img_bytes, target_path, headers)
                if status == "downloaded_and_uploaded":
                    stats["downloaded_and_uploaded"] += 1
                else:
                    stats["errors"] += 1

            append_result([module["url"], old_title, new_title, model, new_color, img_url, target_path, status])
            time.sleep(SLEEP_BETWEEN_IMAGES)

    log("✅ Готово")
    log(f"Итог: {stats}")
    log(f"Отчёт: {RESULT_CSV}")


if __name__ == "__main__":
    main()
