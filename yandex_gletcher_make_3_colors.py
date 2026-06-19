# -*- coding: utf-8 -*-
"""
Глетчер: сделать чистую структуру только из 3 нужных цветов на Яндекс.Диске.

Что делает:
1) Берет PNG-файлы из disk:/Фиды/Глетчер, в том числе если они уже лежат в подпапках.
2) Оставляет только:
   БЕЛ_МРН       -> МРН_СИЛК
   БЕЛ_ГНР       -> ГНР_СИЛК
   БЕЛ_МРН_СИЛК  -> АНД_СИЛК
3) ДБК_ГНР, ДБК_МРН, ДБК_МРН_СИЛК не копирует.
4) Создает новую чистую папку:
   disk:/Фиды/Глетчер_ИТОГ_3_цвета
5) Копирует туда файлы по папкам цветов и переименовывает цвет в названии файла.

ВАЖНО: скрипт НЕ удаляет старые файлы. Он безопасно делает новую итоговую папку.

Запуск:
python yandex_gletcher_make_3_colors.py
"""

import csv
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

# ===== НАСТРОЙКИ =====
SOURCE_BASE = "disk:/Фиды/Глетчер"
TARGET_BASE = "disk:/Фиды/Глетчер_ИТОГ_3_цвета"

# Слэш / нельзя использовать в имени папки Яндекс.Диска, потому что он означает вложенную папку.
# Поэтому вместо МРН/СИЛК используем МРН_СИЛК.
COLOR_MAP: List[Tuple[str, str]] = [
    ("БЕЛ_МРН_СИЛК", "АНД_СИЛК"),
    ("БЕЛ_МРН", "МРН_СИЛК"),
    ("БЕЛ_ГНР", "ГНР_СИЛК"),
]

EXCLUDE_TOKENS = ["ДБК_МРН_СИЛК", "ДБК_ГНР", "ДБК_МРН"]

REQUEST_TIMEOUT = 60
RETRY_COUNT = 5
REPORT_CSV = "gletcher_3_colors_report.csv"
LOG_FILE = "gletcher_3_colors_log.txt"
# =====================

API = "https://cloud-api.yandex.net/v1/disk/resources"


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    line = f"[{now()}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_token() -> str:
    for name in ("token.txt", "token.txt.txt"):
        if os.path.exists(name):
            with open(name, "r", encoding="utf-8") as f:
                token = f.read().strip()
            if token:
                return token
    raise SystemExit("❌ Не найден token.txt рядом со скриптом. Положи token.txt в эту же папку.")


def request_with_retries(method: str, url: str, headers: Dict[str, str], **kwargs) -> Optional[requests.Response]:
    last_error = None
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            r = requests.request(method, url, headers=headers, timeout=REQUEST_TIMEOUT, **kwargs)
            return r
        except requests.RequestException as e:
            last_error = e
            wait = attempt * 3
            log(f"⚠️ Попытка {attempt}/{RETRY_COUNT} не удалась: {repr(e)}. Жду {wait} сек.")
            time.sleep(wait)
    log(f"❌ Запрос окончательно не удался: {method} {url} | {repr(last_error)}")
    return None


def ensure_folder(path: str, headers: Dict[str, str]) -> bool:
    """Создать папку. Если уже есть — нормально."""
    r = request_with_retries("PUT", API, headers=headers, params={"path": path})
    if r is None:
        return False
    if r.status_code in (201, 409):
        return True
    log(f"⚠️ Не удалось создать папку {path}: {r.status_code} {r.text[:300]}")
    return False


def exists(path: str, headers: Dict[str, str]) -> bool:
    r = request_with_retries("GET", API, headers=headers, params={"path": path, "fields": "type"})
    if r is None:
        return False
    return r.status_code == 200


def list_dir(path: str, headers: Dict[str, str]) -> List[Dict]:
    """Список элементов папки с пагинацией."""
    items: List[Dict] = []
    offset = 0
    limit = 1000

    while True:
        params = {
            "path": path,
            "limit": limit,
            "offset": offset,
            "fields": "_embedded.items.name,_embedded.items.path,_embedded.items.type,_embedded.total,_embedded.limit,_embedded.offset",
        }
        r = request_with_retries("GET", API, headers=headers, params=params)
        if r is None:
            break
        if r.status_code != 200:
            log(f"⚠️ Не могу прочитать папку {path}: {r.status_code} {r.text[:300]}")
            break

        data = r.json().get("_embedded", {})
        batch = data.get("items", [])
        items.extend(batch)

        total = data.get("total", len(items))
        offset += limit
        if offset >= total or not batch:
            break

    return items


def collect_png_files_recursive(base_path: str, headers: Dict[str, str]) -> List[Dict]:
    result: List[Dict] = []
    stack = [base_path]
    visited = set()

    while stack:
        folder = stack.pop()
        if folder in visited:
            continue
        visited.add(folder)

        log(f"📂 Читаю папку: {folder}")
        for item in list_dir(folder, headers):
            item_type = item.get("type")
            item_path = item.get("path")
            name = item.get("name", "")
            if not item_path:
                continue
            if item_type == "dir":
                # рекурсивно читаем старые папки цветов, если они уже были созданы
                stack.append(item_path)
            elif item_type == "file" and name.lower().endswith(".png"):
                result.append(item)

    return result


def detect_color(filename: str) -> Tuple[Optional[str], Optional[str], str]:
    """Вернуть old_color, new_color, status."""
    for bad in EXCLUDE_TOKENS:
        if bad in filename:
            return bad, None, "excluded_dark_color"

    for old, new in COLOR_MAP:
        if old in filename:
            return old, new, "keep"

    return None, None, "unknown_color"


def copy_file(src_path: str, dst_path: str, headers: Dict[str, str]) -> bool:
    r = request_with_retries(
        "POST",
        API + "/copy",
        headers=headers,
        params={"from": src_path, "path": dst_path, "overwrite": "true"},
    )
    if r is None:
        return False
    if r.status_code in (201, 202):
        return True
    log(f"❌ Не удалось скопировать: {src_path} -> {dst_path}: {r.status_code} {r.text[:500]}")
    return False


def main() -> None:
    # чистим лог текущего запуска
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("")

    token = read_token()
    headers = {"Authorization": f"OAuth {token}"}

    log("🚀 Старт: делаю чистую структуру Глетчер только по 3 цветам")
    log(f"Источник: {SOURCE_BASE}")
    log(f"Итоговая папка: {TARGET_BASE}")

    ensure_folder("disk:/Фиды", headers)
    ensure_folder(TARGET_BASE, headers)
    for _, new_color in COLOR_MAP:
        ensure_folder(f"{TARGET_BASE}/{new_color}", headers)

    files = collect_png_files_recursive(SOURCE_BASE, headers)
    log(f"📄 Найдено PNG-файлов в источнике: {len(files)}")

    stats = {
        "copied": 0,
        "already_exists": 0,
        "excluded_dark_color": 0,
        "unknown_color": 0,
        "copy_error": 0,
    }
    color_counts: Dict[str, int] = {new: 0 for _, new in COLOR_MAP}

    with open(REPORT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["status", "old_color", "new_color", "source_path", "target_path", "source_name", "target_name"],
            delimiter=";",
        )
        writer.writeheader()

        for idx, item in enumerate(files, start=1):
            src_name = item.get("name", "")
            src_path = item.get("path", "")
            old_color, new_color, status = detect_color(src_name)

            if status != "keep" or not old_color or not new_color:
                stats[status] = stats.get(status, 0) + 1
                writer.writerow({
                    "status": status,
                    "old_color": old_color or "",
                    "new_color": new_color or "",
                    "source_path": src_path,
                    "target_path": "",
                    "source_name": src_name,
                    "target_name": "",
                })
                continue

            target_name = src_name.replace(old_color, new_color)
            target_path = f"{TARGET_BASE}/{new_color}/{target_name}"

            if exists(target_path, headers):
                log(f"[{idx}/{len(files)}] ⏭️ Уже есть: {target_path}")
                stats["already_exists"] += 1
                color_counts[new_color] += 1
                writer.writerow({
                    "status": "already_exists",
                    "old_color": old_color,
                    "new_color": new_color,
                    "source_path": src_path,
                    "target_path": target_path,
                    "source_name": src_name,
                    "target_name": target_name,
                })
                continue

            ok = copy_file(src_path, target_path, headers)
            if ok:
                log(f"[{idx}/{len(files)}] ✅ Скопировано: {target_path}")
                stats["copied"] += 1
                color_counts[new_color] += 1
                writer.writerow({
                    "status": "copied",
                    "old_color": old_color,
                    "new_color": new_color,
                    "source_path": src_path,
                    "target_path": target_path,
                    "source_name": src_name,
                    "target_name": target_name,
                })
            else:
                stats["copy_error"] += 1
                writer.writerow({
                    "status": "copy_error",
                    "old_color": old_color,
                    "new_color": new_color,
                    "source_path": src_path,
                    "target_path": target_path,
                    "source_name": src_name,
                    "target_name": target_name,
                })

    log("✅ Готово")
    log(f"Итог: {stats}")
    log(f"По цветам в итоговой папке: {color_counts}")
    log(f"Отчёт сохранён: {REPORT_CSV}")


if __name__ == "__main__":
    main()
