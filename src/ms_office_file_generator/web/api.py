"""JSON API router for programmatic file generation (ADR-007).

A machine-friendly surface over the same core the UI uses. Generate endpoints
take a typed JSON body and stream the file bytes back; ``fill`` takes a multipart
template + config and streams the filled file with the injection report in the
``X-Injection-Report`` header. Generation errors surface as ``400`` with a JSON
``detail``; invalid bodies surface as Pydantic's ``422``.

The router holds no generation logic: it validates, calls the shared service
(:mod:`ms_office_file_generator.web.service`), and returns the bytes.
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response, UploadFile
from fastapi.responses import JSONResponse

from ms_office_file_generator.core import ConfigError, generate
from ms_office_file_generator.web import service
from ms_office_file_generator.web.schemas import (
    DeckRequest,
    DocRequest,
    SectionRequest,
    SheetRequest,
)

_REPORT_HEADER = "X-Injection-Report"


def create_api_router(*, max_upload_bytes: int) -> APIRouter:
    """Build the ``/api`` router. ``max_upload_bytes`` caps fill-mode uploads."""
    from ms_office_file_generator.web.app import (
        _CONFIG_EXTS,
        _TEMPLATE_EXTS,
        _save_upload,
        _UploadError,
        _video_default,
    )

    router = APIRouter(prefix="/api", tags=["generate"])

    def _stream(kind_key: str, **params: object) -> Response:
        kind = service.file_kind(kind_key)
        try:
            data = service.generate_bytes(kind, **params)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(
            content=data,
            media_type=kind.media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{kind.download_name}"'
            },
        )

    @router.post("/generate/deck")
    def api_deck(body: DeckRequest) -> Response:
        return _stream(
            "deck",
            complexity=body.complexity.value,
            slides=body.slides,
            seed=body.seed,
            video_url=body.video_url or _video_default(),
            background=body.background,
            background_color=body.background_color or None,
        )

    @router.post("/generate/doc")
    def api_doc(body: DocRequest) -> Response:
        return _stream(
            "doc",
            complexity=body.complexity.value,
            sections=body.sections,
            seed=body.seed,
            blocks_per_section=body.blocks_per_section,
        )

    @router.post("/generate/sheet")
    def api_sheet(body: SheetRequest) -> Response:
        return _stream(
            "sheet",
            complexity=body.complexity.value,
            sheets=body.sheets,
            seed=body.seed,
            rows=body.rows,
            cols=body.cols,
        )

    @router.post("/generate/pdf")
    def api_pdf(body: SectionRequest) -> Response:
        return _stream(
            "pdf",
            complexity=body.complexity.value,
            sections=body.sections,
            seed=body.seed,
            blocks_per_section=body.blocks_per_section,
        )

    @router.post("/generate/markdown")
    def api_markdown(body: SectionRequest) -> Response:
        return _stream(
            "markdown",
            complexity=body.complexity.value,
            sections=body.sections,
            seed=body.seed,
            blocks_per_section=body.blocks_per_section,
        )

    @router.post("/generate/fill")
    async def api_fill(
        template: UploadFile,
        config: UploadFile,
        include_report: bool = False,
    ) -> Response:
        with tempfile.TemporaryDirectory(prefix="mofg-api-fill-") as tmp:
            workdir = Path(tmp)
            try:
                template_path = await _save_upload(
                    template, workdir, _TEMPLATE_EXTS, max_upload_bytes
                )
                config_path = await _save_upload(
                    config, workdir, _CONFIG_EXTS, max_upload_bytes
                )
            except _UploadError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            out = workdir / f"filled{template_path.suffix}"
            try:
                report = generate(template_path, config_path, out)
            except (ConfigError, FileNotFoundError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            data = out.read_bytes()

        filename = f"filled{template_path.suffix}"
        rendered = report.render()
        # Default: stream the bytes, with a one-line (newline-folded) summary in a
        # header. ``?include_report=true``: return JSON carrying the full
        # multi-line report and the file base64-encoded, for callers that need the
        # structured report a header cannot hold.
        if include_report:
            return JSONResponse(
                {
                    "filename": filename,
                    "report": rendered,
                    "file_base64": base64.b64encode(data).decode("ascii"),
                }
            )
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                _REPORT_HEADER: _header_safe(rendered),
            },
        )

    return router


def _header_safe(text: str) -> str:
    """Collapse a multi-line report into a single header-safe value.

    HTTP header values cannot contain raw newlines, so the streaming response
    folds the report to one line. Callers needing the full structured report pass
    ``?include_report=true`` to get it as a JSON field instead.
    """
    return " ".join(text.split())
