# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.13.2] - 2026-10-18

### Fixed

- **Idle subscription timeouts** — `subscribe()` and the typed `subscribe_*()` helpers now raise `UnraidTimeoutError` instead of a raw `TimeoutError` when no message arrives for `timeout * 10` seconds, or when the server does not send `connection_ack` in that time. Consumers that already reconnect on `UnraidTimeoutError`, such as ha-unraid, no longer log an error with a traceback each time a quiet subscription goes idle ([#118](https://github.com/tinkerologie/unraid-api/issues/118)).
- **WebSocket closed on handshake failure** — `subscribe()` now closes the WebSocket when the `connection_init` handshake fails (socket closed, WebSocket error, `connection_error`, unexpected message, or an acknowledgement timeout). Before, the socket opened by `ws_connect()` was left open because `subscribe()` only took ownership of it after the handshake succeeded ([#119](https://github.com/tinkerologie/unraid-api/issues/119)).

### Changed
- Pull requests get path labels and at most one type label, `bug` or `enhancement`, from the shared tinkerologie PR labeler. Dependabot pull requests whose largest update is a patch or minor version merge automatically once the checks and commit statuses on their head commit have finished without a failure (a Codecov check that is still pending is not waited for; a Codecov failure blocks); majors, and pull requests with open review threads, stay for review.
- Release workflows hardened (least-privilege job permissions, no expressions in shell scripts, no persisted checkout credentials, no dependency caches); scheduled workflows run on Australia/Brisbane time. Relicensed from MIT to the Apache License 2.0; NOTICE retains the MIT notice for earlier releases.
- Workflow layout tidied after the release hardening (no behaviour change): `permissions:` blocks moved back to the top of their workflow or job in `release.yml`; blank-line layout restored in `ci.yml`.
- Tinkerologie-Bot governance report updated to v1.4.3: an older run can no longer post a stale report after a newer run passed. Workflow formatting tidied.
- Repository standardised to the tinkerologie layout (STANDARDS.md in tinkerologie/.github): workflows renamed to the standard set (CI, Validate, Release, PR Governance, ...), every action pinned to a commit SHA, shared Dependabot, `.editorconfig`, `.gitattributes` and `CODEOWNERS` files, and organization-wide labels and community files.
- Tinkerologie-Bot's comment is now a readable "Pull request checklist": each problem is a numbered heading with plain-English guidance and its items listed underneath, and report updates for a pull request are serialised so an older run can never overwrite a newer one.
- Contribution governance: issues without a `bug` or `enhancement` label are labeled automatically when their type can be determined (issues labeled `question`, `duplicate`, `invalid`, `wontfix`, or `no-type` are skipped), so CodeRabbit can plan them. Pull requests that conflict with the default branch are labeled, and their authors are notified in a comment. Stale issues and pull requests are labeled after 14 days without activity and closed 30 days later. PR governance now re-validates a human-authored, non-draft PR when a bot such as CodeRabbit edits its description, instead of skipping the check and reporting a pass, only maintainers with write access may use `None` instead of linking an issue, and a link to an issue that does not exist now fails the check. Codecov patch coverage must now reach 95%.
- Tinkerologie-Bot now posts one comment on pull requests that fail PR governance, listing every problem to fix, and updates it once they are fixed. PR governance runs from the default branch's workflow (`pull_request_target`), so a pull request cannot change its own check.
- Configured Codecov GitHub Actions workflow for tokenless coverage uploads

## [1.13.1] - 2026-09-03

### Fixed

- **Docker Container Autostart Input Type Name** — Fixed GraphQL validation error (`Unknown type "AutostartConfigurationEntryInput"`) in `update_container_autostart()` by using the correct schema input object type name `[DockerAutostartEntryInput!]!` ([#91](https://github.com/tinkerologie/unraid-api/issues/91)).

## [1.13.0] - 2026-09-02

### Added

- **Unraid OS 7.3.x & GraphQL API 4.37.x Schema Compatibility** — Full model alignment, query updates, and live server verification against Unraid 7.3.2 and GraphQL API 4.37.3+d5058009.
- **Network Interface Queries & Models** — Added `get_network_interfaces()` and `typed_get_network_interfaces()` returning `InfoNetworkInterface` models with IPv4/IPv6 addresses, MAC address, MTU, duplex, DHCP configuration, VLAN ID, and operational state.
- **Docker Organizer & Folder Management** — Added `get_docker_organizer()` and `typed_get_docker_organizer()` returning `ResolvedOrganizerV1`, `ResolvedOrganizerView`, and `FlatOrganizerEntry` hierarchies. Added folder management mutations: `create_docker_folder()`, `rename_docker_folder()`, `delete_docker_entries()`, and `move_docker_entries_to_folder()`.
- **Docker Container Autostart Configuration** — Added `update_container_autostart()` mutation for updating a batch of container `autoStart`, `autoStartOrder`, and `autoStartWait` entries via `docker.updateAutostartConfiguration`.
- **Array Disk Control Mutations** — Added `mount_array_disk()`, `unmount_array_disk()`, and `clear_array_disk_statistics()` for individual disk operations.
- **Server Identity & Connect Queries** — Added `get_servers()`, `typed_get_servers()`, `get_server()`, `typed_get_server()`, and `update_server_identity()` along with `Server` and `ProfileModel` types.
- **Unraid Plugin Background Operations** — Added `get_installed_unraid_plugins()`, `get_plugin_install_operations()`, and `get_plugin_install_operation()` with `PluginInstallOperation` and `PluginInstallEvent` models.
- **Batch Notification Mutations** — Added `archive_notifications()`, `unarchive_notifications()`, `unarchive_all_notifications()`, and `recalculate_notification_overview()`.
- **Real-Time Subscriptions** — Added WebSocket subscription helpers `subscribe_owner()`, `subscribe_servers()`, and `subscribe_plugin_install_updates()` (with `operationId: ID!`).
- **Codecov Coverage Reporting & PR Status Checks** — Integrated Codecov into GitHub Actions CI workflows with XML/branch coverage reporting, a `codecov.yml` configuration enforcing 95% project and patch coverage thresholds, and repository README coverage badge.
- **Python 3.14 CI Matrix & Workflow Streamlining** — Added Python 3.14 to the GitHub Actions test matrix across all supported Python versions (`3.11`, `3.12`, `3.13`, `3.14`). Removed standalone Bandit SAST and OSV Scanner workflows in favor of consolidated Ruff security linting (`flake8-bandit`).

## [1.12.1] - 2026-06-26

### Fixed

- **ANSI escape codes corrupting `DockerContainerStats` IDs** — The Unraid
  backend streams raw `docker stats` terminal output for the
  `dockerContainerStats` subscription, and the first row of every sample cycle
  carries clear-screen/cursor-home escapes (`\x1b[J\x1b[H`) glued onto the
  field right after the `PrefixedID` prefix. Because `docker stats` output
  order is stable, the same container was corrupted on every cycle, so its
  `id` never matched the IDs from `typed_get_containers()` — leaving that
  container's stats permanently unresolved for consumers (e.g. one container's
  CPU/memory sensors stuck "Unknown" in ha-unraid). `DockerContainerStats`
  string fields now strip ANSI CSI sequences on construction, so all consumers
  receive clean values regardless of how the model is built. Verified against a
  live server: round-tripping the corruption through all 8 real container IDs
  recovers the original, server-matching IDs.
  ([#71](https://github.com/tinkerologie/unraid-api/issues/71))

## [1.12.0] - 2026-06-10

### Added

- **`typed_get_containers_safe()` method** — Lightweight variant of
  `typed_get_containers()` for frequent polling. Omits fields that are
  expensive for the server to resolve: `sizeRootFs`/`sizeRw`/`sizeLog` make
  the Docker daemon compute writable-layer sizes (equivalent to
  `docker ps --size`) and caused multi-second CPU spikes on every poll, plus
  the heavy `mounts`/`networkSettings`/`labels` payloads and the
  `ports`/`templatePorts`/`hostConfig`/`tailscaleStatus` subselections.
  Validated against a live Unraid 7.3.1 server: 0.08 s vs 2.5 s for the full
  query with 17 containers.
  ([#69](https://github.com/tinkerologie/unraid-api/issues/69))
- **Network metrics (API 4.35.0)** — `get_network_metrics()` returns
  read-only per-interface throughput, packet, error, and dropped counters
  (`metrics.network`); `subscribe_network_metrics()` streams the same data
  over WebSocket (`systemMetricsNetwork`). New `NetworkMetrics` model
  (public export). Both are capability-gated and raise a clean
  `UnraidAPIError` on servers older than API 4.35.0.
- **Bulk container updates** — `update_all_containers()` updates every
  container with a pending image update (`docker.updateAllContainers`),
  `update_containers(ids)` updates a selected set
  (`docker.updateContainers`), and `refresh_docker_digests()` forces a
  re-check of remote image digests — the WebGUI "check for updates" action
  (`refreshDockerDigests`). All three are capability-gated.

### Changed

- **Test suite migrated from `aioresponses` to `aiointercept`** —
  aiohttp 3.14.0 changed `ClientResponse.__init__()` (new `stream_writer`
  parameter), which broke `aioresponses` 0.7.8 and forced a temporary
  `aiohttp<3.14.0` pin. The test suite now uses
  [aiointercept](https://github.com/Polandia94/aiointercept), which routes
  requests through a real local aiohttp test server and works with
  aiohttp 3.14+. The `aiohttp<3.14.0` constraint is removed
  (`aiohttp>=3.9.0` again) and the lock file is on aiohttp 3.14.1. No
  library code changed — this only affects tests and dev dependencies.

### Fixed

- **Formatter version skew between pre-commit and CI** — The pre-commit
  `ruff-format` hook was pinned to ruff v0.8.0 while the project (and the
  publish workflow's `ruff format --check`) uses ruff 0.15.x; the two
  disagree on formatting, which let an inconsistently formatted file reach
  the v1.12.0 tag and fail the PyPI publish workflow. The pre-commit hook
  is now pinned to the same ruff version as the project.

## [1.11.0] - 2026-06-01

### Added

Support for capabilities exposed by **Unraid 7.3 / API 4.3x** (validated against
a live Unraid 7.3.1 / API 4.34.0 server). Every new method is capability-gated
via the existing introspection layer, so it raises a clean `UnraidAPIError` on
older servers that don't expose the field. The minimum supported Unraid/API
versions are unchanged — older servers keep working.

- **System time** — `get_system_time()` and `get_timezone_options()` read the
  server clock configuration; `update_system_time(time_zone=…, use_ntp=…,
  ntp_servers=…, manual_date_time=…)` updates it (only the provided arguments
  are sent). New `SystemTime` and `TimeZoneOption` models.
- **Disk & UPS extras**
  - `get_assignable_disks()` — disks available to assign to the array
    (returns `PhysicalDisk`; **wakes sleeping disks**).
  - `get_disk(disk_id)` — single physical disk by ID (`PrefixedID`;
    **wakes the disk**, like `get_physical_disks()`).
  - `typed_get_ups_device(device_id)` — single UPS device by ID; returns
    `None` when the device is absent. (The server types this argument as
    `String!`, not `PrefixedID!`.)
  - `subscribe_display()` — async generator yielding `DisplaySettings` on
    each server-side display/theme change.
- **Curated admin**
  - `get_settings()` — read-only diagnostic view of the server `api` and
    `unified` settings blocks. New `Settings`, `ApiConfig`, and
    `UnifiedSettings` models.
  - `configure_ups(…)` — write the apcupsd UPS configuration (pairs with the
    existing `get_ups_configuration()`); only the provided arguments are sent.
- New public exports: `SystemTime`, `TimeZoneOption`, `Settings`, `ApiConfig`,
  `UnifiedSettings`.

## [1.10.0] - 2026-04-15

### Added

- **`get_system_metrics_safe()` method** — Identical to `get_system_metrics()` but omits the `metrics.temperature` GraphQL block. The Unraid temperature resolver triggers smartctl reads that wake sleeping/standby disks; this method is safe for frequent polling (e.g. every 30 seconds) without disrupting disk power management. CPU temperature remains available via `info.cpu.packages.temp`. Returns `SystemMetrics` with `temperature=None`. ([#50](https://github.com/tinkerologie/unraid-api/issues/50))

## [1.9.1] - 2026-04-12

### Security

- **SSRF guard in SSL auto-discovery** — `_discover_redirect_url()` now validates that HTTPS redirects (Unraid "Yes" SSL mode) resolve to the same hostname as the configured server. Redirects to a different host are rejected with a warning, preventing a manipulated HTTP response from redirecting subsequent authenticated requests (including the API key) to an attacker-controlled HTTPS endpoint.
- **Bounded response-body read for nginx 400 detection** — The 400-response body check that detects "plain HTTP to HTTPS port" errors previously read the full response body (`response.text()`). It now reads at most 512 bytes (`response.content.read(512)`), eliminating a potential unbounded-memory DoS vector from a malicious or misbehaving server.
- **Dependabot enabled** — Added `.github/dependabot.yml` to automatically open pull requests when pip dependencies or GitHub Actions have new versions, keeping the supply chain up to date.
- **OSV vulnerability scanner** — Added `.github/workflows/security.yml` that runs [google/osv-scanner](https://google.github.io/osv-scanner/) against `requirements.txt` on every push/PR and on a weekly schedule, uploading results to the GitHub Security tab as SARIF. The workflow also runs Bandit SAST to catch common Python security issues in source code.

## [1.9.0] - 2026-04-11

### Added

- **Server capability detection (Layer 1 backward compatibility)** — `UnraidClient.get_capabilities()` runs a single aliased `__type` introspection query on first use and caches the result, letting the client target multiple Unraid API versions from one codebase
  - New `ServerCapabilities` class with dotted-path lookup: `has("Query.network")`, `has_all(...)`, `has_any(...)`, and a `permissive()` factory for introspection-failure fallback
  - Lazy, lock-guarded initialization via `asyncio.Lock`; auth errors propagate, all other introspection failures fall back to permissive mode so queries are never blocked
  - `typed_get_containers()` now composes its GraphQL query from capabilities and only requests fields the server actually exposes; the old extended→core fallback has been removed
  - New `capabilities.py` module exports `ServerCapabilities` and `build_introspection_query()`
- **Notification subscriptions** — Three new real-time subscriptions for pushing Unraid notifications into Home Assistant without polling
  - `subscribe_notification_added()` yields a `Notification` for each new notification
  - `subscribe_notifications_overview()` yields `NotificationOverview` counts on each change
  - `subscribe_notifications_warnings_and_alerts()` yields a `list[Notification]` of active warnings/alerts
- **Parity history subscription** — `subscribe_parity_history()` yields `ParityCheck` models for live progress updates during a parity check
- **Notification mutations** — `create_notification()` creates a new notification, and `notify_if_unique()` creates one only when no duplicate exists (returns `None` on duplicate)
- **Temperature configuration mutation** — `update_temperature_config()` wraps the `updateTemperatureConfig` mutation for updating server-side temperature monitoring settings (enabled, polling interval, default unit, sensors, thresholds, history)
- **Network query** — `get_network()` and `typed_get_network()` expose the `network` query with access URLs (LAN/WAN/etc.)
- **New models** — `Network`, `AccessUrl`, and `TailscaleExitNodeStatus` exported from `unraid_api`
- **Feature gating** — The 9 new top-level methods (`get_network`, `typed_get_network`, `create_notification`, `notify_if_unique`, `update_temperature_config`, and the 4 new subscriptions) raise a clean `UnraidAPIError` on servers that don't expose the underlying GraphQL field, pointing users at the Unraid API plugin update path

### Changed

- **TailscaleStatus model expanded from 3 to 18 fields** — `typed_get_containers()` now requests and parses the full Tailscale status: `hostname`, `dnsName`, `online`, `version`, `latestVersion`, `updateAvailable`, `relay`, `relayName`, `tailscaleIps`, `primaryRoutes`, `isExitNode`, `exitNodeStatus`, `webUiUrl`, `keyExpiry`, `keyExpiryDays`, `keyExpired`, `backendState`, `authUrl`
- **ParityCheck model extended** — Added `date` (parsed datetime), `duration` (int seconds), and `correcting` (bool) fields for full parity-history payload shape; `speed` type changed from `int | None` to `str | None` to match the server's string-formatted rate

### Fixed

- **Older Unraid servers no longer break on extended container fields** — Capability-composed queries mean servers without `labels`, `networkSettings`, `mounts`, `isUpdateAvailable`, or the full Tailscale subselection get a query that only asks for what they support, instead of relying on a 400-response fallback

## [1.8.0] - 2026-03-31

### Security

- **Eliminated GraphQL injection vector in `get_physical_disks()`** — Replaced f-string interpolation in the GraphQL query with two static query strings, preventing any possibility of query manipulation via the `include_smart` parameter
- **Replaced `assert` with explicit error handling in WebSocket handshake** — `_ws_connect_and_init()` now raises `UnraidConnectionError` instead of using `assert` for session validation, which could be stripped by Python's `-O` flag
- **API key no longer sent during SSL discovery** — The HTTP redirect probe in `_discover_redirect_url()` no longer includes authentication headers, preventing API key exposure over plaintext HTTP connections during SSL auto-discovery

### Deprecated

- **cloud/connect/remoteAccess methods** — `get_cloud()`, `typed_get_cloud()`, `get_connect()`, `typed_get_connect()`, `get_remote_access()`, and `typed_get_remote_access()` now emit `DeprecationWarning`. These query roots were removed from the live Unraid GraphQL API (v4.31.1) and may be re-added in a future release. Models (`Cloud`, `Connect`, `RemoteAccess`) are retained for backward compatibility.

### Fixed

- **Removed redundant `import asyncio`** — `restart_container()` had a local `import asyncio` shadowing the module-level import (flagged by CodeQL `py/repeated-import`)
- **Fixed missing newline at end of file** — `client.py` now ends with a trailing newline per POSIX convention (ruff W292)

### Changed

- **`.gitignore`** — Added `codeql-db/` and `codeql-results.sarif` to exclude local CodeQL artifacts from version control

- **Schema alignment audit** — Comprehensive cross-reference of all models, queries, and exports against live Unraid server GraphQL schema
  - **VmDomain**: Removed 6 speculative fields (`memory`, `vcpu`, `autostart`, `cpuMode`, `iconUrl`, `primaryGpu`) that do not exist in the GraphQL schema
  - **CpuCore**: Added all per-CPU metric fields (`percentUser`, `percentSystem`, `percentIdle`, `percentNice`, `percentIrq`, `percentGuest`, `percentSteal`) — previously only had `percentTotal`
  - **DisplaySettings**: `str | bool | None` union types retained — API may return string representations for boolean fields
- **Granular timeout configuration** — Replaced single total timeout with separate connect (10s cap) and read timeouts via `aiohttp.ClientTimeout`, preventing slow connections from consuming the entire timeout budget
- **Connection pool limits** — Added `limit=10` and `limit_per_host=5` to `TCPConnector` to prevent connection exhaustion under concurrent usage
- **WebSocket size and timeout limits** — Added `max_msg_size=16MB` to prevent OOM on malformed responses and `receive_timeout` to detect stalled subscriptions
- **Graceful session shutdown** — Added `asyncio.sleep(0)` after `session.close()` to allow aiohttp transport cleanup per upstream best practices
- **Safe `__repr__`** — `UnraidClient` now has a `__repr__` that shows host/port/ssl status without exposing the API key
- **Python 3.14 compatibility** — `enable_cleanup_closed` is only passed to `TCPConnector` on Python < 3.14 where it isn't a no-op

### Added

- **Dependency lock file** — Added `requirements.txt` with pinned production dependencies (generated via `pip-compile`) for reproducible installs and supply-chain auditability

- **Share.comment** field and query — `typed_get_shares()` and `Share` model now include the share `comment` field from the schema
- **Notification query fields** — `get_notifications()` now fetches `link`, `type`, and `formattedTimestamp` (model already had these fields, query was missing them)
- **PhysicalDisk extended fields** — Added `serialNum`, `firmwareRevision`, and `partitions` (list of `DiskPartition`) to `PhysicalDisk` model and `get_physical_disks()` query
- **get_metrics() extended fields** — Now includes `active` and `buffcache` in memory query, and `percentNice`, `percentIrq`, `percentGuest`, `percentSteal` in per-CPU query
- **New exports** — `DiskPartition`, `MemoryUtilization`, and `NotificationOverviewCounts` are now exported from `unraid_api` for consumer type access
- **Temperature monitoring** ([#37](https://github.com/tinkerologie/unraid-api/issues/37)) — Full temperature sensor support via `get_temperature_metrics()` query and `subscribe_temperature_metrics()` subscription
  - New models: `TemperatureMetrics`, `TemperatureSensor`, `TemperatureReading`, `TemperatureSummary`, `TemperatureSensorSummary`
  - New enums: `SensorType` (CPU_PACKAGE, CPU_CORE, DISK, NVME, CUSTOM), `TemperatureUnit` (CELSIUS, FAHRENHEIT), `TemperatureStatus` (NORMAL, WARNING, CRITICAL, UNKNOWN)
  - Helper properties: `TemperatureSensor.temperature`, `is_critical`, `is_warning`; `TemperatureMetrics.disk_sensors`, `nvme_sensors`, `cpu_sensors`, `get_sensors_by_type()`
  - Temperature data also included in `SystemMetrics.from_response()` via `temperature` field
- **Missing memory fields** ([#38](https://github.com/tinkerologie/unraid-api/issues/38)) — Added `active`, `buffcache`, and `swapFree` to `MemoryUtilization` model and `memory_active`, `memory_buffcache`, `swap_free` to `SystemMetrics`
  - `get_system_metrics()` query now fetches these additional memory fields

## [1.7.1] - 2026-03-21

### Fixed

- **Resolved all CodeQL clear-text logging alerts (#2–#14)** — API key no longer appears in any method that contains logging calls; auth headers are pre-computed once in `__init__` via `self._auth_headers` and referenced by name elsewhere
- **Redacted API key from test script output** — `scripts/unraid-api-client.py` no longer prints any portion of the API key
- **Fixed all 5 notification mutation methods** sending incorrectly nested GraphQL mutations ([#24](https://github.com/tinkerologie/unraid-api/issues/24))
  - `archive_notification()` — uses root-level `archiveNotification` instead of `notifications { archive }`
  - `unarchive_notification()` — uses root-level `unreadNotification` instead of `notifications { unread }`
  - `delete_notification()` — uses root-level `deleteNotification` with required `type` parameter instead of `notifications { delete }`
  - `archive_all_notifications()` — uses root-level `archiveAll` with proper sub-selections instead of `notifications { archiveAll }`
  - `delete_all_notifications()` — uses root-level `deleteArchivedNotifications` instead of `notifications { deleteAll }` (also fixes wrong field name)
- All notification mutations now include required sub-field selections (`NotificationOverview` fields)
- **Fixed 3 array disk mutation methods** with incorrect GraphQL field names that would fail with HTTP 400 on Unraid 7.2.4+ (API v4.30.x)
  - `add_array_disk()` — uses `addDiskToArray(input: $input)` with `ArrayDiskInput` instead of non-existent `addDisk(id: $id)`; also added optional `slot` parameter
  - `remove_array_disk()` — uses `removeDiskFromArray(input: $input)` with `ArrayDiskInput` instead of non-existent `removeDisk(id: $id)`; also added optional `slot` parameter
  - `clear_disk_stats()` — uses `clearArrayDiskStatistics(id: $id)` returning `Boolean` instead of non-existent `clearStatistics(id: $id)`

### Added

- **Schema cross-check validation script** (`scripts/validate-schema.py`) — three-way cross-check validator that validates client queries against the live Unraid server schema and the official GitHub schema from `github.com/unraid/api`

### Changed

- **Fixed all ruff lint warnings in `scripts/unraid-api-client.py`** — line length (E501), unnecessary lambdas (PLW0108), loop variable overwrite (PLW2901), deprecated `asyncio.TimeoutError` alias (UP041), and unused noqa directives (RUF100)
- Replaced per-request `headers = {"x-api-key": self._api_key}` construction in `_discover_redirect_url`, `_make_request`, and `subscribe` with shared `self._auth_headers` dict
- `delete_notification()` now accepts a `notification_type` parameter (`"ARCHIVE"` or `"UNREAD"`, defaults to `"ARCHIVE"`) as required by the Unraid API schema

## [1.7.0] - 2026-03-19

### Added

- **Full support for Unraid API v4.30.0/v4.30.1 features** (Unraid 7.2.4+)
- **New client methods:**
  - `get_container_update_statuses()` — query Docker container update availability as `list[ContainerUpdateStatus]`
  - `get_ups_configuration()` — query UPS hardware/software configuration as `UPSConfiguration`
  - `get_display_settings()` — query display and temperature threshold settings as `DisplaySettings`
  - `get_docker_port_conflicts()` — query Docker LAN port conflicts as `DockerPortConflicts`
- **WebSocket GraphQL subscription support** — real-time streaming for subscription-only API endpoints using the `graphql-transport-ws` protocol
- **Generic `subscribe()` async generator** — low-level method for any GraphQL subscription with full protocol handling (connection_init/ack, subscribe/next/error/complete)
- **6 typed subscription methods:**
  - `subscribe_container_stats(container_id)` → yields `DockerContainerStats` for real-time Docker container resource metrics
  - `subscribe_cpu_metrics()` → yields `CpuMetrics` for CPU usage per-core and total
  - `subscribe_cpu_telemetry()` → yields `CpuTelemetryMetrics` for CPU power and temperature
  - `subscribe_memory_metrics()` → yields `MemoryMetrics` for system memory usage
  - `subscribe_ups_updates()` → yields raw `dict` for UPS state changes
  - `subscribe_array_updates()` → yields `ArraySubscriptionUpdate` for array state and capacity changes
- **New Pydantic models:**
  - `ContainerUpdateStatus` — container name and update status (e.g., `UP_TO_DATE`, `UPDATE_AVAILABLE`)
  - `UPSConfiguration` — full UPS config (cable, type, device, battery level, timeout, etc.)
  - `DisplaySettings` — theme, temperature unit/thresholds, locale, and UI display toggles
  - `DockerPortConflicts`, `DockerLanPortConflict`, `DockerPortConflictContainer` — port conflict hierarchy
  - `TailscaleStatus` — Tailscale hostname, DNS name, and online status for containers
  - `ContainerTemplatePort` — template port configuration (ip, privatePort, publicPort, type)
  - `KeyFile` — registration key file location and contents
  - `CpuCore`, `CpuMetrics`, `CpuTelemetryMetrics`, `MemoryMetrics`, `ArraySubscriptionUpdate` — subscription models
- WebSocket URL auto-derivation from resolved HTTP URL (http→ws, https→wss)
- UPS nominal and current power fields on `UPSPower` model: `nominalPower` (optional `int`) and `currentPower` (optional `float`)
- Updated `get_ups_status()` and `typed_get_ups_devices()` GraphQL queries to fetch `nominalPower` and `currentPower`
- **Extended `DockerContainer` fields:** `sizeRw`, `sizeLog`, `autoStartOrder`, `autoStartWait`, `shell`, `templatePath`, `projectUrl`, `registryUrl`, `supportUrl`, `tailscaleEnabled`, `tailscaleStatus`, `isRebuildReady`, `templatePorts`, `lanIpPorts`
- **Extended `ArrayDisk` fields:** `rotational`, `numReads`, `numWrites`, `numErrors`, `warning`, `critical`, `color`, `format`, `transport`, `comment`, `exportable`
- **Extended `Share` fields:** `cache`, `include`, `exclude`, `nameOrig`, `allocator`, `splitLevel`, `floor`, `cow`, `color`, `luksStatus`
- **Extended `Vars` fields:** `sbVersion`, `joinStatus`, `pollAttributesStatus`
- **Extended `Registration` model** with `keyFile` field (location and contents)
- **Extended `UnraidArray` model** with `bootDevices` list

### Fixed

- **Fixed WebSocket subscription authentication** — `connection_init` payload sends `x-api-key` at the top level instead of nested under `headers`, fixing "Failed to validate session" CSRF errors
- **Fixed `CpuTelemetryMetrics` model** — `power` and `temp` fields accept `list[float] | float | None` to match real server responses returning per-core values as lists
- **Fixed subscription `next` messages with null data** — `subscribe()` handles `None` data payloads gracefully
- **Error handling for GraphQL errors in subscription `next` payloads** — raises `UnraidAPIError` when server sends errors without data
- **Fixed `DockerContainerStats` model** to match actual GraphQL schema — fields are now `id`, `cpuPercent`, `memUsage` (str), `memPercent`, `netIO` (str), `blockIO` (str)
- Removed `stats` field from `DockerContainer` — container stats are only available via the `dockerContainerStats` GraphQL subscription

### Changed

- All GraphQL queries updated to fetch new v4.30.0 fields (`typed_get_containers`, `typed_get_array`, `typed_get_shares`, `get_containers`, `get_array_status`, `get_array_disks`, `get_shares`, `get_vars`, `get_registration`)

## [1.6.0] - 2026-02-24

### Added

- **State constants module** (`unraid_api.const`) with all known API state values organized by domain (fixes #17)
  - `MIN_API_VERSION`, `MIN_UNRAID_VERSION` for version gating
  - Docker, VM, disk, parity, UPS, and array state constants
- **State helper properties** on models (fixes #17):
  - `DockerContainer.is_running` - True when container state is "running"
  - `VmDomain.is_running` - True when VM state is "running" or "idle"
  - `ArrayDisk.is_healthy` - True when disk status is "DISK_OK"
  - `ParityCheck.is_running` - True when status is "RUNNING" or "PAUSED"
  - `ParityCheck.has_problem` - True when status is "FAILED" or errors > 0
  - `UPSDevice.is_connected` - True when status is not "Offline" or "OFF"
- **`VersionInfo` model** returned by `get_version()` with typed `api` and `unraid` fields (fixes #21)
- **`ParityHistoryEntry` model** returned by `get_parity_history()` with typed fields and `duration_formatted` property (fixes #18)
  - Handles multiple date formats (ISO strings, epoch timestamps, datetime objects)
- **`check_compatibility()` method** on `UnraidClient` for version validation (fixes #20)
  - Raises `UnraidVersionError` if server version is below minimum requirements
  - Uses `packaging` library for robust semantic version comparison
- **`UnraidVersionError` exception** for incompatible server versions (fixes #20)
- **`format_bytes()` utility function** for human-readable byte formatting (fixes #15)
- **`SystemMetrics.average_cpu_temperature`** property - mean of all CPU package temps (fixes #15)
- **`SystemMetrics.memory_used` fallback** computation from `total - available` when API doesn't provide `used` (fixes #15)
- **UPS power calculation helper** `UPSDevice.calculate_power_watts(nominal_power)` (fixes #19)
- **`UPSBattery.runtime_formatted`** property for human-readable runtime display (fixes #19)
- Missing fields in `typed_get_containers()` GraphQL query: `imageId`, `isUpdateAvailable`, `webUiUrl`, `iconUrl` (fixes #12)
  - Extended fields (`isUpdateAvailable`, `webUiUrl`, `iconUrl`) are queried with automatic fallback for older API versions that don't support them (verified against official schema at `unraid/api`)
- `packaging` as a runtime dependency for version comparison

### Fixed

- **ZFS disk usage calculation** - `ArrayDisk.fs_used_bytes` and `usage_percent` now fall back to `fsSize - fsFree` when `fsUsed` is 0 or None, which is common on ZFS pools (fixes #16)
- **aiohttp exception wrapping** - all aiohttp exceptions are now properly mapped to the UnraidAPI exception hierarchy (fixes #22):
  - `ClientResponseError` (401/403) -> `UnraidAuthenticationError`
  - `ClientResponseError` (other) -> `UnraidAPIError`
  - `TimeoutError` during discovery -> `UnraidTimeoutError`
  - Session `close()` errors are now suppressed and logged
- Consumers no longer need to import `aiohttp` to handle errors

### Changed

- `get_version()` now returns `VersionInfo` model instead of `dict[str, str]`
- `get_parity_history()` now returns `list[ParityHistoryEntry]` instead of `list[dict]`

## [1.5.0] - 2026-02-07

### Added

- `restart_container(container_id, delay=1.0)` convenience method that encapsulates the stop/wait/start sequence
- Container log retrieval: `get_container_logs()` and `typed_get_container_logs()` with `tail` and `since` parameters
- User account query: `get_me()` and `typed_get_me()` for current authenticated user info
- API key management: `get_api_keys()`, `typed_get_api_keys()`, `create_api_key()`, `update_api_key()`, `delete_api_keys()`
- New Pydantic models: `UserAccount`, `ApiKey`, `Permission`, `DockerContainerLogs`, `DockerContainerLogLine`
- Refactored datetime parsing in Pydantic models using `BeforeValidator` with reusable `ParsedDatetime` annotated type
  - Consolidates repeated `field_validator` logic for cleaner, more maintainable code

### Fixed

- Silent fallback to default HTTPS port when HTTP probe fails on user-specified port (fixes #9)
  - When a non-default `http_port` is specified and the port is unreachable, `UnraidConnectionError` is now raised instead of silently connecting on port 443
  - Default port (80) behavior is unchanged — HTTPS fallback still works for standard HTTP→HTTPS upgrade
- Improved SSL/TLS detection with short-circuit logic when `http_port == https_port`
- Handle nginx 400 "plain HTTP to HTTPS port" error response to detect forced HTTPS configuration
- Comprehensive test coverage for SSL detection edge cases and session creation failures

## [1.4.0] - 2026-01-13

### Added
- New `UnraidSSLError` exception for SSL/TLS certificate verification failures
  - Raised when SSL certificate verification fails, hostname mismatches, or TLS handshake errors occur
  - Inherits from `UnraidConnectionError` for backwards compatibility
  - Enables cleaner error handling without string matching (fixes #4)
- Added `PLR0912` (too many branches) to ruff ignore list for complex error handling

### Changed
- SSL errors are now caught specifically and re-raised as `UnraidSSLError` instead of generic `UnraidConnectionError`

## [1.3.1] - 2026-01-11

### Added
- CPU temperature fields to `SystemMetrics` model:
  - `cpu_temperature` - First package temperature (most common use)
  - `cpu_temperatures` - All package temperatures (for multi-CPU systems)
  - `cpu_power` - Total CPU power consumption in watts
- Updated `get_system_metrics()` GraphQL query to fetch `info.cpu.packages`

### Fixed
- Issue #3: Add CPU temperature and power to SystemMetrics

## [1.3.0] - 2026-01-11

### Added

#### High-Level Typed Methods
All methods return Pydantic models for type-safe data access:

- `get_system_metrics()` - Returns `SystemMetrics` with CPU, memory, uptime
- `typed_get_array()` - Returns `UnraidArray` with state, capacity, disks
- `typed_get_containers()` - Returns `list[DockerContainer]`
- `typed_get_vms()` - Returns `list[VmDomain]`
- `typed_get_ups_devices()` - Returns `list[UPSDevice]`
- `typed_get_shares()` - Returns `list[Share]`
- `get_notification_overview()` - Returns `NotificationOverview`
- `typed_get_vars()` - Returns `Vars` (system configuration)
- `typed_get_registration()` - Returns `Registration` (license info)
- `typed_get_services()` - Returns `list[Service]`
- `typed_get_flash()` - Returns `Flash`
- `typed_get_owner()` - Returns `Owner`
- `typed_get_plugins()` - Returns `list[Plugin]`
- `typed_get_docker_networks()` - Returns `list[DockerNetwork]`
- `typed_get_log_files()` - Returns `list[LogFile]`
- `typed_get_cloud()` - Returns `Cloud`
- `typed_get_connect()` - Returns `Connect`
- `typed_get_remote_access()` - Returns `RemoteAccess`

#### Raw Data Methods
Return dict/list for flexible access:

- `get_array_status()` - Array state and capacity
- `get_disks()` / `get_physical_disks()` - Physical disk info
- `get_shares()` - User shares
- `get_containers()` - Docker containers
- `get_vms()` - Virtual machines
- `get_ups_status()` - UPS devices
- `get_notifications()` - Notifications list
- `get_parity_history()` - Parity check history
- `get_services()` - System services
- `get_vars()` - System variables
- `get_registration()` - Registration info
- `get_flash()` - Flash drive info
- `get_owner()` - Owner info
- `get_plugins()` - Installed plugins
- `get_docker_networks()` - Docker networks
- `get_log_files()` - Log file list
- `get_log_file(path)` - Log file contents
- `get_cloud()` - Cloud status
- `get_connect()` - Connect status
- `get_remote_access()` - Remote access config

#### New Pydantic Models
- `Vars` - System configuration (hostname, timezone, array state, etc.)
- `Registration` - License type, state, owner
- `Service` / `ServiceUptime` - System service status
- `Flash` - Flash drive vendor/product
- `Owner` - Server owner username
- `Plugin` - Plugin name, version, modules
- `DockerNetwork` - Network configuration
- `LogFile` / `LogFileContent` - Log file access
- `Cloud` / `CloudResponse` / `ApiKeyResponse` / `RelayResponse` / `MinigraphqlResponse` - Unraid Connect
- `Connect` / `DynamicRemoteAccessStatus` - Connect configuration
- `RemoteAccess` - Remote access settings
- `SystemMetrics` - CPU, memory, uptime metrics

#### Enhanced Existing Models
- `DockerContainer` - Added `sizeRootFs`, `labels`, `networkSettings`, `mounts`
- `UPSDevice` - Added `model` field
- `UPSBattery` - Added `health` field

### Changed

- `get_vars()` now returns a single `dict` (was incorrectly returning `list`)
- All typed methods follow `typed_get_*` naming convention
- Improved schema alignment with upstream Unraid API

### Fixed

- `Vars` type corrected from list to single object per GraphQL schema
- `Plugin` model aligned with actual API response (only name, version, hasApiModule, hasCliModule)
- `LogFile` model fixed (removed non-existent `id` field, added `size`, `modifiedAt`)
- `Cloud`, `Connect`, `RemoteAccess` models restructured to match actual API responses

## [1.2.2] - 2026-01-10

### Added
- Initial release with core functionality
- GraphQL query/mutation support
- Docker container control (start/stop/restart)
- VM management (start/stop/force-stop/pause/resume)
- Array operations (start/stop)
- Parity check control
- Disk spin up/down
- SSL auto-discovery
- Session injection for Home Assistant

### Models
- `ServerInfo`, `SystemInfo`
- `UnraidArray`, `ArrayDisk`, `ArrayCapacity`
- `DockerContainer`, `ContainerPort`, `ContainerHostConfig`
- `VmDomain`
- `UPSDevice`, `UPSBattery`, `UPSPower`
- `Share`
- `PhysicalDisk`
- `Notification`, `NotificationOverview`

[Unreleased]: https://github.com/tinkerologie/unraid-api/compare/v1.13.2...HEAD
[1.13.2]: https://github.com/tinkerologie/unraid-api/compare/v1.13.1...v1.13.2
[1.8.0]: https://github.com/tinkerologie/unraid-api/compare/v1.7.1...v1.8.0
[1.7.1]: https://github.com/tinkerologie/unraid-api/compare/v1.7.0...v1.7.1
[1.7.0]: https://github.com/tinkerologie/unraid-api/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/tinkerologie/unraid-api/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/tinkerologie/unraid-api/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/tinkerologie/unraid-api/compare/v1.3.1...v1.4.0
[1.3.1]: https://github.com/tinkerologie/unraid-api/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/tinkerologie/unraid-api/compare/v1.2.2...v1.3.0
[1.2.2]: https://github.com/tinkerologie/unraid-api/releases/tag/v1.2.2
