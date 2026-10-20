import json
import re
import subprocess
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

TOOLS = Path(__file__).resolve().parent
REPORT = TOOLS.parent
REPO = REPORT.parent
ROOT = REPORT

sys.path.insert(0, str(TOOLS))
from build_report import FIGURES, TABLES, TOC  # noqa: E402

DRAFT_HTML = REPORT / "report_draft.html"
FINAL_HTML = REPORT / "report_final.html"
DRAFT_PDF = REPORT / "report_draft.pdf"
FINAL_PDF = REPORT / "RailReserve_MiniProject_DCS.pdf"
ROOT_PDF = REPO / "RailReserve_MiniProject_DCS.pdf"
PAGE_MAP = REPORT / "page_numbers.json"
OVERLAY_PDF = REPORT / "report_overlay.pdf"
CHROME = "google-chrome"
HEADER = "DISTRIBUTED COMPUTING SYSTEM | MINI PROJECT REPORT"
FOOTER = "RailReserve | Final Year B.Tech IT | Page {page} of {total}"


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, cwd=REPO, text=True, capture_output=True)
    if result.returncode:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(f"command failed: {' '.join(cmd)}")


def build_html(mode: str) -> None:
    run([sys.executable, str(TOOLS / "build_report.py"), mode])


def render_pdf(html_path: Path, pdf_path: Path) -> None:
    run([
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        html_path.as_uri(),
    ])


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def page_map(pdf_path: Path) -> dict:
    reader = PdfReader(str(pdf_path))
    pages = [norm(page.extract_text() or "") for page in reader.pages]
    result = {}
    missing = []
    main_start = 5

    for index in range(min(4, len(pages))):
        if pages[index].startswith("Abstract"):
            result["abstract"] = index + 1
            break
    if "abstract" not in result:
        missing.append("Abstract")

    for level, title, key in TOC:
        if key == "abstract":
            continue
        needle = norm(re.sub(r"\*\*|`", "", title))
        found = None
        for index in range(main_start - 1, len(pages)):
            if needle in pages[index]:
                found = index + 1
                break
        if found is None:
            missing.append(title)
        else:
            result[key] = found

    for figure in FIGURES:
        pattern = re.compile(rf"\bFigure\s+{figure['no']}\.\s")
        found = None
        for index in range(main_start - 1, len(pages)):
            if pattern.search(pages[index]):
                found = index + 1
                break
        if found is None:
            missing.append(f"Figure {figure['no']}")
        else:
            result[figure["key"]] = found

    for table in TABLES:
        pattern = re.compile(rf"\bTable\s+{table['no']}\.\s")
        found = None
        for index in range(main_start - 1, len(pages)):
            if pattern.search(pages[index]):
                found = index + 1
                break
        if found is None:
            missing.append(f"Table {table['no']}")
        else:
            result[table["key"]] = found

    result["_main_start"] = main_start
    result["_total_pages"] = len(pages)

    if missing:
        raise SystemExit("page map missing: " + ", ".join(missing))
    if result.get("abstract") != 2:
        raise SystemExit(f"unexpected abstract page: {result.get('abstract')}")
    if result.get("_total_pages") != len(reader.pages):
        raise SystemExit("page count changed while mapping")
    return result


def stamp_pdf(source: Path, output: Path, numbers: dict) -> None:
    reader = PdfReader(str(source))
    total = len(reader.pages)
    width, height = A4

    overlay = canvas.Canvas(str(OVERLAY_PDF), pagesize=A4)
    for index in range(total):
        if index == 0:
            overlay.setStrokeColorRGB(0, 0, 0)
            overlay.setLineWidth(0.8)
            overlay.rect(8 * mm, 8 * mm, width - 16 * mm, height - 16 * mm)
            overlay.setFillColorRGB(0.2, 0.2, 0.2)
            overlay.setFont("Times-Roman", 9)
            overlay.drawRightString(width - 14 * mm, 13 * mm, "1")
        else:
            overlay.setFillColorRGB(0.32, 0.32, 0.32)
            overlay.setFont("Times-Roman", 8)
            overlay.drawRightString(width - 20 * mm, height - 14 * mm, HEADER)
            overlay.setStrokeColorRGB(0.65, 0.65, 0.65)
            overlay.setLineWidth(0.45)
            overlay.line(20 * mm, height - 16.2 * mm, width - 20 * mm, height - 16.2 * mm)
            overlay.setFillColorRGB(0.25, 0.25, 0.25)
            overlay.setFont("Times-Roman", 8.2)
            overlay.drawCentredString(width / 2, 12 * mm, FOOTER.format(page=index + 1, total=total))
        overlay.showPage()
    overlay.save()

    overlay_reader = PdfReader(str(OVERLAY_PDF))
    writer = PdfWriter()
    for page, layer in zip(reader.pages, overlay_reader.pages):
        page.merge_page(layer)
        writer.add_page(page)

    writer.add_metadata({
        "/Title": "Preventing Double Booking in a Railway Reservation System",
        "/Author": "Tony Prajapati, Vedant Patarwale, Pratik Rajput, Ishan Toraskar",
        "/Subject": "DCS FA2 Mini Project Report - RailReserve",
        "/Keywords": "distributed systems, concurrency, idempotency, railway reservation, Postgres",
        "/Creator": "RailReserve report build",
    })

    parents = {}
    for level, title, key in TOC:
        page_number = numbers.get(key)
        if not page_number:
            continue
        if level == 1:
            parents[1] = writer.add_outline_item(title, page_number - 1)
        else:
            writer.add_outline_item(title, page_number - 1, parent=parents.get(1))

    writer.page_mode = "/UseOutlines"
    with output.open("wb") as handle:
        writer.write(handle)


def main() -> None:
    build_html("html")
    render_pdf(DRAFT_HTML, DRAFT_PDF)
    numbers = page_map(DRAFT_PDF)

    for _ in range(2):
        PAGE_MAP.write_text(json.dumps(numbers, indent=2, sort_keys=True) + "\n")
        build_html("html-final")
        render_pdf(FINAL_HTML, FINAL_PDF)
        updated = page_map(FINAL_PDF)
        if updated == numbers:
            break
        numbers = updated
    else:
        raise SystemExit("page map did not stabilise")

    PAGE_MAP.write_text(json.dumps(numbers, indent=2, sort_keys=True) + "\n")
    build_html("docx")
    stamp_pdf(FINAL_PDF, ROOT_PDF, numbers)
    FINAL_PDF.unlink()

    print(ROOT_PDF)
    print(f"pages={numbers['_total_pages']} abstract={numbers['abstract']} main={numbers['_main_start']}")
    print(f"figures={len(FIGURES)} tables={len(TABLES)} toc_entries={len(TOC)}")


if __name__ == "__main__":
    main()
