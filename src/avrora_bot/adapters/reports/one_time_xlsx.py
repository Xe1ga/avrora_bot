"""XLSX-отчёт по разовым посещениям за месяц (ТЗ 3.2 п.4).

Форма и оформление повторяют ручную таблицу клуба
(``tmp/one_time_payment_example.xlsx``), чтобы отчёт бота можно было
класть рядом со старыми файлами без переделки: шапка и итоговые строки —
голубые (Arial 10, полужирный курсив), строки данных — зелёные, колонки
«Дата тренировки | ФИО | Сумма | Казначей (ФИО кто собирал) |
Примечание». Итоги — формулы (см. ``xlsx_style``).
"""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from avrora_bot.adapters.reports import xlsx_style as st
from avrora_bot.application.use_cases.one_time import VisitRow
from avrora_bot.domain.value_objects import MonthPeriod

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
    write_one_time_sheet(wb.active, period, rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path


def write_one_time_sheet(
    ws: Worksheet, period: MonthPeriod, rows: list[VisitRow]
) -> None:
    """Заполняет лист «<Месяц> разовая»."""
    ws.title = st.sheet_title(f'{period.month_name.capitalize()} разовая')

    collectors = sorted(
        {row.collector_name for row in rows if row.collector_name}
    )
    header_row = _TOTAL_ROW + len(collectors) + 1
    first_data_row = header_row + 1
    last_data_row = header_row + len(rows)

    st.merged_band(
        ws,
        _TITLE_ROW,
        1,
        _LAST_COL,
        _TITLE,
        fill=st.CYAN_FILL,
        horizontal='center',
    )
    _write_totals(ws, collectors, first_data_row, last_data_row)
    _write_headers(ws, header_row)
    _write_rows(ws, rows, first_data_row)
    st.set_widths(ws, _COLUMN_WIDTHS)


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
        st.sum_formula('C', first_data_row, last_data_row),
    )
    for offset, name in enumerate(collectors, start=1):
        _write_total_row(
            ws,
            _TOTAL_ROW + offset,
            f'На счету {name}:',
            st.sumif_formula('D', name, 'C', first_data_row, last_data_row),
        )


def _write_total_row(
    ws: Worksheet, row: int, label: str, value: str | int
) -> None:
    """Итоговая строка: подпись на A:B, значение (формула) в C."""
    st.merged_band(ws, row, 1, 2, label, fill=st.CYAN_FILL, horizontal='right')
    cell = ws.cell(row=row, column=_AMOUNT_COL)
    cell.value = value
    st.style_cell(
        cell, st.HEADER_FONT, st.CYAN_FILL, horizontal='center', edges='lrtb'
    )


def _write_headers(ws: Worksheet, header_row: int) -> None:
    """Шапка таблицы.

    У «Казначея» и «Примечания» верхней границы нет — так в образце
    (над ними пустые ячейки без рамки), и отчёт повторяет его один в один.
    """
    for col, name in enumerate(_HEADERS, start=1):
        cell = ws.cell(row=header_row, column=col)
        cell.value = name
        st.style_cell(
            cell,
            st.HEADER_FONT,
            st.CYAN_FILL,
            horizontal='center',
            edges='lrb' if col >= _COLLECTOR_COL else 'lrtb',
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
            st.amount(row.visit.amount),
            row.collector_name,
            row.visit.note,
        )
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=r, column=col)
            cell.value = value
            st.style_cell(
                cell,
                st.ROW_FONT,
                st.GREEN_FILL,
                horizontal='left',
                edges='lrtb',
            )
        ws.cell(row=r, column=1).number_format = st.DATE_FORMAT
        for col in range(_LAST_COL + 1, _FILL_LAST_COL + 1):
            ws.cell(row=r, column=col).fill = st.GREEN_FILL
