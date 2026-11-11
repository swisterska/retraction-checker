
import requests
import pytest

from app.services import grobid
from app.services.grobid import GrobidServiceError, parse_references


VALID_TEI = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
    <text>
        <listBibl>
            <biblStruct>
                <analytic>
                    <title>Test publication</title>
                </analytic>
            </biblStruct>
        </listBibl>
    </text>
</TEI>
"""


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)


def test_parse_references_returns_tei_xml(tmp_path, monkeypatch):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-test")

    def fake_post(url, files, timeout):
        assert url == grobid.GROBID_URL
        assert "input" in files
        assert timeout == grobid.GROBID_TIMEOUT
        return FakeResponse(VALID_TEI)

    monkeypatch.setattr(grobid.requests, "post", fake_post)

    result = parse_references(str(pdf))

    assert result == VALID_TEI.strip()


def test_parse_references_raises_for_missing_file():
    with pytest.raises(FileNotFoundError):
        parse_references("/nonexistent/test.pdf")


def test_parse_references_handles_timeout(tmp_path, monkeypatch):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-test")

    def fake_post(*args, **kwargs):
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(grobid.requests, "post", fake_post)

    with pytest.raises(GrobidServiceError, match="timed out"):
        parse_references(str(pdf))


def test_parse_references_handles_connection_error(tmp_path, monkeypatch):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-test")

    def fake_post(*args, **kwargs):
        raise requests.exceptions.ConnectionError()

    monkeypatch.setattr(grobid.requests, "post", fake_post)

    with pytest.raises(GrobidServiceError, match="Cannot connect"):
        parse_references(str(pdf))


def test_parse_references_handles_http_error(tmp_path, monkeypatch):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-test")

    monkeypatch.setattr(
        grobid.requests,
        "post",
        lambda *args, **kwargs: FakeResponse("", status_code=503),
    )

    with pytest.raises(GrobidServiceError, match="HTTP error 503"):
        parse_references(str(pdf))


def test_parse_references_retries_empty_response(tmp_path, monkeypatch):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-test")

    responses = iter([FakeResponse("   "), FakeResponse(VALID_TEI)])
    monkeypatch.setattr(
        grobid.requests,
        "post",
        lambda *args, **kwargs: next(responses),
    )
    monkeypatch.setattr(grobid.time, "sleep", lambda *_args, **_kwargs: None)

    result = parse_references(str(pdf))

    assert result == VALID_TEI.strip()


def test_parse_references_rejects_empty_response(tmp_path, monkeypatch):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-test")

    monkeypatch.setattr(
        grobid.requests,
        "post",
        lambda *args, **kwargs: FakeResponse("   "),
    )

    with pytest.raises(GrobidServiceError, match="empty response"):
        parse_references(str(pdf))


def test_parse_references_uses_fulltext_fallback_after_empty_responses(
    tmp_path,
    monkeypatch,
):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-test")
    responses = iter(
        [
            FakeResponse("", status_code=204),
            FakeResponse("", status_code=204),
            FakeResponse("", status_code=204),
            FakeResponse(VALID_TEI),
        ]
    )
    requested_urls = []

    def fake_post(url, **_kwargs):
        requested_urls.append(url)
        return next(responses)

    monkeypatch.setattr(grobid.requests, "post", fake_post)
    monkeypatch.setattr(grobid.time, "sleep", lambda *_args: None)

    result = parse_references(str(pdf))

    assert result == VALID_TEI.strip()
    assert requested_urls == [
        grobid.GROBID_URL,
        grobid.GROBID_URL,
        grobid.GROBID_URL,
        grobid.GROBID_FULLTEXT_URL,
    ]


def test_parse_references_rejects_invalid_xml(tmp_path, monkeypatch):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-test")

    monkeypatch.setattr(
        grobid.requests,
        "post",
        lambda *args, **kwargs: FakeResponse("<TEI><broken>"),
    )

    with pytest.raises(GrobidServiceError, match="invalid XML"):
        parse_references(str(pdf))


def test_parse_references_rejects_unexpected_xml_root(tmp_path, monkeypatch):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-test")

    monkeypatch.setattr(
        grobid.requests,
        "post",
        lambda *args, **kwargs: FakeResponse("<html>Unavailable</html>"),
    )

    with pytest.raises(GrobidServiceError, match="Expected 'TEI'"):
        parse_references(str(pdf))
