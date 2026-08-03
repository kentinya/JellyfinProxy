# Changelog

All notable changes to JellyfinProxy are recorded here. Versions follow
[Semantic Versioning](https://semver.org/):

- MAJOR: incompatible behavior or configuration changes.
- MINOR: backward-compatible features.
- PATCH: backward-compatible fixes.

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
