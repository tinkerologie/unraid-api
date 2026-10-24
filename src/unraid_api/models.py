"""Pydantic models for Unraid GraphQL API responses."""

from __future__ import annotations

import math
import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    """Parse datetime from ISO format string or return datetime as-is.

    Args:
        value: ISO format string, datetime object, or None.

    Returns:
        Parsed datetime or None.

    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # Python's fromisoformat doesn't handle trailing Z, normalize first
        normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
        return datetime.fromisoformat(normalized)
    return None


# Reusable annotated type for datetime fields parsed from ISO format strings.
# Use this instead of repeating @field_validator("field", mode="before") on
# every datetime field.
ParsedDatetime = Annotated[datetime | None, BeforeValidator(_parse_datetime)]


# ANSI CSI escape sequences (e.g. ``\x1b[J`` clear-screen, ``\x1b[H`` cursor-home).
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(value: str | None) -> str | None:
    """Remove ANSI CSI escape sequences from a string.

    The Unraid GraphQL backend streams raw ``docker stats`` terminal output for
    container statistics. The first row of every sample cycle carries
    clear-screen/cursor-home escapes (``\\x1b[J\\x1b[H``) glued onto the field,
    corrupting values such as the container ``id`` (see issue #71). Non-string
    values pass through untouched.

    Args:
        value: A possibly escape-laden string, or None.

    Returns:
        The string with ANSI CSI sequences removed, or the value unchanged.

    """
    if isinstance(value, str):
        return _ANSI_ESCAPE_RE.sub("", value)
    return value


# Reusable annotated type for string fields that may contain ANSI terminal
# control sequences (see DockerContainerStats / issue #71).
SanitizedStr = Annotated[str | None, BeforeValidator(_strip_ansi)]


def format_bytes(bytes_value: int | None) -> str | None:
    """Convert bytes to human-readable string.

    Args:
        bytes_value: Number of bytes, or None.

    Returns:
        Human-readable string (e.g., "1.5 GB") or None if input is None.

    """
    if bytes_value is None:
        return None
    if bytes_value == 0:
        return "0 B"

    units = ("B", "KB", "MB", "GB", "TB", "PB")
    exponent = min(int(math.log2(abs(bytes_value)) // 10), len(units) - 1)
    value = bytes_value / (1024**exponent)

    if value == int(value):
        return f"{int(value)} {units[exponent]}"
    return f"{value:.1f} {units[exponent]}"


def _format_duration(seconds: int) -> str:
    """Format seconds into a human-readable duration string.

    Args:
        seconds: Duration in seconds.

    Returns:
        Human-readable string like "2 hours 15 minutes 30 seconds".

    """
    seconds = max(seconds, 0)

    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    parts = []
    if hours:
        parts.append(f"{hours} {'hour' if hours == 1 else 'hours'}")
    if minutes:
        parts.append(f"{minutes} {'minute' if minutes == 1 else 'minutes'}")
    if secs or not parts:
        parts.append(f"{secs} {'second' if secs == 1 else 'seconds'}")

    return " ".join(parts)


class UnraidBaseModel(BaseModel):
    """Base model that ignores unknown fields for forward compatibility."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# =============================================================================
# System Info Models
# =============================================================================


class InfoSystem(UnraidBaseModel):
    """System information (manufacturer, model, version, serial, UUID)."""

    id: str | None = None
    uuid: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    version: str | None = None
    serial: str | None = None
    sku: str | None = None
    virtual: bool | None = None


class CpuPackages(UnraidBaseModel):
    """CPU package information (temperature, power consumption)."""

    id: str | None = None
    temp: list[float] = []
    power: list[float] = []
    totalPower: float | None = None


class InfoCpu(UnraidBaseModel):
    """CPU information (brand, threads, cores, temperature, power, specs)."""

    id: str | None = None
    brand: str | None = None
    manufacturer: str | None = None
    vendor: str | None = None
    family: str | None = None
    model: str | None = None
    stepping: int | None = None
    revision: str | None = None
    voltage: str | None = None
    speed: float | None = None
    speedmin: float | None = None
    speedmax: float | None = None
    threads: int | None = None
    cores: int | None = None
    processors: int | None = None
    socket: str | None = None
    cache: dict[str, Any] | None = None
    flags: list[str] = []
    topology: list[Any] = []
    packages: CpuPackages = Field(default_factory=CpuPackages)


class InfoOs(UnraidBaseModel):
    """Operating system information (hostname, uptime, kernel, platform)."""

    id: str | None = None
    hostname: str | None = None
    platform: str | None = None
    distro: str | None = None
    release: str | None = None
    codename: str | None = None
    kernel: str | None = None
    arch: str | None = None
    fqdn: str | None = None
    build: str | None = None
    servicepack: str | None = None
    uptime: ParsedDatetime = None
    logofile: str | None = None
    serial: str | None = None
    uefi: bool | None = None


class PackageVersions(UnraidBaseModel):
    """Installed package versions."""

    docker: str | None = None
    git: str | None = None
    nginx: str | None = None
    node: str | None = None
    npm: str | None = None
    openssl: str | None = None
    php: str | None = None
    pm2: str | None = None


class CoreVersions(UnraidBaseModel):
    """Core version information."""

    unraid: str | None = None
    api: str | None = None
    kernel: str | None = None


class InfoVersions(UnraidBaseModel):
    """Version information container."""

    id: str | None = None
    core: CoreVersions = Field(default_factory=CoreVersions)
    packages: PackageVersions | None = None


class MemoryLayout(UnraidBaseModel):
    """Individual memory module (DIMM) details."""

    id: str | None = None
    size: int | None = None
    bank: str | None = None
    type: str | None = None
    clockSpeed: int | None = None
    partNum: str | None = None
    serialNum: str | None = None
    manufacturer: str | None = None
    formFactor: str | None = None
    voltageConfigured: int | None = None
    voltageMin: int | None = None
    voltageMax: int | None = None


class InfoMemory(UnraidBaseModel):
    """System memory layout information."""

    id: str | None = None
    layout: list[MemoryLayout] = []


class InfoDisplayCase(UnraidBaseModel):
    """Display case icon information."""

    id: str | None = None
    base64: str | None = None
    error: str | None = None
    icon: str | None = None
    url: str | None = None


class InfoDisplay(UnraidBaseModel):
    """System display and UI preferences."""

    id: str | None = None
    case: InfoDisplayCase | None = None
    theme: str | None = None
    unit: str | None = None
    scale: bool | None = None
    tabs: bool | None = None
    resize: bool | None = None
    wwn: bool | None = None
    total: bool | None = None
    usage: bool | None = None
    text: bool | None = None
    warning: int | None = None
    critical: int | None = None
    hot: int | None = None
    max: int | None = None
    locale: str | None = None


class InfoGpu(UnraidBaseModel):
    """GPU device details."""

    id: str | None = None
    class_: str | None = Field(default=None, alias="class")
    productid: str | None = None
    type: str | None = None
    typeid: str | None = None
    vendorname: str | None = None
    blacklisted: bool | None = None


class InfoNetwork(UnraidBaseModel):
    """Network adapter hardware information."""

    id: str | None = None
    dhcp: bool | None = None
    iface: str | None = None
    mac: str | None = None
    model: str | None = None
    speed: int | None = None
    vendor: str | None = None
    virtual: bool | None = None


class InfoPci(UnraidBaseModel):
    """PCI device details."""

    id: str | None = None
    class_: str | None = Field(default=None, alias="class")
    productid: str | None = None
    productname: str | None = None
    type: str | None = None
    typeid: str | None = None
    vendorid: str | None = None
    vendorname: str | None = None
    blacklisted: bool | None = None


class InfoUsb(UnraidBaseModel):
    """USB device details."""

    id: str | None = None
    bus: str | None = None
    device: str | None = None
    name: str | None = None


class InfoDevices(UnraidBaseModel):
    """System hardware devices."""

    id: str | None = None
    gpu: list[InfoGpu] = []
    network: list[InfoNetwork] = []
    pci: list[InfoPci] = []
    usb: list[InfoUsb] = []


class InfoBaseboard(UnraidBaseModel):
    """Baseboard/motherboard hardware information."""

    id: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    version: str | None = None
    serial: str | None = None
    assetTag: str | None = None
    memMax: float | None = None
    memSlots: float | None = None


class InfoNetworkIpv4Address(UnraidBaseModel):
    """IPv4 address and netmask for a network interface."""

    address: str
    netmask: str | None = None


class InfoNetworkIpv6Address(UnraidBaseModel):
    """IPv6 address and prefix length for a network interface."""

    address: str
    prefixLength: int | None = None


class InfoNetworkInterface(UnraidBaseModel):
    """Network interface hardware and IP configuration."""

    id: str
    name: str
    description: str | None = None
    ipAddress: str | None = None
    netmask: str | None = None
    gateway: str | None = None
    macAddress: str | None = None
    speed: int | None = None
    duplex: str | None = None
    mtu: int | None = None
    internal: bool | None = None
    virtual: bool | None = None
    useDhcp: bool | None = None
    useDhcp6: bool | None = None
    protocol: str | None = None
    operstate: str | None = None
    status: str | None = None
    type: str | None = None
    vlanId: int | None = None
    ipv4Addresses: list[InfoNetworkIpv4Address] = []
    ipv6Address: str | None = None
    ipv6Addresses: list[InfoNetworkIpv6Address] = []
    ipv6Gateway: str | None = None
    ipv6Netmask: str | None = None

    @property
    def mac(self) -> str | None:
        """Compatibility property for MAC address."""
        return self.macAddress

    @property
    def dhcp(self) -> bool | None:
        """Compatibility property for DHCP enabled."""
        return self.useDhcp


class SystemInfo(UnraidBaseModel):
    """Complete system information."""

    id: str | None = None
    time: ParsedDatetime = None
    system: InfoSystem = Field(default_factory=InfoSystem)
    cpu: InfoCpu = Field(default_factory=InfoCpu)
    os: InfoOs = Field(default_factory=InfoOs)
    versions: InfoVersions = Field(default_factory=InfoVersions)
    memory: InfoMemory = Field(default_factory=InfoMemory)
    display: InfoDisplay = Field(default_factory=InfoDisplay)
    devices: InfoDevices = Field(default_factory=InfoDevices)
    baseboard: InfoBaseboard = Field(default_factory=InfoBaseboard)
    networkInterfaces: list[InfoNetworkInterface] = []
    primaryNetwork: InfoNetworkInterface | None = None


# =============================================================================
# Metrics Models
# =============================================================================


class CpuUtilization(UnraidBaseModel):
    """CPU utilization metrics."""

    percentTotal: float | None = None


class MemoryUtilization(UnraidBaseModel):
    """Memory utilization metrics."""

    total: int | None = None
    used: int | None = None
    free: int | None = None
    available: int | None = None
    active: int | None = None
    buffcache: int | None = None
    percentTotal: float | None = None
    swapTotal: int | None = None
    swapUsed: int | None = None
    swapFree: int | None = None
    percentSwapTotal: float | None = None


class Metrics(UnraidBaseModel):
    """System metrics container."""

    cpu: CpuUtilization = Field(default_factory=CpuUtilization)
    memory: MemoryUtilization = Field(default_factory=MemoryUtilization)


# =============================================================================
# Temperature Models
# =============================================================================


class SensorType(StrEnum):
    """Temperature sensor type."""

    CPU_PACKAGE = "CPU_PACKAGE"
    CPU_CORE = "CPU_CORE"
    MOTHERBOARD = "MOTHERBOARD"
    CHIPSET = "CHIPSET"
    GPU = "GPU"
    DISK = "DISK"
    NVME = "NVME"
    AMBIENT = "AMBIENT"
    VRM = "VRM"
    CUSTOM = "CUSTOM"


class TemperatureUnit(StrEnum):
    """Temperature measurement unit."""

    CELSIUS = "CELSIUS"
    FAHRENHEIT = "FAHRENHEIT"
    KELVIN = "KELVIN"
    RANKINE = "RANKINE"


class TemperatureStatus(StrEnum):
    """Temperature status level."""

    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class TemperatureReading(UnraidBaseModel):
    """A temperature reading with value and unit."""

    value: float | None = None
    unit: TemperatureUnit | str | None = None
    status: TemperatureStatus | str | None = None


class TemperatureSensorSummary(UnraidBaseModel):
    """A named sensor with its current reading (used in summary hottest/coolest)."""

    name: str | None = None
    current: TemperatureReading | None = None


class TemperatureSensor(UnraidBaseModel):
    """A full temperature sensor with current, min, max, and thresholds."""

    id: str
    name: str | None = None
    type: SensorType | str | None = None
    location: str | None = None
    current: TemperatureReading | None = None
    min: TemperatureReading | None = None
    max: TemperatureReading | None = None
    warning: int | None = None
    critical: int | None = None
    history: list[TemperatureReading] = []

    @property
    def is_critical(self) -> bool:
        """Return True if the sensor status is CRITICAL."""
        if self.current and self.current.status:
            return str(self.current.status) == TemperatureStatus.CRITICAL
        return False

    @property
    def is_warning(self) -> bool:
        """Return True if the sensor status is WARNING."""
        if self.current and self.current.status:
            return str(self.current.status) == TemperatureStatus.WARNING
        return False

    @property
    def temperature(self) -> float | None:
        """Return the current temperature value."""
        if self.current:
            return self.current.value
        return None


class TemperatureSummary(UnraidBaseModel):
    """Summary of temperature metrics across all sensors."""

    average: float | None = None
    hottest: TemperatureSensorSummary | None = None
    coolest: TemperatureSensorSummary | None = None
    warningCount: int | None = None
    criticalCount: int | None = None


# Plausible range for any real hardware temperature reading (°C).
# CPUs thermal-throttle at ~100 °C, so any reading above that — and in
# particular the 105-120 °C readings that nct6793 reports on unused
# PECI/AUXTIN pins — are treated as disconnected-pin noise, not signal.
_PLAUSIBLE_TEMP_MIN_C = -20.0
_PLAUSIBLE_TEMP_MAX_C = 105.0

# Voltage rails (e.g. "nct6793-isa-0290 in0") and fan tachometers
# (e.g. "Array Fan", "fan5") are routinely mis-typed as temperature
# sensors by the upstream Unraid API.
_VOLTAGE_NAME_RE = re.compile(r"(?:^|[^A-Za-z])in\d+(?:$|[^A-Za-z])", re.IGNORECASE)
_FAN_NAME_RE = re.compile(r"\bfan\d*\b", re.IGNORECASE)


def _is_bogus_temperature_sensor(sensor: TemperatureSensor) -> bool:
    """Return True if the sensor is clearly not a real temperature reading."""
    haystack = f"{sensor.name or ''} {sensor.id or ''}"
    if _VOLTAGE_NAME_RE.search(haystack):
        return True
    if _FAN_NAME_RE.search(haystack):
        return True

    reading = sensor.current
    if reading is None or reading.value is None:
        return False

    value = reading.value
    if not math.isfinite(value):
        return True
    return value < _PLAUSIBLE_TEMP_MIN_C or value > _PLAUSIBLE_TEMP_MAX_C


class TemperatureMetrics(UnraidBaseModel):
    """Temperature metrics container with summary and individual sensors.

    Bogus sensors (voltage rails, fan tachometers, disconnected PECI/TSI
    pins) are filtered out after parsing, and the summary (average,
    hottest, coolest, warning/critical counts) is recomputed from the
    remaining valid sensors. This ensures consumers like the Home
    Assistant integration never see nonsense values.
    """

    id: str | None = None
    summary: TemperatureSummary | None = None
    sensors: list[TemperatureSensor] = []

    @model_validator(mode="after")
    def _sanitize_sensors_and_summary(self) -> TemperatureMetrics:
        valid = [s for s in self.sensors if not _is_bogus_temperature_sensor(s)]
        self.sensors = valid

        readings: list[tuple[TemperatureSensor, float]] = [
            (s, s.current.value)
            for s in valid
            if s.current is not None and s.current.value is not None
        ]
        if not readings:
            self.summary = None
            return self

        values = [value for _, value in readings]
        hottest_sensor, _ = max(readings, key=lambda item: item[1])
        coolest_sensor, _ = min(readings, key=lambda item: item[1])

        def _status(sensor: TemperatureSensor) -> str:
            return str(sensor.current.status) if sensor.current else ""

        warning_count = sum(
            1 for s, _ in readings if _status(s) == TemperatureStatus.WARNING
        )
        critical_count = sum(
            1 for s, _ in readings if _status(s) == TemperatureStatus.CRITICAL
        )

        def _summary_entry(sensor: TemperatureSensor) -> TemperatureSensorSummary:
            current = sensor.current
            reading = (
                TemperatureReading(
                    value=current.value,
                    unit=current.unit,
                    status=current.status,
                )
                if current is not None
                else None
            )
            return TemperatureSensorSummary(name=sensor.name, current=reading)

        self.summary = TemperatureSummary(
            average=sum(values) / len(values),
            hottest=_summary_entry(hottest_sensor),
            coolest=_summary_entry(coolest_sensor),
            warningCount=warning_count,
            criticalCount=critical_count,
        )
        return self

    def get_sensors_by_type(
        self, sensor_type: SensorType | str
    ) -> list[TemperatureSensor]:
        """Return sensors filtered by type.

        Args:
            sensor_type: The SensorType to filter by.

        Returns:
            List of matching TemperatureSensor objects.

        """
        return [s for s in self.sensors if s.type == str(sensor_type)]

    @property
    def disk_sensors(self) -> list[TemperatureSensor]:
        """Return all DISK-type sensors."""
        return self.get_sensors_by_type(SensorType.DISK)

    @property
    def nvme_sensors(self) -> list[TemperatureSensor]:
        """Return all NVME-type sensors."""
        return self.get_sensors_by_type(SensorType.NVME)

    @property
    def cpu_sensors(self) -> list[TemperatureSensor]:
        """Return all CPU_PACKAGE and CPU_CORE sensors."""
        return self.get_sensors_by_type(
            SensorType.CPU_PACKAGE
        ) + self.get_sensors_by_type(SensorType.CPU_CORE)


# =============================================================================
# Array Models
# =============================================================================


class CapacityKilobytes(UnraidBaseModel):
    """Storage capacity in kilobytes."""

    total: int = 0
    used: int = 0
    free: int = 0


class ArrayCapacity(UnraidBaseModel):
    """Array capacity information."""

    kilobytes: CapacityKilobytes = Field(default_factory=CapacityKilobytes)

    @property
    def total_bytes(self) -> int:
        """Return total capacity in bytes."""
        return self.kilobytes.total * 1024

    @property
    def used_bytes(self) -> int:
        """Return used capacity in bytes."""
        return self.kilobytes.used * 1024

    @property
    def free_bytes(self) -> int:
        """Return free capacity in bytes."""
        return self.kilobytes.free * 1024

    @property
    def usage_percent(self) -> float:
        """Return usage percentage."""
        if self.kilobytes.total == 0:
            return 0.0
        return self.kilobytes.used / self.kilobytes.total * 100


class ParityCheck(UnraidBaseModel):
    """Parity check status."""

    status: str | None = None
    progress: int | None = None
    errors: int | None = None
    running: bool | None = None
    paused: bool | None = None
    correcting: bool | None = None
    speed: str | None = None
    date: ParsedDatetime = None
    duration: int | None = None
    elapsed: int | None = None  # Elapsed time in seconds
    estimated: int | None = None  # Estimated time remaining

    @property
    def is_running(self) -> bool:
        """Return True if the parity check is actively running or paused."""
        if self.status is None:
            return False
        return self.status.upper() in {"RUNNING", "PAUSED"}

    @property
    def has_problem(self) -> bool:
        """Return True if there are errors or the check has failed."""
        if self.status is not None and self.status.upper() == "FAILED":
            return True
        return bool(self.errors is not None and self.errors > 0)


class ArrayDisk(UnraidBaseModel):
    """Array disk information.

    This model represents disks as returned by the array endpoint,
    which does NOT wake sleeping disks. Use this for periodic polling.

    Note:
        - temp will be null/0 for disks in standby mode
        - isSpinning indicates if disk is active (True) or standby (False)
        - This is safe for Home Assistant integrations that poll frequently
        - On ZFS pools, fsUsed may be 0 or None; properties fall back to
          computing used space from fsSize - fsFree when available.

    """

    id: str
    idx: int | None = None  # Optional - boot device doesn't have idx
    device: str | None = None
    name: str | None = None
    type: str | None = None
    size: int | None = None
    fsSize: int | None = None
    fsUsed: int | None = None
    fsFree: int | None = None
    fsType: str | None = None  # Filesystem type (XFS, BTRFS, vfat, etc.)
    temp: int | None = None  # Temperature in Celsius (null when disk is standby)
    status: str | None = None
    isSpinning: bool | None = None  # True = active, False = standby/sleeping
    smartStatus: str | None = None  # Only available via physical disk query
    rotational: bool | None = None  # True for HDD, False for SSD
    numReads: int | None = None  # Number of reads
    numWrites: int | None = None  # Number of writes
    numErrors: int | None = None  # Number of errors
    warning: int | None = None  # Warning temperature threshold
    critical: int | None = None  # Critical temperature threshold
    color: str | None = None  # Disk color status indicator
    format: str | None = None  # Disk format
    transport: str | None = None  # Transport type (e.g., "sata")
    comment: str | None = None  # User comment/description
    exportable: bool | None = None  # Whether disk is exportable

    @property
    def is_standby(self) -> bool:
        """Return True if disk is in standby/sleeping mode."""
        return self.isSpinning is False

    @property
    def is_healthy(self) -> bool:
        """Return True if disk status indicates normal operation."""
        if self.status is None:
            return False
        return self.status.upper() == "DISK_OK"

    @property
    def size_bytes(self) -> int | None:
        """Return disk size in bytes."""
        return self.size * 1024 if self.size is not None else None

    @property
    def fs_size_bytes(self) -> int | None:
        """Return filesystem size in bytes."""
        return self.fsSize * 1024 if self.fsSize is not None else None

    @property
    def fs_used_bytes(self) -> int | None:
        """Return filesystem used space in bytes.

        Falls back to (fsSize - fsFree) when fsUsed is 0 or None,
        which is common on ZFS pools where the API reports fsUsed=0.
        """
        # If fsUsed is positive, use it directly
        if self.fsUsed is not None and self.fsUsed > 0:
            return self.fsUsed * 1024
        # Fallback: compute from fsSize - fsFree (ZFS workaround)
        if self.fsSize is not None and self.fsFree is not None:
            computed = self.fsSize - self.fsFree
            if computed >= 0:
                return computed * 1024
        # If fsUsed is explicitly 0 (not None), preserve that
        if self.fsUsed is not None:
            return self.fsUsed * 1024
        return None

    @property
    def fs_free_bytes(self) -> int | None:
        """Return filesystem free space in bytes."""
        return self.fsFree * 1024 if self.fsFree is not None else None

    @property
    def usage_percent(self) -> float | None:
        """Return disk usage percentage.

        Falls back to computing from fsSize and fsFree when fsUsed is
        0 or None (ZFS pool workaround).
        """
        if self.fsSize is None or self.fsSize == 0:
            return None

        # Use fsUsed directly if positive
        if self.fsUsed is not None and self.fsUsed > 0:
            return (self.fsUsed / self.fsSize) * 100

        # Fallback: compute from fsSize - fsFree
        if self.fsFree is not None:
            computed_used = self.fsSize - self.fsFree
            if computed_used >= 0:
                return (computed_used / self.fsSize) * 100

        return None


class UnraidArray(UnraidBaseModel):
    """Complete array information."""

    id: str | None = None
    state: str | None = None
    capacity: ArrayCapacity = Field(default_factory=ArrayCapacity)
    parityCheckStatus: ParityCheck = Field(default_factory=ParityCheck)
    disks: list[ArrayDisk] = []
    parities: list[ArrayDisk] = []
    caches: list[ArrayDisk] = []
    boot: ArrayDisk | None = None
    bootDevices: list[ArrayDisk] = []  # Boot devices (v4.30.0+)


# =============================================================================
# Physical Disk Models (WARNING: Queries wake sleeping disks!)
# =============================================================================


class PhysicalDisk(UnraidBaseModel):
    """Physical disk information from the disks endpoint.

    WARNING: Querying physical disks WAKES SLEEPING DISKS!
    Use ArrayDisk (from get_array_disks) for disk info without wake.

    This model contains hardware-level disk information including SMART
    status, which requires disk access and will spin up any sleeping disk.

    """

    id: str
    device: str | None = None
    name: str | None = None
    vendor: str | None = None
    size: int | None = None  # Size in bytes
    type: str | None = None
    interfaceType: str | None = None  # SATA, SAS, NVMe, USB, etc.
    smartStatus: str | None = None  # OK, UNKNOWN, FAILING, etc.
    temperature: float | None = None  # Temperature in Celsius
    isSpinning: bool | None = None
    serialNum: str | None = None  # Disk serial number
    firmwareRevision: str | None = None  # Firmware version
    partitions: list[DiskPartition] | None = None  # Disk partitions


# =============================================================================
# Docker Models
# =============================================================================


class ContainerPort(UnraidBaseModel):
    """Docker container port mapping."""

    ip: str | None = None
    privatePort: int | None = None
    publicPort: int | None = None
    type: str | None = None


class ContainerHostConfig(UnraidBaseModel):
    """Docker container host configuration."""

    networkMode: str | None = None


class TailscaleExitNodeStatus(UnraidBaseModel):
    """Tailscale exit-node status reported for a container."""

    online: bool | None = None
    tailscaleIps: list[str] | None = None


class TailscaleStatus(UnraidBaseModel):
    """Tailscale status for a Docker container."""

    hostname: str | None = None
    dnsName: str | None = None
    online: bool | None = None
    version: str | None = None
    latestVersion: str | None = None
    updateAvailable: bool | None = None
    relay: str | None = None
    relayName: str | None = None
    tailscaleIps: list[str] | None = None
    primaryRoutes: list[str] | None = None
    isExitNode: bool | None = None
    exitNodeStatus: TailscaleExitNodeStatus | None = None
    webUiUrl: str | None = None
    keyExpiry: ParsedDatetime = None
    keyExpiryDays: int | None = None
    keyExpired: bool | None = None
    backendState: str | None = None
    authUrl: str | None = None


class ContainerTemplatePort(UnraidBaseModel):
    """Docker container template port mapping."""

    ip: str | None = None
    privatePort: int | None = None
    publicPort: int | None = None
    type: str | None = None


class DockerContainerStats(UnraidBaseModel):
    """Docker container resource statistics.

    Available via the ``dockerContainerStats`` GraphQL subscription.
    Not queryable inline on containers.

    Attributes:
        id: Container prefixed ID.
        cpuPercent: CPU usage percentage.
        memUsage: Memory usage string (e.g. "100MB / 1GB").
        memPercent: Memory usage percentage.
        netIO: Network I/O string (e.g. "100MB / 1GB").
        blockIO: Block I/O string (e.g. "100MB / 1GB").

    """

    id: SanitizedStr = None
    cpuPercent: float | None = None
    memUsage: SanitizedStr = None
    memPercent: float | None = None
    netIO: SanitizedStr = None
    blockIO: SanitizedStr = None


class DockerContainer(UnraidBaseModel):
    """Docker container information."""

    id: str
    name: str
    names: list[str] = []  # Container may have multiple names
    state: str | None = None
    status: str | None = None  # Status message (e.g., "Up 5 days")
    image: str | None = None
    imageId: str | None = None
    command: str | None = None
    created: int | None = None  # Unix timestamp
    sizeRootFs: int | None = None  # Total size of files in bytes
    labels: dict[str, Any] | None = None
    networkSettings: dict[str, Any] | None = None
    mounts: list[dict[str, Any]] | None = None
    webUiUrl: str | None = None
    iconUrl: str | None = None
    autoStart: bool | None = None
    isUpdateAvailable: bool | None = None
    isOrphaned: bool | None = None
    hostConfig: ContainerHostConfig | None = None
    ports: list[ContainerPort] = []
    # Extended fields (v4.30.0+)
    sizeRw: int | None = None  # Read-write size in bytes
    sizeLog: int | None = None  # Log size in bytes
    autoStartOrder: int | None = None  # Auto-start order priority
    autoStartWait: int | None = None  # Seconds to wait before starting next
    shell: str | None = None  # Default shell (e.g., "sh", "bash")
    templatePath: str | None = None  # Template XML path
    projectUrl: str | None = None  # Project URL
    registryUrl: str | None = None  # Registry URL
    supportUrl: str | None = None  # Support URL
    tailscaleEnabled: bool | None = None  # Whether Tailscale is enabled
    tailscaleStatus: TailscaleStatus | None = None  # Tailscale connection status
    isRebuildReady: bool | None = None  # Whether container is ready to rebuild
    templatePorts: list[ContainerTemplatePort] | None = None  # Template port mappings
    lanIpPorts: list[str] | None = None  # LAN IP port strings

    @property
    def is_running(self) -> bool:
        """Return True if the container is running."""
        if self.state is None:
            return False
        return self.state.lower() == "running"

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> DockerContainer:
        """Create DockerContainer from API response.

        Extracts name from the names array, removing leading slashes.

        Args:
            data: API response data for a container.

        Returns:
            DockerContainer instance with parsed data.

        """
        names = data.get("names", []) or []
        # Extract name from names array, removing leading slash
        name = names[0].lstrip("/") if names else data.get("id", "unknown")

        host_config = data.get("hostConfig")

        return cls(
            id=data.get("id", ""),
            name=name,
            names=names,
            state=data.get("state"),
            status=data.get("status"),
            image=data.get("image"),
            imageId=data.get("imageId"),
            command=data.get("command"),
            created=data.get("created"),
            sizeRootFs=data.get("sizeRootFs"),
            labels=data.get("labels"),
            networkSettings=data.get("networkSettings"),
            mounts=data.get("mounts"),
            webUiUrl=data.get("webUiUrl"),
            iconUrl=data.get("iconUrl"),
            autoStart=data.get("autoStart"),
            isUpdateAvailable=data.get("isUpdateAvailable"),
            isOrphaned=data.get("isOrphaned"),
            hostConfig=(ContainerHostConfig(**host_config) if host_config else None),
            ports=[ContainerPort(**p) for p in (data.get("ports") or [])],
            sizeRw=data.get("sizeRw"),
            sizeLog=data.get("sizeLog"),
            autoStartOrder=data.get("autoStartOrder"),
            autoStartWait=data.get("autoStartWait"),
            shell=data.get("shell"),  # nosec B604 - model field, not subprocess
            templatePath=data.get("templatePath"),
            projectUrl=data.get("projectUrl"),
            registryUrl=data.get("registryUrl"),
            supportUrl=data.get("supportUrl"),
            tailscaleEnabled=data.get("tailscaleEnabled"),
            tailscaleStatus=(
                TailscaleStatus(**data["tailscaleStatus"])
                if data.get("tailscaleStatus")
                else None
            ),
            isRebuildReady=data.get("isRebuildReady"),
            templatePorts=(
                [ContainerTemplatePort(**p) for p in data["templatePorts"]]
                if data.get("templatePorts")
                else None
            ),
            lanIpPorts=data.get("lanIpPorts"),
        )


class DockerNetwork(UnraidBaseModel):
    """Docker network information."""

    id: str
    name: str
    created: str | None = None
    scope: str | None = None
    driver: str | None = None
    enableIPv6: bool | None = None
    internal: bool | None = None
    attachable: bool | None = None
    ingress: bool | None = None
    configOnly: bool | None = None


class FlatOrganizerEntry(UnraidBaseModel):
    """An entry (folder or container) in the Docker organizer tree."""

    id: str
    name: str
    type: str
    parentId: str | None = None
    childrenIds: list[str] = []
    depth: float = 0.0
    hasChildren: bool = False
    path: list[str] = []
    position: float = 0.0


class ResolvedOrganizerView(UnraidBaseModel):
    """View configuration within the Docker organizer."""

    id: str
    name: str
    rootId: str | None = None
    prefs: dict[str, Any] | None = None
    flatEntries: list[FlatOrganizerEntry] = []


class ResolvedOrganizerV1(UnraidBaseModel):
    """Docker organizer hierarchy and folder views."""

    version: float = 1.0
    views: list[ResolvedOrganizerView] = []


# =============================================================================
# VM Models
# =============================================================================


class VmDomain(UnraidBaseModel):
    """Virtual machine domain information."""

    id: str
    name: str
    state: str | None = None
    uuid: str | None = None

    @property
    def is_running(self) -> bool:
        """Return True if the VM is running or idle."""
        if self.state is None:
            return False
        return self.state.lower() in {"running", "idle"}


# =============================================================================
# UPS Models
# =============================================================================


class UPSBattery(UnraidBaseModel):
    """UPS battery information."""

    chargeLevel: int | None = None
    estimatedRuntime: int | None = None
    health: str | None = None  # Battery health status

    @property
    def runtime_formatted(self) -> str | None:
        """Return estimated runtime as a human-readable string.

        Returns:
            Formatted string like "2 hours 15 minutes" or None if unavailable.

        """
        if self.estimatedRuntime is None:
            return None
        return _format_duration(self.estimatedRuntime)


class UPSPower(UnraidBaseModel):
    """UPS power information."""

    inputVoltage: float | None = None
    outputVoltage: float | None = None
    loadPercentage: float | None = None
    nominalPower: int | None = None
    currentPower: float | None = None


class UPSDevice(UnraidBaseModel):
    """UPS device information."""

    id: str
    name: str
    model: str | None = None
    status: str | None = None
    battery: UPSBattery = Field(default_factory=UPSBattery)
    power: UPSPower = Field(default_factory=UPSPower)

    @property
    def is_connected(self) -> bool:
        """Return True if the UPS is connected and communicating."""
        if self.status is None:
            return False
        return self.status.upper() not in {"OFFLINE", "OFF"}

    def calculate_power_watts(self, nominal_power: int) -> float | None:
        """Calculate current power draw in watts.

        Args:
            nominal_power: The UPS nominal power capacity in watts
                (from user configuration, not available from the API).

        Returns:
            Power draw in watts rounded to 1 decimal, or None if
            load percentage is unavailable.

        """
        if self.power.loadPercentage is None:
            return None
        return round((self.power.loadPercentage / 100) * nominal_power, 1)


# =============================================================================
# Share Models
# =============================================================================


class Share(UnraidBaseModel):
    """User share information."""

    id: str
    name: str
    size: int | None = None  # Size in KB (often returns 0)
    used: int | None = None  # Used in KB
    free: int | None = None  # Free in KB
    # Extended fields (v4.30.0+)
    cache: str | None = None  # Cache setting (e.g., "no", "yes", "prefer", "only")
    include: list[str] | None = None  # Included disks
    exclude: list[str] | None = None  # Excluded disks
    nameOrig: str | None = None  # Original share name
    allocator: str | None = None  # Allocation method
    splitLevel: str | None = None  # Split level
    floor: str | None = None  # Minimum free space floor
    cow: str | None = None  # Copy-on-write setting
    color: str | None = None  # Share color indicator
    luksStatus: str | None = None  # LUKS encryption status
    comment: str | None = None  # Share comment/description

    @property
    def size_bytes(self) -> int | None:
        """Return share size in bytes (calculates from used+free if size=0)."""
        if self.size is not None and self.size > 0:
            return self.size * 1024
        if self.used is not None and self.free is not None:
            return (self.used + self.free) * 1024
        return None

    @property
    def used_bytes(self) -> int | None:
        """Return used space in bytes."""
        return self.used * 1024 if self.used is not None else None

    @property
    def free_bytes(self) -> int | None:
        """Return free space in bytes."""
        return self.free * 1024 if self.free is not None else None

    @property
    def usage_percent(self) -> float | None:
        """Return share usage percentage."""
        size = self.size_bytes
        used = self.used_bytes
        if size is None or size == 0 or used is None:
            return None
        return (used / size) * 100


# =============================================================================
# Notification Models
# =============================================================================


class Notification(UnraidBaseModel):
    """Unraid notification."""

    id: str
    title: str | None = None
    subject: str | None = None
    description: str | None = None
    importance: str | None = None
    link: str | None = None
    type: str | None = None
    timestamp: ParsedDatetime = None
    formattedTimestamp: str | None = None


class NotificationOverviewCounts(UnraidBaseModel):
    """Notification count by type."""

    info: int = 0
    warning: int = 0
    alert: int = 0
    total: int = 0


class NotificationOverview(UnraidBaseModel):
    """Notification overview with counts."""

    unread: NotificationOverviewCounts = Field(
        default_factory=NotificationOverviewCounts
    )
    archive: NotificationOverviewCounts = Field(
        default_factory=NotificationOverviewCounts
    )


class AccessUrl(UnraidBaseModel):
    """Access URL for reaching the Unraid server."""

    type: str | None = None
    name: str | None = None
    ipv4: str | None = None
    ipv6: str | None = None


class Network(UnraidBaseModel):
    """Network configuration and access URLs."""

    id: str | None = None
    accessUrls: list[AccessUrl] | None = None


# =============================================================================
# Physical Disk Models
# =============================================================================


class DiskPartition(UnraidBaseModel):
    """Physical disk partition."""

    name: str | None = None
    fsType: str | None = None
    size: int | None = None


# =============================================================================
# System Metrics Model (for Home Assistant integration)
# =============================================================================


class SystemMetrics(UnraidBaseModel):
    """System metrics for CPU, memory, and uptime monitoring.

    This model consolidates metrics data for Home Assistant sensor entities.
    Use get_system_metrics() to fetch this data efficiently.
    """

    # CPU metrics
    cpu_percent: float | None = None
    cpu_temperature: float | None = None  # First package temp (most common use)
    cpu_temperatures: list[float] = []  # All package temps (for multi-CPU)
    cpu_power: float | None = None  # Total power consumption in watts

    # Memory metrics
    memory_percent: float | None = None
    memory_total: int | None = None  # Total memory in bytes
    memory_used: int | None = None  # Used memory in bytes
    memory_free: int | None = None  # Free memory in bytes
    memory_available: int | None = None  # Available memory in bytes
    memory_active: int | None = None  # Active memory in bytes
    memory_buffcache: int | None = None  # Buffer/cache memory in bytes

    # Swap metrics
    swap_percent: float | None = None
    swap_total: int | None = None  # Total swap in bytes
    swap_used: int | None = None  # Used swap in bytes
    swap_free: int | None = None  # Free swap in bytes

    # Temperature metrics
    temperature: TemperatureMetrics | None = None

    # Uptime
    uptime: ParsedDatetime = None  # System boot time

    @property
    def average_cpu_temperature(self) -> float | None:
        """Return the average CPU package temperature.

        Returns:
            Mean of all CPU package temperatures, or None if no data.

        """
        if not self.cpu_temperatures:
            return None
        return sum(self.cpu_temperatures) / len(self.cpu_temperatures)

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> SystemMetrics:
        """Create SystemMetrics from GraphQL response.

        Args:
            data: GraphQL response data containing metrics and info.

        Returns:
            SystemMetrics instance with parsed data.

        """
        metrics = data.get("metrics", {}) or {}
        cpu = metrics.get("cpu", {}) or {}
        memory = metrics.get("memory", {}) or {}
        info = data.get("info", {}) or {}
        os_info = info.get("os", {}) or {}

        # CPU temperature and power from info.cpu.packages
        cpu_info = info.get("cpu", {}) or {}
        packages = cpu_info.get("packages", {}) or {}
        temps = packages.get("temp", []) or []

        # Compute memory_used with fallback from total - available
        memory_used = memory.get("used")
        if memory_used is None:
            mem_total = memory.get("total")
            mem_available = memory.get("available")
            if mem_total is not None and mem_available is not None:
                memory_used = max(0, mem_total - mem_available)

        # Parse temperature data if available
        temp_data = metrics.get("temperature")
        temperature = TemperatureMetrics(**temp_data) if temp_data else None

        return cls(
            cpu_percent=cpu.get("percentTotal"),
            cpu_temperature=temps[0] if temps else None,
            cpu_temperatures=temps,
            cpu_power=packages.get("totalPower"),
            memory_percent=memory.get("percentTotal"),
            memory_total=memory.get("total"),
            memory_used=memory_used,
            memory_free=memory.get("free"),
            memory_available=memory.get("available"),
            memory_active=memory.get("active"),
            memory_buffcache=memory.get("buffcache"),
            swap_percent=memory.get("percentSwapTotal"),
            swap_total=memory.get("swapTotal"),
            swap_used=memory.get("swapUsed"),
            swap_free=memory.get("swapFree"),
            temperature=temperature,
            uptime=os_info.get("uptime"),
        )


# =============================================================================
# Server Info Model (for Home Assistant integration)
# =============================================================================


class ServerInfo(UnraidBaseModel):
    """Server information for device registration and identification.

    This model consolidates system, hardware, OS, and network information
    needed for Home Assistant device registration.
    """

    # Unique identification
    uuid: str | None = None
    hostname: str | None = None

    # Device info (for HA DeviceInfo)
    manufacturer: str = "Lime Technology"  # Always Lime Technology for Unraid
    model: str | None = None  # "Unraid {version}"
    sw_version: str | None = None  # Unraid version
    hw_version: str | None = None  # Kernel version
    serial_number: str | None = None

    # Hardware info (from system or baseboard fallback)
    hw_manufacturer: str | None = None
    hw_model: str | None = None

    # OS details
    os_distro: str | None = None
    os_release: str | None = None
    os_arch: str | None = None

    # API info
    api_version: str | None = None

    # Network/URLs
    lan_ip: str | None = None
    local_url: str | None = None
    remote_url: str | None = None

    # License
    license_type: str | None = None
    license_state: str | None = None

    # CPU info
    cpu_brand: str | None = None
    cpu_cores: int | None = None
    cpu_threads: int | None = None

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> ServerInfo:
        """Create ServerInfo from GraphQL response.

        Args:
            data: GraphQL response data containing info, server, and registration.

        Returns:
            ServerInfo instance with parsed data.

        """
        info = data.get("info", {})
        system = info.get("system", {}) or {}
        baseboard = info.get("baseboard", {}) or {}
        os_info = info.get("os", {}) or {}
        cpu = info.get("cpu", {}) or {}
        versions = info.get("versions", {}) or {}
        core_versions = versions.get("core", {}) or {}
        server = data.get("server", {}) or {}
        registration = data.get("registration", {}) or {}

        unraid_version = core_versions.get("unraid") or "Unknown"

        return cls(
            uuid=system.get("uuid"),
            hostname=os_info.get("hostname"),
            manufacturer="Lime Technology",
            model=f"Unraid {unraid_version}",
            sw_version=unraid_version,
            hw_version=os_info.get("kernel"),
            serial_number=system.get("serial") or baseboard.get("serial"),
            hw_manufacturer=system.get("manufacturer") or baseboard.get("manufacturer"),
            hw_model=system.get("model") or baseboard.get("model"),
            os_distro=os_info.get("distro"),
            os_release=os_info.get("release"),
            os_arch=os_info.get("arch"),
            api_version=core_versions.get("api"),
            lan_ip=server.get("lanip"),
            local_url=server.get("localurl"),
            remote_url=server.get("remoteurl"),
            license_type=registration.get("type"),
            license_state=registration.get("state"),
            cpu_brand=cpu.get("brand"),
            cpu_cores=cpu.get("cores"),
            cpu_threads=cpu.get("threads"),
        )


# =============================================================================
# Registration Models
# =============================================================================


class KeyFile(UnraidBaseModel):
    """Unraid license key file information."""

    location: str | None = None
    contents: str | None = None


class Registration(UnraidBaseModel):
    """Unraid license registration information."""

    id: str | None = None
    type: str | None = None  # License type (Basic, Plus, Pro, etc.)
    state: str | None = None  # License state
    expiration: str | None = None
    updateExpiration: str | None = None
    keyFile: KeyFile | None = None  # License key file (v4.30.0+)


# =============================================================================
# System Variables (Vars) Models
# =============================================================================


class Vars(UnraidBaseModel):
    """Unraid system variables (vars object).

    This represents the system configuration variables from /var/local/emhttp/var.ini.
    Contains many system settings including hostname, timezone, array state, etc.
    """

    id: str | None = None

    # Basic system info
    version: str | None = None
    name: str | None = None  # Machine hostname
    time_zone: str | None = Field(default=None, alias="timeZone")
    comment: str | None = None
    security: str | None = None
    workgroup: str | None = None
    domain: str | None = None
    domain_short: str | None = Field(default=None, alias="domainShort")

    # Array configuration
    max_arraysz: int | None = Field(default=None, alias="maxArraysz")
    max_cachesz: int | None = Field(default=None, alias="maxCachesz")
    sys_model: str | None = Field(default=None, alias="sysModel")
    sys_array_slots: int | None = Field(default=None, alias="sysArraySlots")
    sys_cache_slots: int | None = Field(default=None, alias="sysCacheSlots")
    sys_flash_slots: int | None = Field(default=None, alias="sysFlashSlots")
    device_count: int | None = Field(default=None, alias="deviceCount")

    # Network/services
    use_ssl: bool | None = Field(default=None, alias="useSsl")
    port: int | None = None  # HTTP port
    portssl: int | None = None  # HTTPS port
    local_tld: str | None = Field(default=None, alias="localTld")
    bind_mgt: bool | None = Field(default=None, alias="bindMgt")
    use_telnet: bool | None = Field(default=None, alias="useTelnet")
    port_telnet: int | None = Field(default=None, alias="porttelnet")
    use_ssh: bool | None = Field(default=None, alias="useSsh")
    port_ssh: int | None = Field(default=None, alias="portssh")

    # NTP settings
    use_ntp: bool | None = Field(default=None, alias="useNtp")
    ntp_server1: str | None = Field(default=None, alias="ntpServer1")
    ntp_server2: str | None = Field(default=None, alias="ntpServer2")
    ntp_server3: str | None = Field(default=None, alias="ntpServer3")
    ntp_server4: str | None = Field(default=None, alias="ntpServer4")

    # File sharing settings
    hide_dot_files: bool | None = Field(default=None, alias="hideDotFiles")
    local_master: bool | None = Field(default=None, alias="localMaster")
    enable_fruit: str | None = Field(default=None, alias="enableFruit")
    share_smb_enabled: bool | None = Field(default=None, alias="shareSmbEnabled")
    share_nfs_enabled: bool | None = Field(default=None, alias="shareNfsEnabled")
    share_afp_enabled: bool | None = Field(default=None, alias="shareAfpEnabled")

    # Array state
    start_array: bool | None = Field(default=None, alias="startArray")
    spindown_delay: str | None = Field(default=None, alias="spindownDelay")
    safe_mode: bool | None = Field(default=None, alias="safeMode")
    start_mode: str | None = Field(default=None, alias="startMode")
    config_valid: bool | None = Field(default=None, alias="configValid")
    config_error: str | None = Field(default=None, alias="configError")

    # Flash info (in vars)
    flash_guid: str | None = Field(default=None, alias="flashGuid")
    flash_product: str | None = Field(default=None, alias="flashProduct")
    flash_vendor: str | None = Field(default=None, alias="flashVendor")

    # Registration info (in vars)
    reg_check: str | None = Field(default=None, alias="regCheck")
    reg_file: str | None = Field(default=None, alias="regFile")
    reg_guid: str | None = Field(default=None, alias="regGuid")
    reg_ty: str | None = Field(default=None, alias="regTy")
    reg_state: str | None = Field(default=None, alias="regState")
    reg_to: str | None = Field(default=None, alias="regTo")  # Registration owner

    # Array/disk state
    md_color: str | None = Field(default=None, alias="mdColor")
    md_num_disks: int | None = Field(default=None, alias="mdNumDisks")
    md_num_disabled: int | None = Field(default=None, alias="mdNumDisabled")
    md_num_invalid: int | None = Field(default=None, alias="mdNumInvalid")
    md_num_missing: int | None = Field(default=None, alias="mdNumMissing")
    md_resync: int | None = Field(default=None, alias="mdResync")
    md_resync_action: str | None = Field(default=None, alias="mdResyncAction")
    md_resync_pos: str | None = Field(default=None, alias="mdResyncPos")
    md_state: str | None = Field(default=None, alias="mdState")
    md_version: str | None = Field(default=None, alias="mdVersion")
    sb_version: str | None = Field(default=None, alias="sbVersion")

    # Join/poll status
    join_status: str | None = Field(default=None, alias="joinStatus")
    poll_attributes_status: str | None = Field(
        default=None, alias="pollAttributesStatus"
    )

    # Cache state
    cache_num_devices: int | None = Field(default=None, alias="cacheNumDevices")

    # Filesystem state
    fs_state: str | None = Field(default=None, alias="fsState")
    fs_progress: str | None = Field(default=None, alias="fsProgress")
    fs_copy_prcnt: int | None = Field(default=None, alias="fsCopyPrcnt")
    fs_num_mounted: int | None = Field(default=None, alias="fsNumMounted")
    fs_num_unmountable: int | None = Field(default=None, alias="fsNumUnmountable")

    # Share counts
    share_count: int | None = Field(default=None, alias="shareCount")
    share_smb_count: int | None = Field(default=None, alias="shareSmbCount")
    share_nfs_count: int | None = Field(default=None, alias="shareNfsCount")
    share_afp_count: int | None = Field(default=None, alias="shareAfpCount")
    share_mover_active: bool | None = Field(default=None, alias="shareMoverActive")
    share_mover_logging: bool | None = Field(default=None, alias="shareMoverLogging")
    share_mover_schedule: str | None = Field(default=None, alias="shareMoverSchedule")

    # Boot & system setup (Unraid 7.2+)
    boot_eligible: bool | None = Field(default=None, alias="bootEligible")
    booted_from_flash_with_internal_boot_setup: bool | None = Field(
        default=None, alias="bootedFromFlashWithInternalBootSetup"
    )
    tpm_guid: str | None = Field(default=None, alias="tpmGuid")
    sb_synced: int | None = Field(default=None, alias="sbSynced")
    sb_sync_errs: int | None = Field(default=None, alias="sbSyncErrs")
    sb_sync_exit: str | None = Field(default=None, alias="sbSyncExit")
    fs_unmountable_mask: str | None = Field(default=None, alias="fsUnmountableMask")
    default_fs_type: str | None = Field(default=None, alias="defaultFsType")
    default_format: str | None = Field(default=None, alias="defaultFormat")

    # Security
    csrf_token: str | None = Field(default=None, alias="csrfToken")


# =============================================================================
# Service Models
# =============================================================================


class ServiceUptime(UnraidBaseModel):
    """Service uptime information."""

    timestamp: str | None = None


class Service(UnraidBaseModel):
    """System service information."""

    id: str
    name: str
    online: bool | None = None
    uptime: ServiceUptime | None = None
    version: str | None = None


# =============================================================================
# Flash Drive Models
# =============================================================================


class Flash(UnraidBaseModel):
    """Flash drive information."""

    id: str
    guid: str | None = None
    product: str | None = None
    vendor: str | None = None


# =============================================================================
# Owner & Server Models
# =============================================================================


class ProfileModel(UnraidBaseModel):
    """Server owner profile information."""

    id: str | None = None
    username: str | None = None
    avatar: str | None = None
    url: str | None = None


class Owner(UnraidBaseModel):
    """Owner/user information."""

    username: str
    avatar: str | None = None
    url: str | None = None


class Server(UnraidBaseModel):
    """Unraid server identity and connectivity information."""

    id: str = ""
    name: str | None = None
    guid: str | None = None
    lanip: str | None = None
    wanip: str | None = None
    localurl: str | None = None
    remoteurl: str | None = None
    status: str | None = None
    comment: str | None = None
    apikey: str | None = None
    owner: ProfileModel | None = None


# =============================================================================
# Plugin Models
# =============================================================================


class Plugin(UnraidBaseModel):
    """Plugin information from the Unraid API.

    Attributes:
        name: The name of the plugin package.
        version: The version of the plugin package.
        hasApiModule: Whether the plugin has an API module.
        hasCliModule: Whether the plugin has a CLI module.

    """

    name: str
    version: str
    hasApiModule: bool | None = None
    hasCliModule: bool | None = None


class PluginInstallOperation(UnraidBaseModel):
    """Background plugin installation operation."""

    id: str
    name: str | None = None
    url: str | None = None
    status: str | None = None
    output: list[str] = Field(default_factory=list)
    createdAt: ParsedDatetime = None
    updatedAt: ParsedDatetime = None
    finishedAt: ParsedDatetime = None


class PluginInstallEvent(UnraidBaseModel):
    """Real-time plugin install update event from subscription."""

    operationId: str
    status: str | None = None
    output: list[str] = Field(default_factory=list)
    timestamp: ParsedDatetime = None


# =============================================================================
# Log File Models
# =============================================================================


class LogFile(UnraidBaseModel):
    """Log file information.

    Attributes:
        name: Name of the log file.
        path: Full path to the log file.
        size: Size of the log file in bytes.
        modifiedAt: Last modified timestamp.

    """

    name: str
    path: str
    size: int | None = None
    modifiedAt: str | None = None


class LogFileContent(UnraidBaseModel):
    """Log file content.

    Attributes:
        path: Path to the log file.
        content: Content of the log file.
        totalLines: Total number of lines in the file.
        startLine: Starting line number of the content (1-indexed).

    """

    path: str
    content: str | None = None
    totalLines: int | None = None
    startLine: int | None = None


# =============================================================================
# Cloud/Connect Models
# =============================================================================


class ApiKeyResponse(UnraidBaseModel):
    """API key response information.

    Attributes:
        valid: Whether the API key is valid.
        error: Any error message.

    """

    valid: bool | None = None
    error: str | None = None


class CloudResponse(UnraidBaseModel):
    """Cloud response information."""

    status: str
    ip: str | None = None
    error: str | None = None


class RelayResponse(UnraidBaseModel):
    """Relay response information."""

    status: str
    timeout: str | None = None
    error: str | None = None


class MinigraphqlResponse(UnraidBaseModel):
    """Minigraphql response information.

    Attributes:
        status: Status of minigraphql (PRE_INIT, CONNECTING, CONNECTED, etc).
        timeout: Timeout value.
        error: Any error message.

    """

    status: str | None = None
    timeout: int | None = None
    error: str | None = None


class Cloud(UnraidBaseModel):
    """Cloud settings information.

    .. deprecated::
        The ``cloud`` query was removed from the Unraid GraphQL API.
        This model is kept for backward compatibility and will be
        removed in a future release.

    Attributes:
        error: Any error message.
        apiKey: API key response details.
        relay: Relay connection status.
        minigraphql: Minigraphql connection status.
        cloud: Cloud connection status.
        allowedOrigins: List of allowed origins.

    """

    error: str | None = None
    apiKey: ApiKeyResponse | None = None
    relay: RelayResponse | None = None
    minigraphql: MinigraphqlResponse | None = None
    cloud: CloudResponse | None = None
    allowedOrigins: list[str] = []


class DynamicRemoteAccessStatus(UnraidBaseModel):
    """Dynamic remote access status.

    Attributes:
        enabledType: The type of dynamic remote access enabled.
        runningType: The type of dynamic remote access currently running.
        error: Any error message.

    """

    enabledType: str | None = None
    runningType: str | None = None
    error: str | None = None


class Connect(UnraidBaseModel):
    """Unraid Connect information.

    .. deprecated::
        The ``connect`` query was removed from the Unraid GraphQL API.
        This model is kept for backward compatibility and will be
        removed in a future release.

    Attributes:
        id: Connect node ID.
        dynamicRemoteAccess: Dynamic remote access status.

    """

    id: str | None = None
    dynamicRemoteAccess: DynamicRemoteAccessStatus | None = None


class RemoteAccess(UnraidBaseModel):
    """Remote access configuration.

    .. deprecated::
        The ``remoteAccess`` query was removed from the Unraid GraphQL
        API. This model is kept for backward compatibility and will be
        removed in a future release.

    Attributes:
        accessType: The type of WAN access (DYNAMIC, ALWAYS, DISABLED).
        forwardType: The type of port forwarding (UPNP, STATIC).
        port: The port used for remote access.

    """

    accessType: str | None = None
    forwardType: str | None = None
    port: int | None = None


# =============================================================================
# User & API Key Models
# =============================================================================


class Permission(UnraidBaseModel):
    """API key or user permission.

    Attributes:
        resource: The resource this permission applies to.
        actions: List of allowed actions on the resource.

    """

    resource: str
    actions: list[str] = []


class UserAccount(UnraidBaseModel):
    """Unraid user account information.

    Attributes:
        id: Unique user account ID.
        name: The name of the user account.
        description: Description of the user account.
        roles: List of roles assigned to the user.
        permissions: Optional list of permissions.

    """

    id: str
    name: str
    description: str | None = None
    roles: list[str] = []
    permissions: list[Permission] | None = None


class ApiKey(UnraidBaseModel):
    """API key information.

    Attributes:
        id: Unique API key ID (PrefixedID format).
        key: The API key value (only returned on create).
        name: Display name for the API key.
        description: Optional description.
        roles: List of roles assigned to this key.
        createdAt: ISO timestamp of when the key was created.
        permissions: List of permissions for this key.

    """

    id: str
    key: str | None = None
    name: str
    description: str | None = None
    roles: list[str] = []
    createdAt: str | None = None
    permissions: list[Permission] | None = None


# =============================================================================
# Docker Container Log Models
# =============================================================================


# =============================================================================
# Version Info Model
# =============================================================================


class VersionInfo(UnraidBaseModel):
    """Server version information.

    Attributes:
        api: The API version string.
        unraid: The Unraid OS version string.

    """

    api: str = "unknown"
    unraid: str = "unknown"


# =============================================================================
# Parity History Model
# =============================================================================


def _parse_parity_date(value: str | int | float | datetime | None) -> datetime | None:
    """Parse a parity history date from various formats.

    Handles ISO strings, epoch timestamps (int/float), datetime objects, and None.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, int | float):
        from datetime import UTC

        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        # Try ISO format first
        try:
            normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
            return datetime.fromisoformat(normalized)
        except ValueError:
            pass
        # Try epoch string
        try:
            from datetime import UTC

            return datetime.fromtimestamp(float(value), tz=UTC)
        except (ValueError, OSError):
            pass
    return None


ParityDate = Annotated[datetime | None, BeforeValidator(_parse_parity_date)]


class ParityHistoryEntry(UnraidBaseModel):
    """A single parity check history entry.

    Attributes:
        date: When the parity check occurred.
        duration: Duration in seconds.
        speed: Speed of the parity check.
        status: Result status of the check.
        errors: Number of errors found.

    """

    date: ParityDate = None
    duration: int | None = None
    speed: str | int | None = None
    status: str | None = None
    errors: int | None = None

    @property
    def duration_formatted(self) -> str | None:
        """Return duration as a human-readable string.

        Returns:
            Formatted string like "2 hours 15 minutes 30 seconds",
            or None if duration is unavailable.

        """
        if self.duration is None:
            return None
        return _format_duration(self.duration)


# =============================================================================
# Docker Container Log Models
# =============================================================================


class DockerContainerLogLine(UnraidBaseModel):
    """A single line from a Docker container log.

    Attributes:
        timestamp: Timestamp of the log entry.
        message: Log message content.

    """

    timestamp: str
    message: str


class DockerContainerLogs(UnraidBaseModel):
    """Docker container log retrieval result.

    Attributes:
        containerId: The container ID the logs belong to.
        lines: List of log lines.
        cursor: Cursor for pagination (DateTime).

    """

    containerId: str | None = None
    lines: list[DockerContainerLogLine] = []
    cursor: str | None = None


# =============================================================================
# Container Update Status Models (v4.30.0+)
# =============================================================================


class ContainerUpdateStatus(UnraidBaseModel):
    """Docker container update status.

    Attributes:
        name: Container name.
        updateStatus: Update status (e.g., "UP_TO_DATE", "UPDATE_AVAILABLE").

    """

    name: str
    updateStatus: str | None = None


# =============================================================================
# UPS Configuration Models (v4.30.0+)
# =============================================================================


class UPSConfiguration(UnraidBaseModel):
    """UPS configuration settings.

    Attributes:
        service: UPS service configuration.
        upsCable: Cable type (e.g., "usb").
        customUpsCable: Custom cable type if applicable.
        upsType: UPS type.
        device: UPS device path.
        overrideUpsCapacity: Whether to override UPS capacity.
        batteryLevel: Battery level threshold for shutdown.
        minutes: Minutes threshold for shutdown.
        timeout: Timeout value.
        killUps: Whether to kill UPS on shutdown.
        nisIp: Network Information Server IP.
        netServer: Network server setting.
        upsName: UPS display name.
        modelName: UPS model name.

    """

    service: str | None = None
    upsCable: str | None = None
    customUpsCable: str | None = None
    upsType: str | None = None
    device: str | None = None
    overrideUpsCapacity: bool | None = None
    batteryLevel: int | None = None
    minutes: int | None = None
    timeout: int | None = None
    killUps: bool | None = None
    nisIp: str | None = None
    netServer: str | None = None
    upsName: str | None = None
    modelName: str | None = None


# =============================================================================
# Display Settings Models (v4.30.0+)
# =============================================================================


class DisplaySettings(UnraidBaseModel):
    """Display and temperature settings.

    Attributes:
        theme: UI theme (e.g., "white", "black").
        unit: Temperature unit (e.g., "CELSIUS", "FAHRENHEIT").
        scale: Scale setting.
        tabs: Tab configuration.
        resize: Resize setting.
        wwn: WWN display setting.
        total: Total display setting.
        usage: Usage display setting.
        text: Text display setting.
        warning: Warning temperature threshold.
        critical: Critical temperature threshold.
        hot: Hot temperature threshold.
        max: Maximum temperature threshold.
        locale: Locale setting (e.g., "en_US").

    """

    theme: str | None = None
    unit: str | None = None
    scale: str | bool | None = None
    tabs: str | bool | None = None
    resize: str | bool | None = None
    wwn: str | bool | None = None
    total: str | bool | None = None
    usage: str | bool | None = None
    text: str | bool | None = None
    warning: int | None = None
    critical: int | None = None
    hot: int | None = None
    max: int | None = None
    locale: str | None = None


# =============================================================================
# Docker Port Conflicts Models (v4.30.0+)
# =============================================================================


class DockerPortConflictContainer(UnraidBaseModel):
    """Container involved in a port conflict."""

    name: str


class DockerLanPortConflict(UnraidBaseModel):
    """A LAN port conflict entry."""

    containers: list[DockerPortConflictContainer] = []


class DockerPortConflicts(UnraidBaseModel):
    """Docker port conflicts information."""

    lanPorts: list[DockerLanPortConflict] = []


# =============================================================================
# Subscription Models (real-time WebSocket data)
# =============================================================================


class CpuCore(UnraidBaseModel):
    """Individual CPU core utilization."""

    percentTotal: float | None = None
    percentUser: float | None = None
    percentSystem: float | None = None
    percentIdle: float | None = None
    percentNice: float | None = None
    percentIrq: float | None = None
    percentGuest: float | None = None
    percentSteal: float | None = None


class CpuMetrics(UnraidBaseModel):
    """CPU utilization metrics from systemMetricsCpu subscription."""

    percentTotal: float | None = None
    cpus: list[CpuCore] = []


class CpuTelemetryMetrics(UnraidBaseModel):
    """CPU telemetry (power/temp) from systemMetricsCpuTelemetry subscription."""

    totalPower: float | None = None
    power: list[float] | float | None = None
    temp: list[float] | float | None = None


class MemoryMetrics(UnraidBaseModel):
    """Memory utilization from systemMetricsMemory subscription."""

    total: int | None = None
    used: int | None = None
    free: int | None = None
    percentTotal: float | None = None


class ArraySubscriptionUpdate(UnraidBaseModel):
    """Array state update from arraySubscription subscription."""

    state: str | None = None
    capacity: ArrayCapacity | None = None


# =============================================================================
# System Time Models (Unraid 7.3 / API 4.3x)
# =============================================================================


class SystemTime(UnraidBaseModel):
    """Server system-time configuration.

    Attributes:
        currentTime: Current server time (ISO-8601 string).
        ntpServers: Configured NTP servers (list of hostnames).
        timeZone: IANA time-zone name (e.g., "Australia/Brisbane").
        useNtp: Whether NTP time synchronization is enabled.

    """

    currentTime: str | None = None
    ntpServers: list[str] | None = None
    timeZone: str | None = None
    useNtp: bool | None = None


class TimeZoneOption(UnraidBaseModel):
    """A selectable time-zone option.

    Attributes:
        label: Human-readable label.
        value: IANA time-zone identifier.

    """

    label: str | None = None
    value: str | None = None


# =============================================================================
# Network Metrics Models (API 4.35.0)
# =============================================================================


class NetworkMetrics(UnraidBaseModel):
    """Per-interface network metrics (metrics.network, API 4.35.0+).

    Attributes:
        id: Prefixed metric identifier.
        name: Interface name (e.g., "br0", "eth0", "lo").
        rxSec: Receive rate in bytes per second.
        txSec: Transmit rate in bytes per second.
        operstate: Interface operational state (e.g., "up", "down", "unknown").
        speed: Interface link speed in Mbps.
        utilizationPercent: Interface bandwidth utilization percentage.
        lastUpdated: ISO timestamp of last metric update.
        bytesReceived: Total bytes received since boot.
        bytesSent: Total bytes sent since boot.
        packetsReceived: Total packets received since boot.
        packetsSent: Total packets sent since boot.
        receiveErrors: Total receive errors since boot.
        transmitErrors: Total transmit errors since boot.
        receiveDropped: Total received packets dropped since boot.
        transmitDropped: Total transmitted packets dropped since boot.

    """

    id: str | None = None
    name: str | None = None
    rxSec: float | None = None
    txSec: float | None = None
    operstate: str | None = None
    speed: int | None = None
    utilizationPercent: float | None = None
    lastUpdated: str | None = None
    bytesReceived: int | None = None
    bytesSent: int | None = None
    packetsReceived: int | None = None
    packetsSent: int | None = None
    receiveErrors: int | None = None
    transmitErrors: int | None = None
    receiveDropped: int | None = None
    transmitDropped: int | None = None


# =============================================================================
# Settings Models (Unraid 7.3 / API 4.3x)
# =============================================================================


class ApiConfig(UnraidBaseModel):
    """API configuration block from ``settings.api``.

    Attributes:
        version: Installed Unraid API version.
        sandbox: Whether the GraphQL sandbox is enabled.
        plugins: Installed API plugin identifiers.
        extraOrigins: Additional allowed CORS origins.
        ssoSubIds: Configured SSO subject identifiers.

    """

    version: str | None = None
    sandbox: bool | None = None
    plugins: list[str] | None = None
    extraOrigins: list[str] | None = None
    ssoSubIds: list[str] | None = None


class UnifiedSettings(UnraidBaseModel):
    """Unified settings form payload from ``settings.unified``.

    The fields are JSON blobs (RJSF schema / values), exposed as-is for
    diagnostics.

    Attributes:
        values: Current setting values.
        dataSchema: JSON schema describing the settings.
        uiSchema: UI schema for rendering the settings form.

    """

    values: dict[str, Any] | None = None
    dataSchema: dict[str, Any] | None = None
    uiSchema: dict[str, Any] | None = None


class Settings(UnraidBaseModel):
    """Server settings (read-only diagnostic view).

    Attributes:
        id: Settings identifier.
        api: API configuration block.
        unified: Unified settings form payload.

    """

    id: str | None = None
    api: ApiConfig | None = None
    unified: UnifiedSettings | None = None
