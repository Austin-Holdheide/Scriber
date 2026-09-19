"""W12: PDF export - COMPACT timestamped segment list (fpdf2, DejaVu for unicode).

Layout: small header (filename + model + segment count), then every segment as a
tight row: right-aligned gray timestamp | text (speaker bolded via "Name:" prefix).
No full-text wall - the segments ARE the document.
"""""
import logging
from pathlib import Path

log = logging.getLogger("scriber.pdf")


def _fmt(ms) -> str:
    """h:mm:ss when 1h+, else m:ss (saves width)."""
    h, rem = divmod(int(ms or 0), 3600000)
    m, rem = divmod(rem, 60000)
    s = rem // 1000
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _soft_wrap(text: str, max_chars: int) -> str:
    """Break over-long tokens (URLs, base64) so multi_cell never overflows."""
    out = []
    for line in text.split("\n"):
        fixed = []
        for word in line.split(" "):
            while len(word) > max_chars:
                fixed.append(word[:max_chars])
                word = word[max_chars:]
            fixed.append(word)
        out.append(" ".join(fixed))
    return "\n".join(out)


def export_pdf(video, transcript, segments, dest: Path) -> Path:
    from fpdf import FPDF

    FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(10, 8, 10)
    pdf.set_auto_page_break(auto=True, margin=10)
    pdf.add_page()
    pdf.set_title("Scriber transcript")

    pdf.add_font("DejaVu", "", str(FONT_DIR / "DejaVuSans.ttf"))
    pdf.add_font("DejaVu", "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
    epw = pdf.epw

    # ---- compact header: 2 lines ----
    pdf.set_font("DejaVu", "B", 12)
    pdf.multi_cell(epw, 5.2, _soft_wrap(video["filename"], 140))
    pdf.set_font("DejaVu", "", 7.5)
    pdf.set_text_color(120)
    pdf.multi_cell(epw, 3.4, f"model: {transcript.get('model') or '?'} | {len(segments)} segments")
    pdf.set_text_color(0)
    pdf.ln(1.2)

    # ---- segment rows ----
    ts_col = 15          # mm for the right-aligned timestamp
    text_w = epw - ts_col - 1.5
    max_chars = max(24, int(text_w / 0.14))  # conservative for 8pt DejaVu

    for s in segments:
        body = (s.get("text") or "").replace("\n", " ").strip()
        if not body:
            continue
        spk = s.get("speaker")
        if spk:
            body = f"{spk}: {body}"
        body = _soft_wrap(body, max_chars)

        # keep timestamp + at least the first text line on the same page
        if pdf.get_y() > pdf.page_break_trigger - 8:
            pdf.add_page()

        pdf.set_font("DejaVu", "", 7)
        pdf.set_text_color(130)
        pdf.set_x(pdf.l_margin)
        pdf.cell(ts_col, 3.3, _fmt(s.get("start_ms")), align="R")

        pdf.set_x(pdf.l_margin + ts_col + 1.5)
        pdf.set_text_color(0)
        pdf.set_font("DejaVu", "", 8)
        try:
            pdf.multi_cell(text_w, 3.3, body)
        except Exception:
            # absolute last resort: hard chop
            pdf.multi_cell(text_w, 3.3, body[:8000])

    tmp = dest.with_suffix(".pdf.tmp")
    pdf.output(str(tmp))
    tmp.replace(dest)
    log.info("pdf written: %s (%d segments, %d pages)", dest.name, len(segments), len(pdf.pages))
    return dest
