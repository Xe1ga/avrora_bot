"""XLSX-отчёт по разовым посещениям за месяц (ТЗ 3.2 п.4).

Форма и оформление повторяют ручную таблицу клуба
(``tmp/one_time_payment_example.xlsx``), чтобы отчёт бота можно было
класть рядом со старыми файлами без переделки: шапка и итоговые строки —
голубые (Arial 10, полужирный курсив), строки данных — зелёные, колонки
«Дата тренировки | ФИО | Сумма | Казначей (ФИО кто собирал) |
Примечание».

Итоги — не посчитанные числа, а формулы Excel (``SUM``/``SUMIF``): файл
продолжают вести руками, дописывая строки, и суммы должны пересчитываться
сами, как в исходной таблице.
"""

from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.worksheet import Worksheet

from avrora_bot.application.use_cases.one_time import VisitRow
from avrora_bot.domain.value_objects import MonthPeriod

# Цвета — в формате ARGB, как в образце: голубая шапка и зелёные строки.
_HEADER_FILL = PatternFill('solid', fgColor='FF00FFFF')
_ROW_FILL = PatternFill('solid', fgColor='FF00FF00')
_HEADER_FONT = Font(name='Arial', size=10, bold=True, italic=True)
_ROW_FONT = Font(name='Arial', size=10)
_THIN = Side(style='thin')
_NO_SIDE = Side()
_DATE_FORMAT = 'dd.mm.yyyy'

_TITLE = 'Разовая оплата'
_TOTAL_LABEL = 'ИТОГО:'
_HEADERS = (
    'Дата тренировки',
    'ФИО',
    'Сумма',
    'Казначей (ФИО кто собирал)',
    'Примечание',
)
_COLUMN_WIDTHS = {
    'A': 18.33203125,
    'B': 31.77734375,
    'C': 21.0,
    'D': 28.88671875,
    'E': 32.44140625,
}
# Последняя колонка таблицы (E, «Примечание») и последняя колонка заливки:
# в образце зелёный фон строки тянется до конца видимой области листа.
_LAST_COL = 5
_FILL_LAST_COL = 26
_AMOUNT_COL = 3
_COLLECTOR_COL = 4

_TITLE_ROW = 1
_TOTAL_ROW = 2


def build_one_time_report(
    period: MonthPeriod, rows: list[VisitRow], out_path: Path
) -> Path:
    """Создаёт XLSX-отчёт по разовым посещениям и возвращает путь к нему.

    :param rows: посещения месяца в порядке вывода — см.
        ``OneTimeUseCases.month_visits``.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = f'{period.month_name.capitalize()} разовая'

    collectors = sorted(
        {row.collector_name for row in rows if row.collector_name}
    )
    header_row = _TOTAL_ROW + len(collectors) + 1
    first_data_row = header_row + 1
    last_data_row = header_row + len(rows)

    _write_title(ws)
    _write_totals(ws, collectors, first_data_row, last_data_row)
    _write_headers(ws, header_row)
    _write_rows(ws, rows, first_data_row)

    for column, width in _COLUMN_WIDTHS.items():
        ws.column_dimensions[column].width = width

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path


def _write_title(ws: Worksheet) -> None:
    """Заголовок «Разовая оплата» на всю ширину таблицы (A:E)."""
    ws.merge_cells(
        start_row=_TITLE_ROW,
        start_column=1,
        end_row=_TITLE_ROW,
        end_column=_LAST_COL,
    )
    ws.cell(row=_TITLE_ROW, column=1).value = _TITLE
    _style_merged_band(ws, _TITLE_ROW, 1, _LAST_COL, horizontal='center')


def _write_totals(
    ws: Worksheet,
    collectors: list[str],
    first_data_row: int,
    last_data_row: int,
) -> None:
    """Строка «ИТОГО» и по строке на каждого казначея месяца.

    Казначеи берутся из самих данных: сколько разных ФИО в колонке
    «Казначей», столько строк «На счету ...» — в образце их две, но состав
    сборщиков со временем меняется.
    """
    _write_total_row(
        ws,
        _TOTAL_ROW,
        _TOTAL_LABEL,
        _sum_formula(first_data_row, last_data_row),
    )
    for offset, name in enumerate(collectors, start=1):
        _write_total_row(
            ws,
            _TOTAL_ROW + offset,
            f'На счету {name}:',
            _sumif_formula(name, first_data_row, last_data_row),
        )


def _write_total_row(
    ws: Worksheet, row: int, label: str, value: str | int
) -> None:
    """Итоговая строка: подпись на A:B, значение (формула) в C."""
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
    ws.cell(row=row, column=1).value = label
    _style_merged_band(ws, row, 1, 2, horizontal='right')
    amount = ws.cell(row=row, column=_AMOUNT_COL)
    amount.value = value
    _style_cell(
        amount,
        _HEADER_FONT,
        _HEADER_FILL,
        horizontal='center',
        edges='lrtb',
    )


def _write_headers(ws: Worksheet, header_row: int) -> None:
    """Шапка таблицы.

    У «Казначея» и «Примечания» верхней границы нет — так в образце
    (над ними пустые ячейки без рамки), и отчёт повторяет его один в один.
    """
    for column, name in enumerate(_HEADERS, start=1):
        cell = ws.cell(row=header_row, column=column)
        cell.value = name
        _style_cell(
            cell,
            _HEADER_FONT,
            _HEADER_FILL,
            horizontal='center',
            edges='lrb' if column >= _COLLECTOR_COL else 'lrtb',
        )


def _write_rows(
    ws: Worksheet, rows: list[VisitRow], first_data_row: int
) -> None:
    """Строки посещений: дата, ФИО, сумма, казначей, примечание."""
    for offset, row in enumerate(rows):
        r = first_data_row + offset
        values = (
            row.visit.visit_date,
            row.full_name,
            _amount(row.visit.amount),
            row.collector_name,
            row.visit.note,
        )
        for column, value in enumerate(values, start=1):
            cell = ws.cell(row=r, column=column)
            cell.value = value
            _style_cell(
                cell, _ROW_FONT, _ROW_FILL, horizontal='left', edges='lrtb'
            )
        ws.cell(row=r, column=1).number_format = _DATE_FORMAT
        for column in range(_LAST_COL + 1, _FILL_LAST_COL + 1):
            ws.cell(row=r, column=column).fill = _ROW_FILL


def _style_merged_band(
    ws: Worksheet, row: int, first_col: int, last_col: int, *, horizontal: str
) -> None:
    """Оформляет объединённый диапазон одной строки.

    Рамку получает каждая ячейка диапазона (иначе Excel нарисует её только
    вокруг левой ячейки), заливку и шрифт — тоже: объединение показывает
    стиль левой верхней ячейки, но границы берёт с краёв диапазона.
    """
    for column in range(first_col, last_col + 1):
        edges = 'lrtb' if column == first_col else 'tb'
        if column == last_col:
            edges = 'rtb'
        _style_cell(
            ws.cell(row=row, column=column),
            _HEADER_FONT,
            _HEADER_FILL if column == first_col else None,
            horizontal=horizontal if column == first_col else None,
            edges=edges,
        )


def _style_cell(
    cell: Cell | MergedCell,
    font: Font,
    fill: PatternFill | None,
    *,
    horizontal: str | None,
    edges: str,
) -> None:
    cell.font = font
    if fill is not None:
        cell.fill = fill
    if horizontal is not None:
        cell.alignment = Alignment(horizontal=horizontal)
    cell.border = Border(
        left=_THIN if 'l' in edges else _NO_SIDE,
        right=_THIN if 'r' in edges else _NO_SIDE,
        top=_THIN if 't' in edges else _NO_SIDE,
        bottom=_THIN if 'b' in edges else _NO_SIDE,
    )


def _sum_formula(first_data_row: int, last_data_row: int) -> str | int:
    """``=SUM(C6:C34)`` — или 0, если за месяц нет ни одного посещения."""
    if last_data_row < first_data_row:
        return 0
    return f'=SUM(C{first_data_row}:C{last_data_row})'


def _sumif_formula(name: str, first_data_row: int, last_data_row: int) -> str:
    """``=SUMIF(D6:D34, "ФИО", C6:C34)`` — сколько собрал этот казначей."""
    # Кавычка внутри ФИО закрыла бы строковый литерал формулы — в Excel она
    # экранируется удвоением.
    escaped = name.replace('"', '""')
    return (
        f'=SUMIF(D{first_data_row}:D{last_data_row}, "{escaped}", '
        f'C{first_data_row}:C{last_data_row})'
    )


def _amount(amount: Decimal) -> int | float:
    """Сумма числом: целые рубли — как в образце, без лишних «.00»."""
    return (
        int(amount) if amount == amount.to_integral_value() else float(amount)
    )
