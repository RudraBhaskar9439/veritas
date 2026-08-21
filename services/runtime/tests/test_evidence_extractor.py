import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from veritas_runtime.changes.extractor import EvidenceExtractionError, GoogleEvidenceExtractor
from veritas_runtime.changes.models import EvidenceSourceRegistration
from veritas_runtime.packets.models import SourceKind

NOW = datetime(2026, 8, 21, 1, 0, tzinfo=UTC)


def _registration(kind: SourceKind, anchor: str) -> EvidenceSourceRegistration:
    return EvidenceSourceRegistration(
        subject="subject-1",
        packet_id="packet-1",
        source_id="source-1",
        kind=kind,
        resource_id="resource/1",
        anchor=anchor,
        registered_at=NOW,
    )


def test_google_extractor_reads_unformatted_sheet_value_and_presentation() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "/drive/" in request.url.path:
            return httpx.Response(200, json={"version": "42"})
        if "/values/" in request.url.path:
            return httpx.Response(200, json={"values": [[0.04]]})
        return httpx.Response(
            200,
            json={
                "sheets": [
                    {
                        "properties": {"sheetId": 0, "title": "Metrics"},
                        "data": [{"rowData": [{"values": [{"formattedValue": "4%"}]}]}],
                    }
                ]
            },
        )

    async def scenario() -> None:
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        extractor = GoogleEvidenceExtractor(
            http,
            drive_root="https://api.test/drive/v3",
            sheets_root="https://api.test/sheets/v4",
            docs_root="https://api.test/docs/v1",
        )
        capture = await extractor.extract(
            "access", _registration(SourceKind.GOOGLE_SHEET, "Metrics!B17")
        )
        assert capture.workspace_version == "42"
        assert capture.evidence == {"Metrics!B17": 0.04}
        assert capture.presentation["Metrics!B17"]["sheets"][0]["data"]  # type: ignore[index]
        await http.aclose()

    asyncio.run(scenario())
    value_request = next(request for request in requests if "/values/" in request.url.path)
    assert value_request.url.params["valueRenderOption"] == "UNFORMATTED_VALUE"
    assert "resource%2F1" in str(value_request.url)


def test_google_extractor_resolves_exact_docs_named_range() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/drive/" in request.url.path:
            return httpx.Response(200, json={"version": 9})
        return httpx.Response(
            200,
            json={
                "revisionId": "revision-1",
                "namedRanges": {
                    "launch-date": {
                        "namedRanges": [{"ranges": [{"startIndex": 13, "endIndex": 23}]}]
                    }
                },
                "body": {
                    "content": [
                        {
                            "paragraph": {
                                "elements": [
                                    {
                                        "startIndex": 1,
                                        "endIndex": 25,
                                        "textRun": {
                                            "content": "The date is October 15.\n",
                                            "textStyle": {"bold": True},
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                },
            },
        )

    async def scenario() -> None:
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        extractor = GoogleEvidenceExtractor(
            http,
            drive_root="https://api.test/drive/v3",
            sheets_root="https://api.test/sheets/v4",
            docs_root="https://api.test/docs/v1",
        )
        capture = await extractor.extract(
            "access", _registration(SourceKind.GOOGLE_DOC, "launch-date")
        )
        assert capture.evidence == {"launch-date": "October 15"}
        assert capture.presentation["launch-date"]["segments"][0]["textStyle"] == {  # type: ignore[index]
            "bold": True
        }
        await http.aclose()

    asyncio.run(scenario())


def test_google_extractor_fails_closed_for_empty_or_unanchored_evidence() -> None:
    sheet_responses = iter(
        [
            httpx.Response(200, json={"version": 1}),
            httpx.Response(200, json={"values": []}),
        ]
    )

    async def sheet_scenario() -> None:
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: next(sheet_responses))
        )
        extractor = GoogleEvidenceExtractor(http, "https://api/drive", "https://api/sheets")
        with pytest.raises(EvidenceExtractionError, match="is empty"):
            await extractor.extract("access", _registration(SourceKind.GOOGLE_SHEET, "Metrics!B17"))
        await http.aclose()

    asyncio.run(sheet_scenario())

    doc_responses = iter(
        [
            httpx.Response(200, json={"version": 1}),
            httpx.Response(200, json={"body": {"content": []}}),
        ]
    )

    async def doc_scenario() -> None:
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: next(doc_responses))
        )
        extractor = GoogleEvidenceExtractor(http, "https://api/drive", docs_root="https://api/docs")
        with pytest.raises(EvidenceExtractionError, match="was not found"):
            await extractor.extract("access", _registration(SourceKind.GOOGLE_DOC, "launch-date"))
        await http.aclose()

    asyncio.run(doc_scenario())
