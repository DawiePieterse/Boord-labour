"""xlsx downloads. Adapted from Boord's excel_io.py: headers + rows in,
bytes out, so routers supply plain Python data."""
import io

from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def sheets_to_xlsx_bytes(sheets: list) -> bytes:
    """`sheets`: [(title, headers, rows)], one worksheet each, in order."""
    wb = Workbook()
    wb.remove(wb.active)
    for title, headers, rows in sheets:
        ws = wb.create_sheet(title[:31])  # Excel sheet name limit
        ws.append(headers)
        for row in rows:
            ws.append(row)
        for i, header in enumerate(headers, start=1):
            width = max([len(str(header))] + [len(str(r[i - 1])) for r in rows])
            ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 10), 40)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def xlsx_response(sheets: list, filename: str) -> Response:
    """`filename` has no extension."""
    return Response(content=sheets_to_xlsx_bytes(sheets), media_type=XLSX_MEDIA,
                    headers={"Content-Disposition": f'attachment; filename="{filename}.xlsx"'})

