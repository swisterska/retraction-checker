"""Build a small, dependency-free PDF summary for guest email delivery."""

import textwrap
import unicodedata


def _pdf_text(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap(value, width=88):
    return textwrap.wrap(str(value or ""), width=width) or [""]


def create_guest_report_pdf(report):
    """Return a readable multi-page PDF containing only extracted findings."""
    document = report.get("document") or {}
    lines = [
        "RETRACTION CHECKER - GUEST REPORT",
        "",
        f"Document: {document.get('filename', 'Uploaded paper')}",
        f"References checked: {report.get('total_references', len(report.get('results', [])))}",
        f"Retractions found: {report.get('retracted_references', 0)}",
        "",
        "This report summarizes reference checks. Review the source details before citing.",
        "",
    ]
    for number, item in enumerate(report.get("results", []), start=1):
        status = item.get("verification_status") or "not_verified"
        title = item.get("title") or "Untitled reference"
        lines.extend(_wrap(f"{number}. {title}"))
        authors = item.get("authors")
        byline = " · ".join(str(part) for part in (authors, item.get("year")) if part)
        if byline:
            lines.extend(_wrap(byline))
        doi = item.get("doi") or "Missing DOI"
        lines.extend(_wrap(f"DOI: {doi}"))
        lines.extend(_wrap(f"Status: {status.replace('_', ' ').title()}"))
        note = item.get("verification_note")
        if note:
            lines.extend(_wrap(f"Note: {note}"))
        publication = item.get("retracted_publication") or {}
        reason = publication.get("retraction_reason")
        if reason:
            lines.extend(_wrap(f"Retraction notice: {reason}"))
        lines.append("")

    page_chunks = [lines[index:index + 52] for index in range(0, len(lines), 52)] or [[]]
    objects = [b"", b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    page_ids = []
    for index in range(len(page_chunks)):
        page_ids.append(4 + index * 2)
    objects[2] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] "
        f"/Count {len(page_ids)} >>"
    ).encode("ascii")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for index, chunk in enumerate(page_chunks):
        page_id = page_ids[index]
        content_id = page_id + 1
        commands = ["BT", "/F1 10 Tf", "50 790 Td", "14 TL"]
        for line in chunk:
            commands.append(f"({_pdf_text(line)}) Tj T*")
        commands.append("ET")
        stream = "\n".join(commands).encode("ascii")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        .encode("ascii"))
        objects.append(
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
            + stream + b"\nendstream"
        )

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, body in enumerate(objects[1:], start=1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)
