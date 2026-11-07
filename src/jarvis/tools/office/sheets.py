"""Add a row to a spreadsheet: "add groceries, 450 to my budget sheet" (ADR-089).

- Open in Excel: the row is written through Excel itself, into the workbook you have open, so
  nothing you typed is lost. Jarvis never saves it: the file on disk changes when you save, and
  closing without saving drops the row. Excel clears its undo history for changes made this
  way, so Ctrl+Z cannot take the row back.
- A closed .xlsx or .xlsm: written with openpyxl after a copy of the file is kept in the data
  folder (`backups\\sheets`), because openpyxl can drop parts it does not understand (images,
  some charts) when it saves.
- A .csv: one line appended, in the file's own delimiter.

Writing always asks first (risk confirm), and the row is read back after it is written.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import logging
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.platform.com import run_com
from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.files.index import FileHit, FileIndex
from jarvis.tools.files.tools import CLEAR_LEAD, locate
from jarvis.tools.registry import tool

log = logging.getLogger(__name__)

SHEET_TYPES = (".xlsx", ".xlsm", ".csv")
MAX_CELLS = 30
MAX_CELL_CHARS = 500
WM_GETOBJECT = 0x003D
OBJID_NATIVEOM = -16  # asks a workbook window for Excel's own object model
_NUMBER = re.compile(r"^-?\d{1,15}(\.\d{1,10})?$")


@dataclass(frozen=True)
class Written:
    row: int
    values: list[Any]
    how: str  # "excel", "file", or "csv"
    sheet: str | None


def cell_value(text: str) -> Any:
    """A number stays a number in the sheet ("450", "12.5", "1,200"); anything else is text."""
    raw = text.strip()
    plain = raw.replace(",", "") if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", raw) else raw
    if _NUMBER.match(plain):
        return float(plain) if "." in plain else int(plain)
    return raw


def _lock_file(path: Path) -> Path:
    return path.with_name(f"~${path.name}")  # Excel's owner file while a workbook is open


# Through Excel (on the COM thread)


def _excel_workbook(path: Path) -> Any | None:
    """The open workbook at `path` in a running Excel, or None.

    pywin32's late binding, not comtypes': Excel's Cells(row, column) is a property with
    arguments, which comtypes' dynamic objects cannot assign to (seen in the live test).
    """
    wanted = str(path).casefold()
    for excel in _running_excels():
        for workbook in excel.Workbooks:
            if str(workbook.FullName).casefold() == wanted:
                return workbook
    return None


def _running_excels() -> list[Any]:
    """Every running Excel: the one in the running object table, and the ones reached through
    their workbook windows. Excel joins that table only after its window first loses focus
    (seen in the live test), so a workbook you just opened is found the second way."""
    import pythoncom
    import pywintypes
    import win32com.client
    import win32gui

    found: list[Any] = []
    with contextlib.suppress(pywintypes.com_error):
        found.append(win32com.client.GetActiveObject("Excel.Application"))

    desks: list[int] = []

    def collect(hwnd: int, _: Any) -> bool:
        if win32gui.GetClassName(hwnd) == "XLMAIN":
            desk = win32gui.FindWindowEx(hwnd, 0, "XLDESK", None)
            sheet = win32gui.FindWindowEx(desk, 0, "EXCEL7", None) if desk else 0
            if sheet:
                desks.append(sheet)
        return True

    win32gui.EnumWindows(collect, None)
    for hwnd in desks:
        try:
            result = win32gui.SendMessage(hwnd, WM_GETOBJECT, 0, OBJID_NATIVEOM)
            if not result:
                continue
            window = pythoncom.ObjectFromLresult(result, pythoncom.IID_IDispatch, 0)
            found.append(win32com.client.Dispatch(window).Application)
        except pywintypes.com_error:
            continue
    return found


def _excel_write(path: Path, values: list[Any], sheet: str | None) -> Written | None:
    workbook = _excel_workbook(path)
    if workbook is None:
        return None
    if sheet:
        names = [str(ws.Name) for ws in workbook.Worksheets]
        if sheet not in names:
            raise ToolError(
                f"{path.name} has no sheet called {sheet}. Its sheets: {', '.join(names)}."
            )
        worksheet = workbook.Worksheets(sheet)
    else:
        worksheet = workbook.ActiveSheet
    used = worksheet.UsedRange
    last = int(used.Row) + int(used.Rows.Count) - 1
    empty = last == 1 and worksheet.Cells(1, 1).Value is None
    row = 1 if empty else last + 1
    for column, value in enumerate(values, start=1):
        worksheet.Cells(row, column).Value = value
    back = [plain(worksheet.Cells(row, c).Value) for c in range(1, len(values) + 1)]
    return Written(row, back, "excel", str(worksheet.Name))


# Closed files


def _backup(path: Path, backups: Path) -> Path:
    backups.mkdir(parents=True, exist_ok=True)
    copy = backups / f"{time.strftime('%Y%m%d-%H%M%S')}-{path.name}"
    shutil.copy2(path, copy)
    return copy


def _xlsx_write(path: Path, values: list[Any], sheet: str | None, backups: Path) -> Written:
    import openpyxl

    keep_vba = path.suffix.casefold() == ".xlsm"
    workbook = openpyxl.load_workbook(path, keep_vba=keep_vba)
    try:
        if sheet:
            if sheet not in workbook.sheetnames:
                names = ", ".join(workbook.sheetnames)
                raise ToolError(f"{path.name} has no sheet called {sheet}. Its sheets: {names}.")
            worksheet = workbook[sheet]
        else:
            worksheet = workbook.active
        empty = worksheet.max_row == 1 and worksheet.cell(1, 1).value is None
        row = 1 if empty else worksheet.max_row + 1
        for column, value in enumerate(values, start=1):
            worksheet.cell(row=row, column=column, value=value)
        copy = _backup(path, backups)
        log.info("Kept a copy of %s at %s before writing", path.name, copy)
        workbook.save(path)
        name = str(worksheet.title)
    finally:
        workbook.close()
    check = openpyxl.load_workbook(path, read_only=True)
    try:
        cells = next(check[name].iter_rows(min_row=row, max_row=row, values_only=True), ())
    finally:
        check.close()
    return Written(row, [plain(c) for c in list(cells)[: len(values)]], "file", name)


def _csv_write(path: Path, values: list[Any]) -> Written:
    text = path.read_text(encoding="utf-8-sig", errors="replace") if path.exists() else ""
    try:
        dialect: Any = csv.Sniffer().sniff(text[:4096]) if text.strip() else csv.excel
    except csv.Error:
        dialect = csv.excel
    rows = text.count("\n") + (0 if not text or text.endswith("\n") else 1)
    line = io.StringIO()
    csv.writer(line, delimiter=dialect.delimiter, lineterminator="\n").writerow(values)
    with path.open("a", encoding="utf-8", newline="") as handle:
        if text and not text.endswith("\n"):
            handle.write("\n")
        handle.write(line.getvalue())
    last = path.read_text(encoding="utf-8-sig").splitlines()[-1]
    back = next(csv.reader([last], delimiter=dialect.delimiter))
    return Written(rows + 1, back, "csv", None)


async def write_row(path: Path, values: list[Any], sheet: str | None, backups: Path) -> Written:
    if path.suffix.casefold() == ".csv":
        return await asyncio.to_thread(_csv_write, path, values)
    written = await run_com(_excel_write, path, values, sheet)
    if written is not None:
        return written
    if await asyncio.to_thread(_lock_file(path).exists):
        raise ToolError(
            f"{path.name} is open in another program (or in Excel under another account), so I "
            "can't write to it now. Close it, or open it in Excel here, and ask again."
        )
    return await asyncio.to_thread(_xlsx_write, path, values, sheet, backups)


async def _sheet_hits(files: FileIndex, query: str) -> list[FileHit]:
    hits = await files.search(query, kind="file", limit=10)
    return [hit for hit in hits if Path(hit.path).suffix.casefold() in SHEET_TYPES]


async def find_sheet(ctx: ToolContext, spoken: str) -> str:
    """The spreadsheet the user means: a real path, or the clear best spreadsheet match."""
    text = spoken.strip().strip('"')
    if Path(text).is_absolute():
        return await locate(ctx, text)
    words = re.sub(r"\b(my|the|sheet|spreadsheet|excel|file|workbook)\b", " ", text, flags=re.I)
    query = " ".join(words.split()) or text
    files = ctx.services.files
    sheets = await _sheet_hits(files, query)
    if not sheets:  # made since the index was built? (seen in the live test) Look once more.
        await files.rebuild()
        sheets = await _sheet_hits(files, query)
    if sheets and (len(sheets) == 1 or sheets[0].score - sheets[1].score >= CLEAR_LEAD):
        return sheets[0].path
    if sheets:
        options = "; ".join(hit.path for hit in sheets[:3])
        raise ToolError(f"'{spoken}' could be {options}. Ask the user which one.")
    raise ToolError(f"No spreadsheet in the allowed folders matches '{spoken}'.")


def plain(value: Any) -> Any:
    """A cell read back as plain data: Excel turns "2026-11-07" into a date, as it does when
    you type it, and hands it over as a date and time with a time zone."""
    if isinstance(value, datetime):
        if (value.hour, value.minute, value.second) == (0, 0, 0):
            return value.date().isoformat()
        return value.replace(tzinfo=None).isoformat(sep=" ", timespec="minutes")
    return value


def _shown(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return "" if value is None else str(value)


@tool(risk=Risk.CONFIRM, sensitivity=Sensitivity.PRIVATE, timeout_s=60)
async def add_sheet_row(
    ctx: ToolContext, file: str, values: list[str], sheet: str | None = None
) -> ToolResult:
    """Add one row at the end of a spreadsheet (Excel .xlsx or .csv), for "add groceries,
    450 to my budget sheet". Asks the user first and reads the row back.

    Args:
        file: The spreadsheet's name as the user said it ("budget"), or a full path.
        values: The cells from left to right, for example ["2026-11-07", "Groceries", "450"].
        sheet: The sheet (tab) name, if the user named one; otherwise the open or first sheet.
    """
    path = Path(file)
    cells = [cell_value(v) for v in values]
    written = await write_row(path, cells, sheet, ctx.settings.data_dir / "backups" / "sheets")
    shown = ", ".join(_shown(v) for v in written.values)
    where = f"row {written.row}" + (f" of {written.sheet}" if written.sheet else "")
    note = " It is not saved yet: save it in Excel to keep it." if written.how == "excel" else ""
    return ToolResult.success(
        data={"file": str(path), "row": written.row, "values": written.values, "via": written.how},
        speech=f"Added to {where} in {path.name}: {shown}.{note}",
    )


@add_sheet_row.preparer
async def _prepare_add_row(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    values = [" ".join(str(v).split()) for v in args["values"]]
    if not values or not any(values):
        raise ToolError("Ask the user what the row should say.")
    if len(values) > MAX_CELLS or any(len(v) > MAX_CELL_CHARS for v in values):
        raise ToolError(f"A row is up to {MAX_CELLS} cells of {MAX_CELL_CHARS} characters.")
    check = ctx.services.files.guard.check(await find_sheet(ctx, args["file"]))
    if check.path.suffix.casefold() not in SHEET_TYPES:
        raise ToolError(f"{check.path.name} is not a spreadsheet (.xlsx, .xlsm, or .csv).")
    if check.risk is Risk.BLOCKED:
        raise ToolError(check.reason or f"{check.path.name} is not allowed.")
    sheet = (args.get("sheet") or "").strip() or None
    if sheet and sheet.casefold() in check.path.stem.casefold():
        sheet = None  # "my budget live sheet": the live test saw sheet="live", part of the name
    cells = " | ".join(values)
    tab = f" (sheet {sheet})" if sheet else ""
    return Prepared(
        args={"file": str(check.path), "values": values, "sheet": sheet},
        summary=f"Add a row to {check.path.name}{tab}: {cells}",
        risk=Risk.CONFIRM,
        reason="it changes a file of yours",
    )
