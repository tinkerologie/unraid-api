# unraid-api

[![PyPI version](https://badge.fury.io/py/unraid-api.svg)](https://badge.fury.io/py/unraid-api)
[![Python versions](https://img.shields.io/pypi/pyversions/unraid-api.svg)](https://pypi.org/project/unraid-api/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![codecov](https://codecov.io/gh/tinkerologie/unraid-api/graph/badge.svg?token=QY61Z24GNZ)](https://codecov.io/gh/tinkerologie/unraid-api)

An async Python client library for the Unraid GraphQL API.

## Features

- 🔄 **Async/await** - Built with `aiohttp` for non-blocking operations
- 🏠 **Home Assistant ready** - Accepts external `aiohttp.ClientSession` for integration
- 🔒 **Secure by design** - GraphQL variables, no string interpolation
- 📦 **Typed** - Full type hints with `py.typed` marker (PEP 561)
- 🧩 **Pydantic models** - Structured response parsing
- 🔌 **SSL auto-discovery** - Handles Unraid's "No", "Yes", and "Strict" SSL modes
- ⚡ **Redirect handling** - Supports myunraid.net remote access

## Installation

```bash
pip install unraid-api
```

## Quick Start

```python
import asyncio
from unraid_api import UnraidClient


async def main():
    async with UnraidClient("192.168.1.100", "your-api-key") as client:
        # Test connection
        if await client.test_connection():
            print("Connected!")

            # Get version info
            version = await client.get_version()
            print(f"Unraid {version['unraid']}, API {version['api']}")


asyncio.run(main())
```

## Usage Examples

### Basic Queries

```python
async with UnraidClient(host, api_key) as client:
    # Custom GraphQL query
    result = await client.query("""
        query {
            info {
                os { hostname uptime }
                cpu { name cores threads }
                memory { total used }
            }
        }
    """)
    print(result["info"]["os"]["hostname"])
```

### Docker Container Control

```python
async with UnraidClient(host, api_key) as client:
    # Start a container
    await client.start_container("container:plex")

    # Stop a container
    await client.stop_container("container:plex")
```

### VM Management

```python
async with UnraidClient(host, api_key) as client:
    # Start a VM
    await client.start_vm("vm:windows-11")

    # Stop a VM
    await client.stop_vm("vm:windows-11")
```

### Array Operations

```python
async with UnraidClient(host, api_key) as client:
    # Start/stop array
    await client.start_array()
    await client.stop_array()

    # Parity check
    await client.start_parity_check(correct=True)
    await client.pause_parity_check()
    await client.resume_parity_check()
    await client.cancel_parity_check()

    # Disk spin control
    await client.spin_up_disk("disk:1")
    await client.spin_down_disk("disk:1")
```

### Session Injection (Home Assistant)

```python
import aiohttp
from unraid_api import UnraidClient


async def setup_client(session: aiohttp.ClientSession):
    """Use shared session from Home Assistant."""
    client = UnraidClient(
        host="192.168.1.100",
        api_key="your-api-key",
        session=session,  # Injected session won't be closed by client
        verify_ssl=False,
    )
    return client
```

### Real-Time Subscriptions (WebSocket)

```python
async with UnraidClient(host, api_key) as client:
    # Stream CPU metrics
    async for cpu in client.subscribe_cpu_metrics():
        print(f"CPU: {cpu.percentTotal}%")

    # Stream Docker container stats
    async for stats in client.subscribe_container_stats("container:plex"):
        print(f"CPU: {stats.cpuPercent}%, Mem: {stats.memUsage}")

    # Generic subscription with custom query
    async for data in client.subscribe("subscription { arraySubscription { state } }"):
        print(f"Array state: {data['state']}")
```

A subscription that receives no message for `timeout * 10` seconds (300 s with the default `timeout=30`) raises `UnraidTimeoutError`. This is normal for rare events on a quiet server, such as notifications or UPS changes; catch it and reconnect.

## Pydantic Models

Response data can be parsed into typed models:

```python
from unraid_api.models import DockerContainer, VmDomain, UnraidArray

# Parse container data
container = DockerContainer(**container_data)
print(f"{container.name}: {container.state}")

# Parse array data
array = UnraidArray(**array_data)
print(f"Array: {array.state}, Capacity: {array.capacity.usage_percent}%")
```

## Exception Handling

```python
from unraid_api import UnraidClient
from unraid_api.exceptions import (
    UnraidAPIError,
    UnraidAuthenticationError,
    UnraidConnectionError,
    UnraidSSLError,
    UnraidTimeoutError,
)

async with UnraidClient(host, api_key) as client:
    try:
        await client.query("query { online }")
    except UnraidAuthenticationError:
        print("Invalid API key")
    except UnraidSSLError:
        print("SSL certificate verification failed")
    except UnraidConnectionError:
        print("Cannot reach server")
    except UnraidTimeoutError:
        print("Request timed out")
    except UnraidAPIError as e:
        print(f"API error: {e}")
```

## API Reference

### UnraidClient

#### Core Methods

| Method | Description |
|--------|-------------|
| `test_connection()` | Test if server is reachable |
| `get_version()` | Get Unraid and API version |
| `get_server_info()` | Get server info for device registration |
| `query(query, variables)` | Execute GraphQL query |
| `mutate(mutation, variables)` | Execute GraphQL mutation |

#### High-Level Typed Methods (Pydantic Models)

| Method | Returns | Description |
|--------|---------|-------------|
| `get_system_metrics()` | `SystemMetrics` | CPU, memory, temperature, power, uptime |
| `get_system_metrics_safe()` | `SystemMetrics` | Same as above but omits temperature sensors to avoid waking sleeping disks |
| `typed_get_array()` | `UnraidArray` | Array state, capacity, disks |
| `typed_get_containers()` | `list[DockerContainer]` | All Docker containers |
| `typed_get_containers_safe()` | `list[DockerContainer]` | Same as above but omits expensive fields (container sizes, mounts, network settings) — use for frequent polling |
| `typed_get_vms()` | `list[VmDomain]` | All virtual machines |
| `typed_get_ups_devices()` | `list[UPSDevice]` | UPS devices with battery info |
| `typed_get_shares()` | `list[Share]` | User shares with usage |
| `get_notification_overview()` | `NotificationOverview` | Notification counts |
| `typed_get_vars()` | `Vars` | System configuration variables |
| `typed_get_registration()` | `Registration` | License information |
| `typed_get_services()` | `list[Service]` | System services status |
| `typed_get_flash()` | `Flash` | Flash drive info |
| `typed_get_owner()` | `Owner` | Owner information |
| `typed_get_plugins()` | `list[Plugin]` | Installed API plugins |
| `typed_get_docker_networks()` | `list[DockerNetwork]` | Docker networks |
| `typed_get_log_files()` | `list[LogFile]` | Available log files |
| `typed_get_cloud()` | `Cloud` | ⚠️ **Deprecated** — Cloud status |
| `typed_get_connect()` | `Connect` | ⚠️ **Deprecated** — Connect configuration |
| `typed_get_remote_access()` | `RemoteAccess` | ⚠️ **Deprecated** — Remote access settings |
| `get_container_update_statuses()` | `list[ContainerUpdateStatus]` | Docker container update availability |
| `get_ups_configuration()` | `UPSConfiguration` | UPS hardware/software configuration |
| `get_display_settings()` | `DisplaySettings` | Display and temperature settings |
| `get_docker_port_conflicts()` | `DockerPortConflicts` | Docker LAN port conflicts |
| `get_temperature_metrics()` | `TemperatureMetrics` | Temperature sensors, thresholds, summary |
| `get_network_metrics()` | `list[NetworkMetrics]` | Per-interface network throughput, packet, error counters (API 4.35.0+) |

#### Raw Data Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `get_array_status()` | `dict` | Array state and capacity |
| `get_disks()` | `list[dict]` | Physical disks |
| `get_shares()` | `list[dict]` | User shares |
| `get_containers()` | `list[dict]` | Docker containers |
| `get_vms()` | `list[dict]` | Virtual machines |
| `get_ups_status()` | `list[dict]` | UPS devices |
| `get_notifications()` | `list[dict]` | Notifications |
| `get_parity_history()` | `list[dict]` | Parity check history |
| `get_services()` | `list[dict]` | System services |
| `get_plugins()` | `list[dict]` | Installed plugins |
| `get_docker_networks()` | `list[dict]` | Docker networks |
| `get_log_files()` | `list[dict]` | Log files |
| `get_log_file(path)` | `dict` | Log file contents |

#### Control Methods

| Method | Description |
|--------|-------------|
| `start_container(id)` | Start Docker container |
| `stop_container(id)` | Stop Docker container |
| `restart_container(id)` | Restart Docker container |
| `start_vm(id)` | Start VM |
| `stop_vm(id)` | Stop VM (graceful) |
| `force_stop_vm(id)` | Force stop VM |
| `pause_vm(id)` | Pause VM |
| `resume_vm(id)` | Resume paused VM |
| `start_array()` | Start disk array |
| `stop_array()` | Stop disk array |
| `start_parity_check(correct)` | Start parity check |
| `pause_parity_check()` | Pause parity check |
| `resume_parity_check()` | Resume parity check |
| `cancel_parity_check()` | Cancel parity check |
| `spin_up_disk(id)` | Spin up disk |
| `spin_down_disk(id)` | Spin down disk |
| `update_container(id)` | Update container to latest image |
| `update_containers(ids)` | Update selected containers (API 4.35.0+) |
| `update_all_containers()` | Update every container with a pending update (API 4.35.0+) |
| `update_container_autostart(entries)` | Update container autostart configuration (API 4.37.0+) |
| `refresh_docker_digests()` | Re-check remote image digests ("check for updates", API 4.35.0+) |

#### Subscription Methods (WebSocket)

| Method | Yields | Description |
|--------|--------|-------------|
| `subscribe(subscription, variables)` | `dict` | Generic GraphQL subscription (async generator) |
| `subscribe_container_stats(container_id)` | `DockerContainerStats` | Real-time Docker container resource metrics |
| `subscribe_cpu_metrics()` | `CpuMetrics` | CPU usage per-core and total |
| `subscribe_cpu_telemetry()` | `CpuTelemetryMetrics` | CPU power and temperature |
| `subscribe_memory_metrics()` | `MemoryMetrics` | System memory usage |
| `subscribe_ups_updates()` | `dict` | UPS state changes (raw) |
| `subscribe_array_updates()` | `ArraySubscriptionUpdate` | Array state and capacity changes |
| `subscribe_temperature_metrics()` | `TemperatureMetrics` | Temperature sensor updates |
| `subscribe_network_metrics()` | `list[NetworkMetrics]` | Per-interface network metrics (API 4.35.0+) |

### Models

#### System Models
- `ServerInfo` - Server info for HA device registration
- `SystemInfo` - System information
- `SystemMetrics` - CPU, memory, temperature, power, uptime metrics (includes `TemperatureMetrics`)
- `Vars` - System configuration variables
- `Registration` - License/registration info
- `Flash` - Flash drive information
- `Owner` - Server owner info

#### Storage Models
- `UnraidArray` - Array state and disks
- `ArrayDisk` - Individual array disk
- `ArrayCapacity` - Capacity calculations
- `PhysicalDisk` - Physical disk details (serialNum, firmwareRevision, partitions)
- `DiskPartition` - Disk partition info (name, fsType, size)
- `Share` - User share with usage and comment

#### Docker/VM Models
- `DockerContainer` - Container with ports, state, mounts, Tailscale, template ports
- `DockerNetwork` - Docker network configuration
- `VmDomain` - Virtual machine (id, name, state)
- `TailscaleStatus` - Tailscale hostname, DNS name, and online status
- `ContainerTemplatePort` - Template port configuration
- `ContainerUpdateStatus` - Container update availability
- `DockerPortConflicts` - Port conflict detection

#### Service Models
- `Service` - System service status
- `UPSDevice` - UPS with battery/power info
- `UPSConfiguration` - UPS hardware/software configuration
- `Plugin` - Installed plugin info
- `LogFile` - Log file metadata
- `LogFileContent` - Log file contents
- `DisplaySettings` - Display and temperature threshold settings
- `KeyFile` - Registration key file location and contents

#### Network Models (Deprecated)

- `Cloud` - Unraid Connect cloud status *(deprecated — removed from live API)*
- `Connect` - Connect configuration *(deprecated — removed from live API)*
- `RemoteAccess` - Remote access settings *(deprecated — removed from live API)*

#### Notification Models
- `Notification` - System notification (with link, type, formattedTimestamp)
- `NotificationOverview` - Notification counts
- `NotificationOverviewCounts` - Per-importance notification counts

#### Subscription Models
- `CpuCore` - Per-core CPU usage (percentTotal, percentUser, percentSystem, percentIdle, percentNice, percentIrq, percentGuest, percentSteal)
- `CpuMetrics` - CPU usage with per-core breakdown
- `CpuTelemetryMetrics` - CPU power and temperature
- `MemoryUtilization` - Full memory data (total, used, free, available, active, buffcache, swap)
- `MemoryMetrics` - System memory total/used/free
- `ArraySubscriptionUpdate` - Array state and capacity updates
- `DockerContainerStats` - Real-time container resource metrics
- `TemperatureMetrics` - Temperature sensors with summary and per-sensor data
- `TemperatureSensor` - Individual sensor with reading, thresholds, and status helpers
- `TemperatureReading` - Temperature value, unit, and status
- `TemperatureSummary` - Average, hottest, coolest, warning/critical counts
- `SensorType` - Enum: CPU_PACKAGE, CPU_CORE, DISK, NVME, CUSTOM
- `TemperatureUnit` - Enum: CELSIUS, FAHRENHEIT
- `TemperatureStatus` - Enum: NORMAL, WARNING, CRITICAL, UNKNOWN

### Exceptions

| Exception | Parent | Description |
|-----------|--------|-------------|
| `UnraidAPIError` | `Exception` | Base exception for all API errors |
| `UnraidConnectionError` | `UnraidAPIError` | Connection failures |
| `UnraidSSLError` | `UnraidConnectionError` | SSL certificate verification failures |
| `UnraidAuthenticationError` | `UnraidAPIError` | Authentication failures (invalid API key) |
| `UnraidTimeoutError` | `UnraidAPIError` | Request timeout |

**Note:** `UnraidSSLError` inherits from `UnraidConnectionError`, so it can be caught with either exception type for backwards compatibility.

## Requirements

- Python 3.14+
- Unraid 7.2.4+ with latest Unraid API
- API key with appropriate permissions

## Development

```bash
# Clone repository
git clone https://github.com/tinkerologie/unraid-api.git
cd unraid-api

# Install dependencies with uv
uv sync --all-extras

# Run tests
uv run pytest tests/ -v --cov=src/unraid_api

# Lint and type check
uv run ruff check .
uv run ruff format .
uv run mypy src/
```

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details. Earlier releases were MIT licensed; see [NOTICE](NOTICE).

## Contributing

Contributions welcome! Please ensure:
1. Tests are written first (TDD)
2. No linting errors (`ruff check . && mypy src/`)
3. GraphQL variables used (no string interpolation)

## Links

- [Official Unraid API Repository](https://github.com/unraid/api)
- [GraphQL API Reference](UNRAIDAPI.md)
- [PyPI Package](https://pypi.org/project/unraid-api/)
