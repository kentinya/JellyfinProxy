# Changelog

All notable changes to JellyfinProxy are recorded here. Versions follow
[Semantic Versioning](https://semver.org/):

- MAJOR: incompatible behavior or configuration changes.
- MINOR: backward-compatible features.
- PATCH: backward-compatible fixes.

## Unreleased

- Removed the danmu raw video special case. `/api/danmu/{id}/raw` and
  `/emby/api/danmu/{id}/raw` are now always forwarded to Jellyfin through the
  plain HTTP proxy: they no longer look up or use a cached media source mapping,
  even when the same ID has a valid mapping, and the proxy does not create a
  video `302` for them. Upstream status, body, `Content-Type` and any
  upstream-originated `Location` are forwarded as usual. The `/Videos/{id}/...`,
  `/videos/{id}/...` and `/video/...` redirect and streaming fallback behaviour is
  unchanged.

## 1.0.0 - 2026-10-25

- Removed the complete PlaybackInfo JSON response cache. Every PlaybackInfo request
  is forwarded upstream again, so a repeated or concurrent request for one Item no
  longer reuses an earlier response body. Upstream errors that a cache hit used to
  hide now surface per request.
- Removed the cache-only configuration `playback_info_cache_enabled`,
  `playback_info_cache_ttl_seconds`, `playback_info_cache_max_entries` and
  `playback_cache_bypass_clients` together with their uppercase environment
  variables. Legacy keys are ignored in TOML and the environment, so existing
  configurations still start.
- Removed the `X-JellyfinProxy-Cache` response header, the `playback_info_cache`
  application log records and the `cache` field of `client_identified` logs.
- Retained PlaybackInfo bypass bodies, direct-URL filling for Video redirects, the
  Video 302 behaviour, media source path invalidation and the streaming proxy
  fallback.
- PlaybackInfo fields are now configured in TOML and are no longer modified by
  default. The previous automatic `Protocol = "File"` and
  `SupportsTranscoding = false` rewrite for remote media sources is gone; configure
  `[playback_info.media_source_fields]` with those two values to restore it. Both
  `[playback_info.response_fields]` and `[playback_info.media_source_fields]` are
  optional and only listed fields are overwritten, so an existing configuration
  without these tables now receives Jellyfin's original field values. Values keep
  their TOML type, arrays and objects replace the whole field, and configurable
  values are validated at startup. The shipped sample configuration does not
  enable any override.

## 0.9.3 - 2026-10-24

- Dropped the cached media source URL when a later PlaybackInfo response for the
  same `MediaSourceId` carries a Path that is not a usable HTTP(S) URL, so video
  requests fall back to the transparent proxy instead of redirecting to a stale
  address. Paths passed to the media source cache that are invalid or raise
  `ValueError` during URL parsing only remove that single ID; parsing errors are
  caught inside the cache method. A later valid URL re-establishes the redirect.
  Earlier MediaResolver error handling during PlaybackInfo modification is unchanged.

## 0.9.2 - 2026-10-06

- Populated video redirect URLs even when clients bypass PlaybackInfo changes,
  including PlaybackInfo cache hits, while preserving the original response body.

## 0.9.1 - 2026-10-06

- Accepted both `MediaSourceId` and `mediaSourceId` query parameters for cached
  video redirects, preferring a non-empty `MediaSourceId` when both are supplied.

## 0.9.0 - 2026-08-06

- Added a bounded, cross-device in-memory TTL cache for successful PlaybackInfo
  responses so repeated POST requests do not trigger Jellyfin STRM probing again.
- Added TOML and environment configuration for cache enablement, lifetime, and
  capacity, plus `X-JellyfinProxy-Cache` response diagnostics.
- Routed SenPlayer's `/api/danmu/{id}/raw` requests through the cached direct
  video handler in addition to the existing `/emby/api/danmu/{id}/raw` form.
- Added an independent client list for bypassing PlaybackInfo cache reads and
  writes without changing PlaybackInfo modification policy.

## 0.8.1 - 2026-08-04

- Added sanitized client identity logging for PlaybackInfo and Video requests,
  including the selected modify or bypass action.

## 0.8.0 - 2026-08-04

- Added independent per-client bypass lists for PlaybackInfo modifications and
  Video redirects while retaining the existing full-bypass list.
- Added TOML and environment-variable configuration for both route categories.

## 0.7.2 - 2026-08-03

- Added PlaybackInfo processing for the `/emby/Items/{id}/PlaybackInfo` route.
- Added cached remote media redirects for `/emby/api/danmu/{id}/raw`, with
  streaming proxy fallback for local media and cache misses.

## 0.7.1 - 2026-08-03

- Added direct redirect lookup from the `/Videos/{id}/...` path when clients
  omit `MediaSourceId`.
- Normalized hyphenated and compact 32-character media UUIDs for cache lookup.

## 0.7.0 - 2026-08-03

- Changed transparent proxy responses to asynchronous streaming so large video
  files are no longer buffered in memory.
- Preserved Range and representation metadata while streaming, and ensured
  upstream responses close on completion or client disconnect.

## 0.6.0 - 2026-08-03

- Added direct video redirects from `/videos/{id}/...` requests to the cached
  HTTP(S) `MediaSource.Path` selected by `MediaSourceId`.
- Preserved transparent proxy fallback when no safe cached path is available.

## 0.5.2 - 2026-08-03

- Added video-route matching for clients that send the lowercase plural
  `/videos/{id}/...` path.

## 0.5.1 - 2026-08-03

- Added video-route matching for the lowercase `/video` path prefix while
  preserving Jellyfin `/Videos/{id}` compatibility.

## 0.5.0 - 2026-08-03

- Added a dedicated, rotating MediaWarp-style access log with configurable
  output path and credential redaction.

## 0.4.1 - 2026-08-03

- Fixed corrupted browser assets when Jellyfin selected Brotli compression.
- Removed duplicate upstream `Date` and `Server` response headers.

## 0.4.0 - 2026-08-03

- Added Docker image and Docker Compose deployment support.
- Added stdout-only logging mode for container runtimes.
- Added a container health check and restart policy.

## 0.3.0 - 2026-08-03

- Renamed the application, executable, configuration, logs, and response header
  from MediaWarp to JellyfinProxy.

## 0.2.0 - 2026-08-03

- Added TOML configuration files with environment-variable overrides.
- Added a reproducible PyInstaller specification for Linux single-file builds.
- Added standalone binary deployment documentation.

## 0.1.0 - 2026-08-03

- Added asynchronous Jellyfin reverse proxying.
- Added PlaybackInfo media-source policy rewriting.
- Added client bypass policies.
- Added request-correlated rotating logs with credential redaction.
- Added application version reporting.
