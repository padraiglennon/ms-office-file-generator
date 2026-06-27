"""FastAPI app: deck + fill forms, generation, and download delivery.

The web layer holds no generation logic. It validates the request, calls the
core (``generate_deck`` / ``generate``), writes the result to a temp file keyed
by an opaque token, and renders an HTMX partial with a download link.
"""

from __future__ import annotations

import os
import secrets
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from common_file_generator.core import ConfigError, Report, generate
from common_file_generator.web import service
from common_file_generator.web.caps import Caps
from common_file_generator.web.forms import (
    deck_fields,
    doc_fields,
    md_fields,
    pdf_fields,
    sheet_fields,
)
from common_file_generator.web.service import GenerationTimeout, OutputTooLarge

_HERE = Path(__file__).parent
_TEMPLATE_EXTS = {".pptx", ".docx", ".xlsx"}
_CONFIG_EXTS = {".json"}
_DEFAULT_MAX_UPLOAD_MB = 25
_DEFAULT_TTL_SECONDS = 3600  # generated files are swept after one hour
_UPLOAD_CHUNK = 64 * 1024
# Hosted documentation site (GitHub Pages). Overridable for forks/mirrors.
_DOCS_URL = "https://padraiglennon.github.io/common-file-generator/"


@dataclass
class _Artifact:
    """A generated file awaiting download."""

    path: Path
    filename: str
    created_at: float


def create_app(
    *,
    max_upload_mb: int = _DEFAULT_MAX_UPLOAD_MB,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    caps: Caps | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    ``max_upload_mb`` caps fill-mode uploads; ``ttl_seconds`` is how long a
    generated file is kept before it is swept on the next request. ``caps``
    carries the ADR-010 resource caps and runtime guards; it defaults to values
    resolved from the environment.
    """
    caps = caps or Caps.from_env()
    docs_url = os.getenv("COMMON_FILE_GEN_DOCS_URL", _DOCS_URL)
    app = FastAPI(title="Common File Generator")
    templates = Jinja2Templates(directory=str(_HERE / "templates"))
    app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

    workdir = Path(tempfile.mkdtemp(prefix="cfg-web-"))
    artifacts: dict[str, _Artifact] = {}
    max_upload_bytes = max_upload_mb * 1024 * 1024

    def _sweep() -> None:
        cutoff = time.monotonic() - ttl_seconds
        for token in [t for t, a in artifacts.items() if a.created_at < cutoff]:
            artifact = artifacts.pop(token)
            artifact.path.unlink(missing_ok=True)

    def _store(path: Path, filename: str) -> str:
        _sweep()
        token = secrets.token_urlsafe(16)
        artifacts[token] = _Artifact(
            path=path, filename=filename, created_at=time.monotonic()
        )
        return token

    asset_version = secrets.token_hex(4)  # busts the CSS cache each server start

    @app.get("/health")
    def health() -> dict[str, str]:
        # Lightweight readiness probe for the container HEALTHCHECK and CI polling.
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "deck_fields": deck_fields(),
                "doc_fields": doc_fields(),
                "sheet_fields": sheet_fields(),
                "pdf_fields": pdf_fields(),
                "md_fields": md_fields(),
                "max_upload_mb": max_upload_mb,
                "version": asset_version,
                "docs_url": docs_url,
            },
        )

    def _generate(request: Request, kind_key: str, **params: object) -> HTMLResponse:
        # Run the shared service into the per-request workdir, store the result
        # under a token, and render the download partial. The kind's MIME and
        # download name come from the service, so UI and API stay in lockstep.
        kind = service.file_kind(kind_key)
        scratch = workdir / f"{kind.key}-{secrets.token_hex(4)}"
        scratch.mkdir()
        try:
            out = service.generate_to_path(kind, scratch, caps, **params)
        except GenerationTimeout as exc:
            return _error(templates, request, str(exc), status_code=503)
        except (OutputTooLarge, ValueError, FileNotFoundError) as exc:
            return _error(templates, request, str(exc))

        token = _store(out, kind.download_name)
        return _result(templates, request, token, kind.download_name, report=None)

    @app.post("/generate/deck", response_class=HTMLResponse)
    def generate_deck_route(
        request: Request,
        complexity: str = Form("standard"),
        slides: int = Form(10),
        seed: int = Form(0),
        background: str = Form("none"),
        background_color: str = Form(""),
        video_url: str = Form(""),
    ) -> HTMLResponse:
        # "custom" is a UI-only choice: it means "use this exact colour", which the
        # core expresses as background mode none + an explicit background_color.
        if background == "custom":
            background = "none"
        else:
            background_color = ""

        return _generate(
            request,
            "deck",
            complexity=complexity,
            slides=slides,
            seed=seed,
            background=background,
            background_color=background_color or None,
            video_url=video_url or _video_default(),
        )

    @app.post("/generate/doc", response_class=HTMLResponse)
    def generate_doc_route(
        request: Request,
        complexity: str = Form("standard"),
        sections: int = Form(5),
        seed: int = Form(0),
    ) -> HTMLResponse:
        return _generate(
            request, "doc", complexity=complexity, sections=sections, seed=seed
        )

    @app.post("/generate/sheet", response_class=HTMLResponse)
    def generate_sheet_route(
        request: Request,
        complexity: str = Form("standard"),
        sheets: int = Form(3),
        seed: int = Form(0),
    ) -> HTMLResponse:
        return _generate(
            request, "sheet", complexity=complexity, sheets=sheets, seed=seed
        )

    @app.post("/generate/pdf", response_class=HTMLResponse)
    def generate_pdf_route(
        request: Request,
        complexity: str = Form("standard"),
        sections: int = Form(5),
        seed: int = Form(0),
    ) -> HTMLResponse:
        return _generate(
            request, "pdf", complexity=complexity, sections=sections, seed=seed
        )

    @app.post("/generate/md", response_class=HTMLResponse)
    def generate_markdown_route(
        request: Request,
        complexity: str = Form("standard"),
        sections: int = Form(5),
        seed: int = Form(0),
    ) -> HTMLResponse:
        return _generate(
            request, "markdown", complexity=complexity, sections=sections, seed=seed
        )

    @app.post("/generate/fill", response_class=HTMLResponse)
    async def generate_fill_route(
        request: Request,
        template: UploadFile,
        config: UploadFile,
    ) -> HTMLResponse:
        try:
            template_path = await _save_upload(
                template, workdir, _TEMPLATE_EXTS, max_upload_bytes
            )
            config_path = await _save_upload(
                config, workdir, _CONFIG_EXTS, max_upload_bytes
            )
        except _UploadError as exc:
            return _error(templates, request, str(exc))

        out = workdir / f"filled-{secrets.token_hex(4)}{template_path.suffix}"
        report_box: dict[str, Report] = {}

        def _build() -> Path:
            report_box["report"] = generate(template_path, config_path, out)
            return out

        try:
            service.run_guarded(_build, caps)
        except GenerationTimeout as exc:
            return _error(templates, request, str(exc), status_code=503)
        except (OutputTooLarge, ConfigError, FileNotFoundError, ValueError) as exc:
            return _error(templates, request, str(exc))

        token = _store(out, f"filled{template_path.suffix}")
        return _result(
            templates, request, token, out.name, report=report_box["report"].render()
        )

    from common_file_generator.web.api import create_api_router

    app.include_router(create_api_router(max_upload_bytes=max_upload_bytes, caps=caps))

    @app.get("/download/{token}")
    def download(token: str) -> FileResponse:
        artifact = artifacts.get(token)
        if artifact is None or not artifact.path.is_file():
            raise HTTPException(status_code=404, detail="File not found or expired.")
        return FileResponse(
            artifact.path,
            filename=artifact.filename,
            media_type="application/octet-stream",
        )

    # Expose internals the tests rely on without leaking them into responses.
    app.state.artifacts = artifacts
    app.state.workdir = workdir
    return app


class _UploadError(ValueError):
    """Raised when an upload is the wrong type or too large."""


async def _save_upload(
    upload: UploadFile,
    workdir: Path,
    allowed_exts: set[str],
    max_bytes: int,
) -> Path:
    name = upload.filename or ""
    suffix = Path(name).suffix.lower()
    if suffix not in allowed_exts:
        allowed = ", ".join(sorted(allowed_exts))
        raise _UploadError(
            f"'{name}' is not an accepted file type. Allowed: {allowed}."
        )

    dest = workdir / f"upload-{secrets.token_hex(4)}{suffix}"
    written = 0
    # Stream in chunks and abort as soon as the cap is exceeded, so an oversized
    # upload is never fully buffered in memory or fully written to disk.
    with dest.open("wb") as handle:
        while chunk := await upload.read(_UPLOAD_CHUNK):
            written += len(chunk)
            if written > max_bytes:
                handle.close()
                dest.unlink(missing_ok=True)
                raise _UploadError(
                    f"'{name}' is larger than the "
                    f"{max_bytes // (1024 * 1024)} MB limit."
                )
            handle.write(chunk)
    return dest


def _video_default() -> str:
    from common_file_generator.core import DEFAULT_VIDEO_URL

    return DEFAULT_VIDEO_URL


def _result(
    templates: Jinja2Templates,
    request: Request,
    token: str,
    filename: str,
    *,
    report: str | None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "partials/result.html",
        {
            "token": token,
            "filename": filename,
            "report": report,
            "generated_at": time.strftime("%H:%M:%S", time.localtime()),
        },
    )


def _error(
    templates: Jinja2Templates,
    request: Request,
    message: str,
    *,
    status_code: int = 400,
) -> HTMLResponse:
    response = templates.TemplateResponse(
        request, "partials/error.html", {"message": message}
    )
    response.status_code = status_code
    return response
