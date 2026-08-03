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

from config import settings
from handlers.dispatcher import Dispatcher
from infrastructure.http_client import JellyfinHttpClient
from infrastructure.logging import bind_request_id, configure_logging, reset_request_id
from policies.client_policy import ClientPolicy
from routers.router import Router
from services.media_resolver import MediaResolver
from services.media_source_service import MediaSourceService, ProtocolFileRule
from services.playback_service import PlaybackService
from version import __version__


configure_logging(settings.log_level, settings.log_file)
logger = logging.getLogger(__name__)
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _request_id(request: Request) -> str:
    supplied = request.headers.get("x-request-id", "")
    return supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else uuid4().hex


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        http_client = JellyfinHttpClient(
            base_url=settings.jellyfin_url,
            timeout_seconds=settings.request_timeout_seconds,
        )
        app.state.dispatcher = Dispatcher(
            router=Router(),
            client_policy=ClientPolicy(settings.bypass_clients),
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
        title="Jellyfin Middleware Proxy",
        version=__version__,
        debug=settings.debug,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_logging(request: Request, call_next) -> Response:
        request_id = _request_id(request)
        token = bind_request_id(request_id)
        started = perf_counter()
        try:
            response = await call_next(request)
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
            response.headers["x-mediawarp-version"] = __version__
            logger.info(
                "request_completed method=%s path=%s status=%d duration_ms=%.2f",
                request.method,
                request.url.path,
                response.status_code,
                (perf_counter() - started) * 1000,
            )
            return response
        finally:
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


app = create_app()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MediaWarp Jellyfin middleware proxy")
    parser.add_argument("--version", action="version", version=f"MediaWarp {__version__}")
    parser.parse_args()
    uvicorn.run(
        "main:app",
        host=settings.listen_host,
        port=settings.listen_port,
        reload=False,
        log_config=None,
        access_log=False,
    )
