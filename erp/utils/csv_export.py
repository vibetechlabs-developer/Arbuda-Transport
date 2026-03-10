import csv
from datetime import date, datetime
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from django.http import HttpResponse


def _to_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        # Excel: avoid "#######" caused by narrow columns + date/number formatting
        # by exporting dates as TEXT (leading apostrophe is hidden by Excel).
        if isinstance(value, datetime):
            return "'" + value.strftime("%d-%m-%Y %H:%M:%S")
        return "'" + value.strftime("%d-%m-%Y")
    return str(value)


def csv_response(
    *,
    filename: str,
    header: Sequence[str],
    rows: Iterable[Sequence[object]],
) -> HttpResponse:
    """
    Return a text/csv HttpResponse with UTF-8 BOM (better Excel compatibility).
    """
    if not filename.lower().endswith(".csv"):
        filename = f"{filename}.csv"

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    # UTF-8 BOM so Excel opens UTF-8 correctly
    response.write("\ufeff")

    writer = csv.writer(response)
    writer.writerow(list(header))
    for row in rows:
        writer.writerow([_to_str(v) for v in row])
    return response


def dict_rows_to_csv_response(
    *,
    filename: str,
    columns: Sequence[Tuple[str, str]],
    dict_rows: Iterable[Mapping[str, object]],
) -> HttpResponse:
    """
    columns: list of (key, label)
    dict_rows: iterable of dict-like rows
    """
    header = [label for _, label in columns]
    rows = ([row.get(key, "") for key, _ in columns] for row in dict_rows)
    return csv_response(filename=filename, header=header, rows=rows)

