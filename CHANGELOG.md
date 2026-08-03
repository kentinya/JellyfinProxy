# Changelog

All notable changes to JellyfinProxy are recorded here. Versions follow
[Semantic Versioning](https://semver.org/):

- MAJOR: incompatible behavior or configuration changes.
- MINOR: backward-compatible features.
- PATCH: backward-compatible fixes.

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
