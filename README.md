# Jellyfin Middleware Proxy

An asynchronous FastAPI reverse proxy that transparently forwards Jellyfin traffic and applies policy decisions to URLs already resolved by Jellyfin in PlaybackInfo responses.

## Run

```bash
cd /opt/mediawarp
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
JELLYFIN_URL=http://jellyfin:8096 .venv/bin/python main.py
```

Configuration is provided through the environment; see `.env.example`. `BYPASS_CLIENTS` is a comma-separated, case-insensitive substring list checked against `User-Agent`, `X-Emby-Client`, and `X-Emby-Device-Name`.

`LOG_LEVEL` controls application logging and defaults to `INFO`. Each request receives
an `X-Request-ID` response header; an incoming `X-Request-ID` is preserved so related
request, upstream, and playback-policy log entries can be correlated. Query strings,
request bodies, and authentication headers are not logged.
`LOG_FILE` selects a rotating log file and defaults to `mediawarp.log` in the working
directory. Files rotate at 10 MiB and five backups are retained.

The proxy never opens STRM files. Jellyfin remains responsible for resolving media metadata and STRM content; MediaWarp only analyzes the resulting HTTP(S) `MediaSources[].Path` and applies configured policy rules.

## Versioning

MediaWarp follows Semantic Versioning. The current version is defined once in
`version.py`, appears in startup logs and the `X-MediaWarp-Version` response header,
and can be printed without starting the server:

```bash
.venv/bin/python main.py --version
```

Release changes are documented in `CHANGELOG.md`.
