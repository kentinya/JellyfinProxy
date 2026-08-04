"""ASGI application factory and process entry point."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
import logging
import re
from time import perf_counter
from typing import AsyncIterator
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Request, Response

from config import Settings, default_config_path
from handlers.dispatcher import Dispatcher
from infrastructure.http_client import JellyfinHttpClient
from infrastructure.logging import bind_request_id, configure_logging, log_access, reset_request_id
from policies.client_policy import ClientPolicy
from routers.router import Router
from services.media_resolver import MediaResolver
from services.media_source_service import MediaSourceService, ProtocolFileRule
from services.playback_service import PlaybackService
from version import __version__


logger = logging.getLogger(__name__)
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _request_id(request: Request) -> str:
    supplied = request.headers.get("x-request-id", "")
    return supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else uuid4().hex


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        http_client = JellyfinHttpClient(
            base_url=settings.jellyfin_url,
            timeout_seconds=settings.request_timeout_seconds,
        )
        app.state.dispatcher = Dispatcher(
            router=Router(),
            client_policy=ClientPolicy(
                settings.bypass_clients,
                settings.playback_bypass_clients,
                settings.video_bypass_clients,
            ),
            http_client=http_client,
            playback_service=PlaybackService(
                MediaSourceService(MediaResolver(), rules=(ProtocolFileRule(),))
            ),
        )
        logger.info(
            "application_started version=%s listen=%s:%d upstream=%s",
            __version__,
            settings.listen_host,
            settings.listen_port,
            settings.jellyfin_url,
        )
        yield
        await http_client.close()
        logger.info("application_stopped")

    app = FastAPI(
        title="JellyfinProxy",
        version=__version__,
        debug=settings.debug,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_logging(request: Request, call_next) -> Response:
        request_id = _request_id(request)
        token = bind_request_id(request_id)
        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            logger.exception(
                "request_failed method=%s path=%s duration_ms=%.2f",
                request.method,
                request.url.path,
                (perf_counter() - started) * 1000,
            )
            raise
        else:
            response.headers["x-request-id"] = request_id
            response.headers["x-jellyfinproxy-version"] = __version__
            logger.info(
                "request_completed method=%s path=%s status=%d duration_ms=%.2f",
                request.method,
                request.url.path,
                response.status_code,
                (perf_counter() - started) * 1000,
            )
            return response
        finally:
            query = request.url.query
            path = request.url.path + (f"?{query}" if query else "")
            client_ip = request.client.host if request.client else "-"
            log_access(
                method=request.method,
                path=path,
                status_code=status_code,
                duration_ms=(perf_counter() - started) * 1000,
                client_ip=client_ip,
            )
            reset_request_id(token)

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
        include_in_schema=False,
    )
    async def proxy_entry(request: Request, path: str) -> Response:
        del path
        return await request.app.state.dispatcher.dispatch(request)

    return app


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JellyfinProxy middleware proxy")
    parser.add_argument(
        "--config",
        default=str(default_config_path()),
        help="path to the TOML configuration file",
    )
    parser.add_argument("--version", action="version", version=f"JellyfinProxy {__version__}")
    return parser


if __name__ == "__main__":
    arguments = _argument_parser().parse_args()
    try:
        runtime_settings = Settings.from_file(arguments.config)
    except ValueError as exc:
        _argument_parser().error(str(exc))
else:
    # Preserve compatibility for ASGI servers importing ``main:app``.
    candidate = default_config_path()
    runtime_settings = Settings.from_file(candidate) if candidate.exists() else Settings.from_env()

configure_logging(
    runtime_settings.log_level,
    runtime_settings.log_file,
    runtime_settings.access_log_file,
)
app = create_app(runtime_settings)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=runtime_settings.listen_host,
        port=runtime_settings.listen_port,
        reload=False,
        log_config=None,
        access_log=False,
    )
