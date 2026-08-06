#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Глетчер — Гейнсборо силк (серый светлый):
публикация изображений на Яндекс.Диске и выгрузка ссылок в Excel.

Положите этот файл рядом с token.txt и запустите:
    python .\yandex_gletcher_gainsborough_links_to_excel.py

Результат:
    Глетчер_Гейнсборо_силк_ссылки.xlsx
    gletcher_gainsborough_links_log.txt
"""

from __future__ import annotations

import re
import sys
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from xml.sax.saxutils import escape

import requests


BASE_DIR = Path(__file__).resolve().parent
TOKEN_FILES = (BASE_DIR / "token.txt", BASE_DIR / "token.txt.txt")

YANDEX_FOLDER = (
    "disk:/Картинки для карточек ОЗОН Модули/"
    "Модули: Глетчер - Гейнсборо силк (серый светлый)"
)

OUTPUT_XLSX = BASE_DIR / "Глетчер_Гейнсборо_силк_ссылки.xlsx"
LOG_FILE = BASE_DIR / "gletcher_gainsborough_links_log.txt"

RESOURCES_API = "https://cloud-api.yandex.net/v1/disk/resources"
PUBLISH_API = "https://cloud-api.yandex.net/v1/disk/resources/publish"

TIMEOUT = 60
RETRIES = 5
PAUSE = 0.15
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def log(message: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(line + "\n")


def read_token() -> str:
    for path in TOKEN_FILES:
        if path.exists():
            token = path.read_text(encoding="utf-8").strip()
            if token:
                return token
            raise SystemExit(f"❌ Файл токена пустой: {path}")
    raise SystemExit(
        "❌ Не найден token.txt рядом со скриптом.\n"
        f"Папка запуска: {BASE_DIR}"
    )


def request_retry(
    method: str,
    url: str,
    *,
    expected: Iterable[int],
    **kwargs,
) -> requests.Response:
    expected_codes = set(expected)
    last_error = ""

    for attempt in range(1, RETRIES + 1):
        try:
            response = requests.request(
                method,
                url,
                timeout=TIMEOUT,
                **kwargs,
            )
            if response.status_code in expected_codes:
                return response
            last_error = f"HTTP {response.status_code}: {response.text[:400]}"
        except requests.RequestException as error:
            last_error = repr(error)

        if attempt < RETRIES:
            wait = min(attempt * 2, 10)
            log(
                f"⚠️ Попытка {attempt}/{RETRIES} не удалась: "
                f"{last_error}. Повтор через {wait} сек."
            )
            time.sleep(wait)

    raise RuntimeError(f"Запрос не выполнен: {method} {url} | {last_error}")


def list_images(folder: str, headers: Dict[str, str]) -> List[Dict]:
    result: List[Dict] = []
    stack = [folder]
    visited = set()

    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        log(f"📂 Читаю папку: {current}")

        offset = 0
        limit = 1000

        while True:
            response = request_retry(
                "GET",
                RESOURCES_API,
                expected={200},
                headers=headers,
                params={
                    "path": current,
                    "limit": limit,
                    "offset": offset,
                    "fields": (
                        "_embedded.items.name,"
                        "_embedded.items.path,"
                        "_embedded.items.type,"
                        "_embedded.items.public_url,"
                        "_embedded.total"
                    ),
                },
            )

            data = response.json().get("_embedded", {})
            items = data.get("items", [])
            total = int(data.get("total", len(items)))

            for item in items:
                item_type = item.get("type")
                item_path = item.get("path")
                if not item_path:
                    continue
                if item_type == "dir":
                    stack.append(item_path)
                elif item_type == "file":
                    if Path(item.get("name", "")).suffix.lower() in IMAGE_EXTENSIONS:
                        result.append(item)

            offset += len(items)
            if not items or offset >= total:
                break

    return result


def publish_file(path: str, headers: Dict[str, str]) -> str:
    response = request_retry(
        "PUT",
        PUBLISH_API,
        expected={200, 201, 202, 409},
        headers=headers,
        params={"path": path},
    )

    if response.status_code == 202:
        time.sleep(1)

    for attempt in range(1, 6):
        metadata = request_retry(
            "GET",
            RESOURCES_API,
            expected={200},
            headers=headers,
            params={"path": path, "fields": "name,path,public_url"},
        ).json()
        public_url = metadata.get("public_url")
        if public_url:
            return str(public_url)
        if attempt < 5:
            time.sleep(attempt)

    raise RuntimeError(f"Не получена публичная ссылка: {path}")


def detect_type(filename: str) -> Tuple[str, Optional[str]]:
    stem = Path(filename).stem.strip()
    match = re.match(
        r"^(.*?)[\s_\-–—]+(главная|размеры|выбор)$",
        stem,
        flags=re.IGNORECASE,
    )
    if not match:
        return re.sub(r"\s+", " ", stem).strip(), None

    module = re.sub(r"\s+", " ", match.group(1)).strip(" _-–—")
    return module, match.group(2).lower()


def excel_column(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def xlsx_formula_hyperlink(url: str) -> str:
    safe = url.replace('"', '""')
    return f'HYPERLINK("{safe}","Открыть")'


def xml_cell(
    ref: str,
    *,
    value: str = "",
    style: int = 0,
    formula: Optional[str] = None,
) -> str:
    style_attr = f' s="{style}"' if style else ""
    if formula is not None:
        return (
            f'<c r="{ref}"{style_attr}>'
            f'<f>{escape(formula)}</f><v></v></c>'
        )
    if value == "":
        return f'<c r="{ref}"{style_attr}></c>'
    return (
        f'<c r="{ref}" t="inlineStr"{style_attr}>'
        f'<is><t>{escape(str(value))}</t></is></c>'
    )


def build_sheet(
    rows: List[List[Dict[str, object]]],
    widths: List[float],
    autofilter: str,
    tab_color: str,
) -> str:
    row_xml: List[str] = []

    for row_number, row in enumerate(rows, start=1):
        cells: List[str] = []
        for column_number, data in enumerate(row, start=1):
            ref = f"{excel_column(column_number)}{row_number}"
            cells.append(
                xml_cell(
                    ref,
                    value=str(data.get("value", "")),
                    style=int(data.get("style", 0)),
                    formula=data.get("formula"),
                )
            )
        height = 27 if row_number == 1 else 21
        row_xml.append(
            f'<row r="{row_number}" ht="{height}" customHeight="1">'
            + "".join(cells)
            + "</row>"
        )

    columns = "".join(
        f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        for index, width in enumerate(widths, start=1)
    )

    max_col = excel_column(max(len(row) for row in rows))
    max_row = len(rows)

    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetPr><tabColor rgb="{tab_color}"/></sheetPr>
  <dimension ref="A1:{max_col}{max_row}"/>
  <sheetViews>
    <sheetView workbookViewId="0">
      <pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>
    </sheetView>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="15"/>
  <cols>{columns}</cols>
  <sheetData>{''.join(row_xml)}</sheetData>
  <autoFilter ref="{autofilter}"/>
  <pageMargins left="0.3" right="0.3" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>
</worksheet>'''


def write_xlsx(
    output: Path,
    grouped_rows: List[Dict[str, str]],
    file_rows: List[Dict[str, str]],
) -> None:
    rows1: List[List[Dict[str, object]]] = [[
        {"value": "Название модуля", "style": 1},
        {"value": "Главная", "style": 1},
        {"value": "Размеры", "style": 1},
        {"value": "Выбор", "style": 1},
        {"value": "Статус", "style": 1},
        {"value": "Отсутствует", "style": 1},
    ]]

    for row_number, item in enumerate(grouped_rows, start=2):
        def link_cell(url: str) -> Dict[str, object]:
            if not url:
                return {"value": "", "style": 4}
            return {
                "value": "",
                "style": 3,
                "formula": xlsx_formula_hyperlink(url),
            }

        rows1.append([
            {"value": item["module"], "style": 2},
            link_cell(item.get("главная", "")),
            link_cell(item.get("размеры", "")),
            link_cell(item.get("выбор", "")),
            {
                "value": "",
                "style": 5,
                "formula": (
                    f'IF(COUNTA(B{row_number}:D{row_number})=3,'
                    f'"Комплект","Неполный комплект")'
                ),
            },
            {
                "value": item.get("missing", ""),
                "style": 4 if item.get("missing") else 2,
            },
        ])

    rows2: List[List[Dict[str, object]]] = [[
        {"value": "Имя файла", "style": 1},
        {"value": "Название модуля", "style": 1},
        {"value": "Тип картинки", "style": 1},
        {"value": "Публичная ссылка", "style": 1},
        {"value": "Путь на Яндекс.Диске", "style": 1},
        {"value": "Распознано", "style": 1},
    ]]

    for item in file_rows:
        url = item.get("url", "")
        rows2.append([
            {"value": item.get("filename", ""), "style": 2},
            {"value": item.get("module", ""), "style": 2},
            {"value": item.get("type", "") or "не определён", "style": 2},
            {
                "value": "" if url else "",
                "style": 3 if url else 4,
                "formula": xlsx_formula_hyperlink(url) if url else None,
            },
            {"value": item.get("path", ""), "style": 2},
            {
                "value": "Да" if item.get("type") else "Нет",
                "style": 5 if item.get("type") else 4,
            },
        ])

    sheet1 = build_sheet(
        rows1,
        widths=[44, 15, 15, 15, 22, 30],
        autofilter=f"A1:F{len(rows1)}",
        tab_color="FF63C7C1",
    )
    sheet2 = build_sheet(
        rows2,
        widths=[52, 44, 18, 18, 72, 14],
        autofilter=f"A1:F{len(rows2)}",
        tab_color="FFA7E3A1",
    )

    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>'''

    root_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''

    workbook = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <bookViews><workbookView windowWidth="24000" windowHeight="12000"/></bookViews>
  <sheets>
    <sheet name="Ссылки по модулям" sheetId="1" r:id="rId1"/>
    <sheet name="Все файлы" sheetId="2" r:id="rId2"/>
  </sheets>
  <calcPr calcId="191029" calcMode="auto" fullCalcOnLoad="1" forceFullCalc="1"/>
</workbook>'''

    workbook_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''

    styles = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="3">
    <font><sz val="11"/><name val="Calibri"/><family val="2"/></font>
    <font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font>
    <font><u/><color rgb="FF0563C1"/><sz val="11"/><name val="Calibri"/></font>
  </fonts>
  <fills count="5">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF288F8A"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFE2F0D9"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFFFE2E2"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border>
      <left style="thin"><color rgb="FFD9E1E8"/></left>
      <right style="thin"><color rgb="FFD9E1E8"/></right>
      <top style="thin"><color rgb="FFD9E1E8"/></top>
      <bottom style="thin"><color rgb="FFD9E1E8"/></bottom>
      <diagonal/>
    </border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="6">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="4" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
  <dxfs count="0"/>
  <tableStyles count="0" defaultTableStyle="TableStyleMedium2" defaultPivotStyle="PivotStyleLight16"/>
</styleSheet>'''

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    core = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties
 xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:dcmitype="http://purl.org/dc/dcmitype/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:creator>ChatGPT</dc:creator>
  <cp:lastModifiedBy>ChatGPT</cp:lastModifiedBy>
  <dc:title>Глетчер Маренго силк — ссылки</dc:title>
  <dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>
</cp:coreProperties>'''

    app = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
 xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Microsoft Excel</Application>
  <DocSecurity>0</DocSecurity>
  <ScaleCrop>false</ScaleCrop>
  <HeadingPairs>
    <vt:vector size="2" baseType="variant">
      <vt:variant><vt:lpstr>Листы</vt:lpstr></vt:variant>
      <vt:variant><vt:i4>2</vt:i4></vt:variant>
    </vt:vector>
  </HeadingPairs>
  <TitlesOfParts>
    <vt:vector size="2" baseType="lpstr">
      <vt:lpstr>Ссылки по модулям</vt:lpstr>
      <vt:lpstr>Все файлы</vt:lpstr>
    </vt:vector>
  </TitlesOfParts>
  <AppVersion>16.0300</AppVersion>
</Properties>'''

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/styles.xml", styles)
        archive.writestr("xl/worksheets/sheet1.xml", sheet1)
        archive.writestr("xl/worksheets/sheet2.xml", sheet2)
        archive.writestr("docProps/core.xml", core)
        archive.writestr("docProps/app.xml", app)


def main() -> None:
    LOG_FILE.write_text("", encoding="utf-8")
    log("🚀 Старт: выгрузка ссылок Глетчер — Гейнсборо силк")
    log(f"Папка: {YANDEX_FOLDER}")

    token = read_token()
    headers = {"Authorization": f"OAuth {token}"}

    images = list_images(YANDEX_FOLDER, headers)
    if not images:
        raise SystemExit(
            "❌ В папке не найдено изображений. "
            "Проверьте, что экспорт из Figma уже загружен."
        )

    images.sort(key=lambda item: item.get("name", "").lower())
    log(f"📄 Найдено файлов: {len(images)}")

    grouped: Dict[str, Dict[str, str]] = defaultdict(dict)
    file_rows: List[Dict[str, str]] = []
    errors = 0

    for index, item in enumerate(images, start=1):
        filename = str(item.get("name", "")).strip()
        disk_path = str(item.get("path", "")).strip()
        module, image_type = detect_type(filename)

        log(f"[{index}/{len(images)}] {filename}")

        try:
            public_url = str(
                item.get("public_url") or publish_file(disk_path, headers)
            )
            log("✅ Ссылка получена")
        except Exception as error:
            public_url = ""
            errors += 1
            log(f"❌ Не удалось получить ссылку: {error}")

        if image_type:
            grouped[module].setdefault(image_type, public_url)

        file_rows.append({
            "filename": filename,
            "module": module,
            "type": image_type or "",
            "url": public_url,
            "path": disk_path,
        })

        time.sleep(PAUSE)

    grouped_rows: List[Dict[str, str]] = []
    for module in sorted(grouped, key=str.lower):
        links = grouped[module]
        missing = [
            name
            for name in ("главная", "размеры", "выбор")
            if not links.get(name)
        ]
        grouped_rows.append({
            "module": module,
            "главная": links.get("главная", ""),
            "размеры": links.get("размеры", ""),
            "выбор": links.get("выбор", ""),
            "missing": ", ".join(missing),
        })

    write_xlsx(OUTPUT_XLSX, grouped_rows, file_rows)

    complete = sum(1 for row in grouped_rows if not row["missing"])
    incomplete = len(grouped_rows) - complete
    unrecognized = sum(1 for row in file_rows if not row["type"])

    log("✅ Готово")
    log(f"📦 Модулей: {len(grouped_rows)}")
    log(f"✅ Полных комплектов: {complete}")
    log(f"⚠️ Неполных комплектов: {incomplete}")
    log(f"❓ Нераспознанных файлов: {unrecognized}")
    log(f"❌ Ошибок публикации: {errors}")
    log(f"📊 Excel: {OUTPUT_XLSX}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⛔ Остановлено пользователем.")
        sys.exit(130)
    except Exception as error:
        log(f"❌ Критическая ошибка: {error}")
        raise
