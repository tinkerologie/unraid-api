"""Tests for Pydantic models."""

from __future__ import annotations

from datetime import UTC, datetime

from unraid_api.models import (
    ArrayCapacity,
    ArrayDisk,
    CapacityKilobytes,
    DockerContainer,
    InfoOs,
    Notification,
    ParityHistoryEntry,
    PhysicalDisk,
    Share,
    UnraidArray,
    VersionInfo,
    _format_duration,
    _parse_datetime,
    format_bytes,
)


class TestDatetimeParsing:
    """Tests for datetime parsing in models."""

    def test_parse_iso_datetime_with_z(self) -> None:
        """Test parsing ISO datetime with Z suffix."""
        os_info = InfoOs(uptime="2024-01-15T10:30:00Z")

        assert os_info.uptime is not None
        assert os_info.uptime.year == 2024
        assert os_info.uptime.month == 1
        assert os_info.uptime.day == 15

    def test_parse_iso_datetime_with_offset(self) -> None:
        """Test parsing ISO datetime with timezone offset."""
        os_info = InfoOs(uptime="2024-01-15T10:30:00+00:00")

        assert os_info.uptime is not None
        assert os_info.uptime.year == 2024

    def test_parse_none_datetime(self) -> None:
        """Test parsing None datetime."""
        os_info = InfoOs(uptime=None)

        assert os_info.uptime is None

    def test_parse_datetime_object(self) -> None:
        """Test passing datetime object directly."""
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        os_info = InfoOs(uptime=dt)

        assert os_info.uptime == dt

    def test_parse_unsupported_type_returns_none(self) -> None:
        """Test that unsupported types return None."""
        result = _parse_datetime(12345)

        assert result is None


class TestArrayCapacity:
    """Tests for ArrayCapacity model."""

    def test_capacity_properties(self) -> None:
        """Test capacity byte conversion properties."""
        capacity = ArrayCapacity(
            kilobytes=CapacityKilobytes(total=1000, used=400, free=600)
        )

        assert capacity.total_bytes == 1024000
        assert capacity.used_bytes == 409600
        assert capacity.free_bytes == 614400

    def test_usage_percent(self) -> None:
        """Test usage percentage calculation."""
        capacity = ArrayCapacity(
            kilobytes=CapacityKilobytes(total=1000, used=400, free=600)
        )

        assert capacity.usage_percent == 40.0

    def test_usage_percent_zero_total(self) -> None:
        """Test usage percentage with zero total."""
        capacity = ArrayCapacity(kilobytes=CapacityKilobytes(total=0, used=0, free=0))

        assert capacity.usage_percent == 0.0


class TestArrayDisk:
    """Tests for ArrayDisk model."""

    def test_disk_with_required_fields(self) -> None:
        """Test disk creation with required fields only."""
        disk = ArrayDisk(id="disk:1")

        assert disk.id == "disk:1"
        assert disk.name is None
        assert disk.temp is None

    def test_disk_with_all_fields(self) -> None:
        """Test disk creation with all fields."""
        disk = ArrayDisk(
            id="disk:1",
            idx=1,
            device="sda",
            name="Disk 1",
            type="DATA",
            size=4000000000,
            fsSize=3900000000,
            fsUsed=1000000000,
            fsFree=2900000000,
            fsType="XFS",
            temp=35,
            status="DISK_OK",
            isSpinning=True,
            smartStatus="PASSED",
        )

        assert disk.id == "disk:1"
        assert disk.idx == 1
        assert disk.name == "Disk 1"
        assert disk.temp == 35
        assert disk.isSpinning is True

    def test_disk_is_standby_spinning(self) -> None:
        """Test is_standby property when disk is spinning."""
        disk = ArrayDisk(id="disk:1", isSpinning=True)
        assert disk.is_standby is False

    def test_disk_is_standby_sleeping(self) -> None:
        """Test is_standby property when disk is in standby."""
        disk = ArrayDisk(id="disk:1", isSpinning=False)
        assert disk.is_standby is True

    def test_disk_is_standby_none(self) -> None:
        """Test is_standby property when isSpinning is None."""
        disk = ArrayDisk(id="disk:1", isSpinning=None)
        # When isSpinning is None, is_standby should be False (not certain)
        assert disk.is_standby is False

    def test_disk_byte_properties(self) -> None:
        """Test disk byte conversion properties."""
        disk = ArrayDisk(
            id="disk:1",
            size=1000,
            fsSize=900,
            fsUsed=300,
            fsFree=600,
        )

        assert disk.size_bytes == 1024000
        assert disk.fs_size_bytes == 921600
        assert disk.fs_used_bytes == 307200
        assert disk.fs_free_bytes == 614400

    def test_disk_usage_percent(self) -> None:
        """Test disk usage percentage."""
        disk = ArrayDisk(
            id="disk:1",
            fsSize=1000,
            fsUsed=250,
        )

        assert disk.usage_percent == 25.0

    def test_disk_usage_percent_none_values(self) -> None:
        """Test disk usage percentage with None values."""
        disk = ArrayDisk(id="disk:1")

        assert disk.usage_percent is None


class TestDockerContainer:
    """Tests for DockerContainer model."""

    def test_container_required_fields(self) -> None:
        """Test container with required fields."""
        container = DockerContainer(id="container:abc123", name="plex")

        assert container.id == "container:abc123"
        assert container.name == "plex"
        assert container.state is None
        assert container.ports == []

    def test_container_with_all_fields(self) -> None:
        """Test container with all fields."""
        container = DockerContainer(
            id="container:abc123",
            name="plex",
            state="RUNNING",
            image="plexinc/pms-docker:latest",
            webUiUrl="http://192.168.1.100:32400/web",
            iconUrl="/icons/plex.png",
        )

        assert container.state == "RUNNING"
        assert container.image == "plexinc/pms-docker:latest"


class TestShare:
    """Tests for Share model."""

    def test_share_size_from_size_field(self) -> None:
        """Test share size calculation from size field."""
        share = Share(id="share:1", name="appdata", size=1000, used=400, free=600)

        assert share.size_bytes == 1024000

    def test_share_size_from_used_free(self) -> None:
        """Test share size calculation from used+free when size is 0."""
        share = Share(id="share:1", name="appdata", size=0, used=400, free=600)

        assert share.size_bytes == 1024000

    def test_share_usage_percent(self) -> None:
        """Test share usage percentage."""
        share = Share(id="share:1", name="appdata", size=1000, used=250, free=750)

        assert share.usage_percent == 25.0

    def test_share_used_bytes(self) -> None:
        """Test share used_bytes property."""
        share = Share(id="share:1", name="appdata", used=500)
        assert share.used_bytes == 512000

    def test_share_free_bytes(self) -> None:
        """Test share free_bytes property."""
        share = Share(id="share:1", name="appdata", free=500)
        assert share.free_bytes == 512000

    def test_share_size_bytes_all_none(self) -> None:
        """Test share size_bytes when all values are None."""
        share = Share(id="share:1", name="appdata")
        assert share.size_bytes is None

    def test_share_usage_percent_zero_size(self) -> None:
        """Test share usage_percent when size is zero."""
        share = Share(id="share:1", name="appdata", size=0, used=0, free=0)
        # When size=0 and used=0 and free=0, size_bytes = 0
        assert share.usage_percent is None

    def test_share_usage_percent_none_used(self) -> None:
        """Test share usage_percent when used is None."""
        share = Share(id="share:1", name="appdata", size=1000)
        assert share.usage_percent is None

    def test_share_used_bytes_none(self) -> None:
        """Test share used_bytes when used is None."""
        share = Share(id="share:1", name="appdata")
        assert share.used_bytes is None

    def test_share_free_bytes_none(self) -> None:
        """Test share free_bytes when free is None."""
        share = Share(id="share:1", name="appdata")
        assert share.free_bytes is None


class TestUnraidArray:
    """Tests for UnraidArray model."""

    def test_array_defaults(self) -> None:
        """Test array with default values."""
        array = UnraidArray(capacity=ArrayCapacity())

        assert array.state is None
        assert array.disks == []
        assert array.parities == []
        assert array.caches == []
        assert array.boot is None

    def test_array_with_disks(self) -> None:
        """Test array with disk list."""
        array = UnraidArray(
            state="STARTED",
            capacity=ArrayCapacity(),
            disks=[
                ArrayDisk(id="disk:1", name="Disk 1"),
                ArrayDisk(id="disk:2", name="Disk 2"),
            ],
        )

        assert array.state == "STARTED"
        assert len(array.disks) == 2
        assert array.disks[0].name == "Disk 1"


class TestNotification:
    """Tests for Notification model."""

    def test_notification_timestamp_parsing(self) -> None:
        """Test notification timestamp parsing."""
        notification = Notification(
            id="notif:1",
            title="Test",
            timestamp="2024-01-15T10:30:00Z",
        )

        assert notification.timestamp is not None
        assert notification.timestamp.year == 2024

    def test_notification_with_all_fields(self) -> None:
        """Test notification with all fields."""
        notification = Notification(
            id="notif:1",
            title="Parity Check Complete",
            subject="Parity check completed successfully",
            description="No errors found",
            importance="INFO",
            type="UNREAD",
        )

        assert notification.title == "Parity Check Complete"
        assert notification.importance == "INFO"


class TestPhysicalDisk:
    """Tests for PhysicalDisk model."""

    def test_physical_disk_required_fields(self) -> None:
        """Test physical disk with required fields only."""
        disk = PhysicalDisk(id="disk:sda")
        assert disk.id == "disk:sda"
        assert disk.device is None
        assert disk.smartStatus is None

    def test_physical_disk_with_all_fields(self) -> None:
        """Test physical disk with all fields."""
        disk = PhysicalDisk(
            id="disk:sda",
            device="/dev/sda",
            name="WDC WD140EDFZ-11A0VA0",
            vendor="Western Digital",
            size=14000519643136,  # 14TB in bytes
            type="HDD",
            interfaceType="SATA",
            smartStatus="OK",
            temperature=35.0,
            isSpinning=True,
        )

        assert disk.id == "disk:sda"
        assert disk.vendor == "Western Digital"
        assert disk.interfaceType == "SATA"
        assert disk.smartStatus == "OK"
        assert disk.temperature == 35.0
        assert disk.isSpinning is True


class TestForwardCompatibility:
    """Tests for forward compatibility (ignoring unknown fields)."""

    def test_ignores_unknown_fields(self) -> None:
        """Test that unknown fields are ignored."""
        disk = ArrayDisk(
            id="disk:1",
            name="Disk 1",
            unknown_field="should be ignored",  # type: ignore[call-arg]
            another_unknown=123,  # type: ignore[call-arg]
        )

        assert disk.id == "disk:1"
        assert disk.name == "Disk 1"
        assert not hasattr(disk, "unknown_field")


class TestServerInfo:
    """Tests for ServerInfo model."""

    def test_server_info_default_values(self) -> None:
        """Test ServerInfo with default values."""
        from unraid_api.models import ServerInfo

        info = ServerInfo()

        assert info.uuid is None
        assert info.hostname is None
        assert info.manufacturer == "Lime Technology"
        assert info.model is None
        assert info.sw_version is None
        assert info.hw_version is None
        assert info.serial_number is None
        assert info.api_version is None
        assert info.lan_ip is None

    def test_server_info_with_all_fields(self) -> None:
        """Test ServerInfo with all fields populated."""
        from unraid_api.models import ServerInfo

        info = ServerInfo(
            uuid="abc123-def456",
            hostname="Tower",
            manufacturer="Lime Technology",
            model="Unraid 7.2.0",
            sw_version="7.2.0",
            hw_version="6.1.38-Unraid",
            serial_number="ABC123",
            hw_manufacturer="ASUS",
            hw_model="Z690",
            os_distro="Unraid",
            os_release="7.2.0",
            os_arch="x64",
            api_version="4.29.2",
            lan_ip="192.168.1.100",
            local_url="http://192.168.1.100",
            remote_url="https://myserver.myunraid.net",
            license_type="Pro",
            license_state="valid",
            cpu_brand="Intel Core i7-12700K",
            cpu_cores=12,
            cpu_threads=20,
        )

        assert info.uuid == "abc123-def456"
        assert info.hostname == "Tower"
        assert info.manufacturer == "Lime Technology"
        assert info.model == "Unraid 7.2.0"
        assert info.sw_version == "7.2.0"
        assert info.hw_version == "6.1.38-Unraid"
        assert info.serial_number == "ABC123"
        assert info.hw_manufacturer == "ASUS"
        assert info.hw_model == "Z690"
        assert info.os_distro == "Unraid"
        assert info.os_release == "7.2.0"
        assert info.os_arch == "x64"
        assert info.api_version == "4.29.2"
        assert info.lan_ip == "192.168.1.100"
        assert info.local_url == "http://192.168.1.100"
        assert info.remote_url == "https://myserver.myunraid.net"
        assert info.license_type == "Pro"
        assert info.license_state == "valid"
        assert info.cpu_brand == "Intel Core i7-12700K"
        assert info.cpu_cores == 12
        assert info.cpu_threads == 20

    def test_from_response_full_data(self) -> None:
        """Test from_response with complete GraphQL response."""
        from unraid_api.models import ServerInfo

        response = {
            "info": {
                "system": {
                    "uuid": "abc123-def456",
                    "manufacturer": "Dell Inc.",
                    "model": "PowerEdge R730",
                    "serial": "SYS123",
                },
                "baseboard": {
                    "manufacturer": "Dell",
                    "model": "0HFG24",
                    "serial": "BB456",
                },
                "os": {
                    "hostname": "Tower",
                    "distro": "Unraid",
                    "release": "7.2.0",
                    "kernel": "6.1.38-Unraid",
                    "arch": "x64",
                },
                "cpu": {
                    "manufacturer": "Intel",
                    "brand": "Intel Xeon E5-2680",
                    "cores": 12,
                    "threads": 24,
                },
                "versions": {
                    "core": {
                        "unraid": "7.2.0",
                        "api": "4.29.2",
                    }
                },
            },
            "server": {
                "lanip": "192.168.1.100",
                "localurl": "http://192.168.1.100",
                "remoteurl": "https://myserver.myunraid.net",
            },
            "registration": {
                "type": "Pro",
                "state": "valid",
            },
        }

        info = ServerInfo.from_response(response)

        assert info.uuid == "abc123-def456"
        assert info.hostname == "Tower"
        assert info.manufacturer == "Lime Technology"
        assert info.model == "Unraid 7.2.0"
        assert info.sw_version == "7.2.0"
        assert info.hw_version == "6.1.38-Unraid"
        assert info.serial_number == "SYS123"
        assert info.hw_manufacturer == "Dell Inc."
        assert info.hw_model == "PowerEdge R730"
        assert info.os_distro == "Unraid"
        assert info.os_release == "7.2.0"
        assert info.os_arch == "x64"
        assert info.api_version == "4.29.2"
        assert info.lan_ip == "192.168.1.100"
        assert info.local_url == "http://192.168.1.100"
        assert info.remote_url == "https://myserver.myunraid.net"
        assert info.license_type == "Pro"
        assert info.license_state == "valid"
        assert info.cpu_brand == "Intel Xeon E5-2680"
        assert info.cpu_cores == 12
        assert info.cpu_threads == 24

    def test_from_response_baseboard_fallback(self) -> None:
        """Test from_response falls back to baseboard when system info is missing."""
        from unraid_api.models import ServerInfo

        response = {
            "info": {
                "system": {
                    "uuid": "abc123",
                    "manufacturer": None,
                    "model": None,
                    "serial": None,
                },
                "baseboard": {
                    "manufacturer": "ASUS",
                    "model": "Z690",
                    "serial": "BBSERIAL123",
                },
                "os": {
                    "hostname": "Tower",
                    "distro": "Unraid",
                    "release": "7.2.0",
                    "kernel": "6.1.38-Unraid",
                    "arch": "x64",
                },
                "cpu": {
                    "brand": "Intel Core i7",
                    "cores": 8,
                    "threads": 16,
                },
                "versions": {"core": {"unraid": "7.2.0", "api": "4.29.2"}},
            },
            "server": {"lanip": "192.168.1.100"},
            "registration": {"type": "Basic", "state": "valid"},
        }

        info = ServerInfo.from_response(response)

        # Should fall back to baseboard values
        assert info.hw_manufacturer == "ASUS"
        assert info.hw_model == "Z690"
        assert info.serial_number == "BBSERIAL123"

    def test_from_response_empty_data(self) -> None:
        """Test from_response with empty/missing data."""
        from unraid_api.models import ServerInfo

        response: dict[str, object] = {}

        info = ServerInfo.from_response(response)

        assert info.uuid is None
        assert info.hostname is None
        assert info.manufacturer == "Lime Technology"
        assert info.model == "Unraid Unknown"
        assert info.sw_version == "Unknown"

    def test_from_response_partial_data(self) -> None:
        """Test from_response with partial data."""
        from unraid_api.models import ServerInfo

        response = {
            "info": {
                "system": {"uuid": "abc123"},
                "os": {"hostname": "MyServer"},
                "versions": {"core": {"unraid": "7.1.4"}},
            },
        }

        info = ServerInfo.from_response(response)

        assert info.uuid == "abc123"
        assert info.hostname == "MyServer"
        assert info.model == "Unraid 7.1.4"
        assert info.sw_version == "7.1.4"
        assert info.lan_ip is None
        assert info.license_type is None


class TestSystemMetrics:
    """Tests for SystemMetrics model."""

    def test_system_metrics_creation(self) -> None:
        """Test creating SystemMetrics with all fields."""
        from unraid_api.models import SystemMetrics

        metrics = SystemMetrics(
            cpu_percent=25.5,
            cpu_temperature=55.0,
            cpu_temperatures=[55.0, 52.0],
            cpu_power=65.5,
            memory_percent=50.0,
            memory_total=34359738368,
            memory_used=17179869184,
            memory_free=17179869184,
            memory_available=25769803776,
            swap_percent=10.0,
            swap_total=8589934592,
            swap_used=858993459,
            uptime=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
        )

        assert metrics.cpu_percent == 25.5
        assert metrics.cpu_temperature == 55.0
        assert metrics.cpu_temperatures == [55.0, 52.0]
        assert metrics.cpu_power == 65.5
        assert metrics.memory_percent == 50.0
        assert metrics.memory_total == 34359738368
        assert metrics.memory_used == 17179869184
        assert metrics.memory_available == 25769803776
        assert metrics.swap_percent == 10.0
        assert metrics.uptime is not None

    def test_system_metrics_defaults(self) -> None:
        """Test SystemMetrics with default values."""
        from unraid_api.models import SystemMetrics

        metrics = SystemMetrics()

        assert metrics.cpu_percent is None
        assert metrics.cpu_temperature is None
        assert metrics.cpu_temperatures == []
        assert metrics.cpu_power is None
        assert metrics.memory_percent is None
        assert metrics.memory_total is None
        assert metrics.uptime is None

    def test_system_metrics_from_response(self) -> None:
        """Test from_response with full data."""
        from unraid_api.models import SystemMetrics

        response = {
            "metrics": {
                "cpu": {"percentTotal": 25.5},
                "memory": {
                    "total": 34359738368,
                    "used": 17179869184,
                    "free": 17179869184,
                    "available": 25769803776,
                    "percentTotal": 50.0,
                    "swapTotal": 8589934592,
                    "swapUsed": 858993459,
                    "percentSwapTotal": 10.0,
                },
            },
            "info": {
                "os": {"uptime": "2024-01-15T10:30:00Z"},
                "cpu": {"packages": {"temp": [55.0, 52.0], "totalPower": 65.5}},
            },
        }

        metrics = SystemMetrics.from_response(response)

        assert metrics.cpu_percent == 25.5
        assert metrics.cpu_temperature == 55.0
        assert metrics.cpu_temperatures == [55.0, 52.0]
        assert metrics.cpu_power == 65.5
        assert metrics.memory_percent == 50.0
        assert metrics.memory_total == 34359738368
        assert metrics.memory_used == 17179869184
        assert metrics.memory_available == 25769803776
        assert metrics.swap_percent == 10.0
        assert metrics.swap_total == 8589934592
        assert metrics.swap_used == 858993459
        assert metrics.uptime is not None

    def test_system_metrics_from_response_minimal(self) -> None:
        """Test from_response with minimal data."""
        from unraid_api.models import SystemMetrics

        response = {
            "metrics": {
                "cpu": {"percentTotal": 10.0},
                "memory": {"percentTotal": 30.0},
            },
        }

        metrics = SystemMetrics.from_response(response)

        assert metrics.cpu_percent == 10.0
        assert metrics.cpu_temperature is None
        assert metrics.cpu_temperatures == []
        assert metrics.cpu_power is None
        assert metrics.memory_percent == 30.0
        assert metrics.memory_total is None
        assert metrics.uptime is None

    def test_system_metrics_from_response_empty(self) -> None:
        """Test from_response with empty data."""
        from unraid_api.models import SystemMetrics

        response: dict[str, object] = {}

        metrics = SystemMetrics.from_response(response)

        assert metrics.cpu_percent is None
        assert metrics.cpu_temperature is None
        assert metrics.cpu_temperatures == []
        assert metrics.cpu_power is None
        assert metrics.memory_percent is None
        assert metrics.uptime is None

    def test_system_metrics_from_response_single_temp(self) -> None:
        """Test from_response with single CPU temperature."""
        from unraid_api.models import SystemMetrics

        response = {
            "metrics": {"cpu": {"percentTotal": 15.0}},
            "info": {"cpu": {"packages": {"temp": [45.0], "totalPower": 30.0}}},
        }

        metrics = SystemMetrics.from_response(response)

        assert metrics.cpu_temperature == 45.0
        assert metrics.cpu_temperatures == [45.0]
        assert metrics.cpu_power == 30.0

    def test_system_metrics_from_response_empty_temp_list(self) -> None:
        """Test from_response with empty temperature list."""
        from unraid_api.models import SystemMetrics

        response = {
            "info": {"cpu": {"packages": {"temp": [], "totalPower": None}}},
        }

        metrics = SystemMetrics.from_response(response)

        assert metrics.cpu_temperature is None
        assert metrics.cpu_temperatures == []
        assert metrics.cpu_power is None


class TestRegistrationModel:
    """Tests for Registration model."""

    def test_registration_with_all_fields(self) -> None:
        """Test Registration creation with all fields."""
        from unraid_api.models import Registration

        reg = Registration(
            id="registration:1",
            type="Pro",
            state="VALID",
            expiration="2025-12-31",
            updateExpiration="2025-12-31",
        )

        assert reg.id == "registration:1"
        assert reg.type == "Pro"
        assert reg.state == "VALID"
        assert reg.expiration == "2025-12-31"

    def test_registration_with_minimal_fields(self) -> None:
        """Test Registration creation with minimal fields."""
        from unraid_api.models import Registration

        reg = Registration()

        assert reg.id is None
        assert reg.type is None
        assert reg.state is None


class TestVarsModel:
    """Tests for Vars model (system configuration)."""

    def test_vars_basic_creation(self) -> None:
        """Test Vars model creation with basic fields."""
        from unraid_api.models import Vars

        vars_data = Vars(
            id="vars:1",
            version="7.2.3",
            name="MyServer",
            time_zone="America/New_York",
        )

        assert vars_data.id == "vars:1"
        assert vars_data.version == "7.2.3"
        assert vars_data.name == "MyServer"
        assert vars_data.time_zone == "America/New_York"

    def test_vars_from_graphql_response(self) -> None:
        """Test Vars creation from GraphQL response with aliases."""
        from unraid_api.models import Vars

        # Response uses camelCase from GraphQL
        data = {
            "id": "vars:1",
            "version": "7.2.3",
            "name": "Cube",
            "timeZone": "UTC",
            "workgroup": "WORKGROUP",
            "mdNumDisks": 4,
            "mdState": "STARTED",
            "fsState": "Running",
            "shareCount": 10,
            "shareSmbCount": 8,
        }

        vars_obj = Vars(**data)

        assert vars_obj.name == "Cube"
        assert vars_obj.time_zone == "UTC"
        assert vars_obj.workgroup == "WORKGROUP"
        assert vars_obj.md_num_disks == 4
        assert vars_obj.md_state == "STARTED"
        assert vars_obj.fs_state == "Running"
        assert vars_obj.share_count == 10
        assert vars_obj.share_smb_count == 8

    def test_vars_with_optional_fields(self) -> None:
        """Test Vars with optional fields as None."""
        from unraid_api.models import Vars

        vars_data = Vars(name="Server")

        assert vars_data.name == "Server"
        assert vars_data.version is None
        assert vars_data.md_num_disks is None
        assert vars_data.csrf_token is None

    def test_vars_all_field_categories(self) -> None:
        """Test Vars model with fields from all categories."""
        from unraid_api.models import Vars

        vars_data = Vars(
            # Basic info
            version="7.2.3",
            name="Unraid",
            time_zone="America/Chicago",
            comment="My Unraid Server",
            # Network
            use_ssl=True,
            port=80,
            portssl=443,
            use_ssh=True,
            port_ssh=22,
            # Array state
            md_state="STARTED",
            md_num_disks=8,
            fs_state="Running",
            # Shares
            share_smb_enabled=True,
            share_count=15,
        )

        assert vars_data.version == "7.2.3"
        assert vars_data.use_ssl is True
        assert vars_data.port == 80
        assert vars_data.md_num_disks == 8
        assert vars_data.share_count == 15


class TestServiceModel:
    """Tests for Service model."""

    def test_service_with_all_fields(self) -> None:
        """Test Service creation with all fields."""
        from unraid_api.models import Service, ServiceUptime

        service = Service(
            id="service:docker",
            name="docker",
            online=True,
            uptime=ServiceUptime(timestamp="2024-01-15T10:30:00Z"),
            version="24.0.7",
        )

        assert service.id == "service:docker"
        assert service.name == "docker"
        assert service.online is True
        assert service.uptime is not None
        assert service.uptime.timestamp == "2024-01-15T10:30:00Z"
        assert service.version == "24.0.7"


class TestFlashModel:
    """Tests for Flash model."""

    def test_flash_with_all_fields(self) -> None:
        """Test Flash creation with all fields."""
        from unraid_api.models import Flash

        flash = Flash(
            id="flash:1",
            product="Ultra Fit",
            vendor="SanDisk",
        )

        assert flash.id == "flash:1"
        assert flash.product == "Ultra Fit"
        assert flash.vendor == "SanDisk"


class TestOwnerModel:
    """Tests for Owner model."""

    def test_owner_with_all_fields(self) -> None:
        """Test Owner creation with all fields."""
        from unraid_api.models import Owner

        owner = Owner(
            username="admin",
            avatar="https://example.com/avatar.png",
            url="https://my.unraid.net",
        )

        assert owner.username == "admin"
        assert owner.avatar == "https://example.com/avatar.png"
        assert owner.url == "https://my.unraid.net"


class TestPluginModel:
    """Tests for Plugin model."""

    def test_plugin_with_all_fields(self) -> None:
        """Test Plugin creation with all fields."""
        from unraid_api.models import Plugin

        plugin = Plugin(
            name="Test Plugin",
            version="1.0.0",
            hasApiModule=True,
            hasCliModule=False,
        )

        assert plugin.name == "Test Plugin"
        assert plugin.version == "1.0.0"
        assert plugin.hasApiModule is True
        assert plugin.hasCliModule is False

    def test_plugin_with_minimal_fields(self) -> None:
        """Test Plugin creation with minimal fields."""
        from unraid_api.models import Plugin

        plugin = Plugin(name="Test", version="1.0")

        assert plugin.name == "Test"
        assert plugin.version == "1.0"
        assert plugin.hasApiModule is None
        assert plugin.hasCliModule is None


class TestDockerNetworkModel:
    """Tests for DockerNetwork model."""

    def test_docker_network_with_all_fields(self) -> None:
        """Test DockerNetwork creation with all fields."""
        from unraid_api.models import DockerNetwork

        network = DockerNetwork(
            id="network:bridge",
            name="bridge",
            created="2024-01-01T00:00:00Z",
            scope="local",
            driver="bridge",
            enableIPv6=False,
            internal=False,
            attachable=False,
            ingress=False,
            configOnly=False,
        )

        assert network.id == "network:bridge"
        assert network.name == "bridge"
        assert network.driver == "bridge"


class TestLogFileModels:
    """Tests for LogFile and LogFileContent models."""

    def test_log_file_creation(self) -> None:
        """Test LogFile creation."""
        from unraid_api.models import LogFile

        log = LogFile(
            name="syslog",
            path="/var/log/syslog",
            size=102400,
            modifiedAt="2024-01-15T10:30:00Z",
        )

        assert log.name == "syslog"
        assert log.path == "/var/log/syslog"
        assert log.size == 102400

    def test_log_file_content_creation(self) -> None:
        """Test LogFileContent creation."""
        from unraid_api.models import LogFileContent

        content = LogFileContent(
            path="/var/log/syslog",
            content="Log entry 1\nLog entry 2\n",
            totalLines=100,
            startLine=1,
        )

        assert content.path == "/var/log/syslog"
        assert content.content is not None
        assert "Log entry 1" in content.content
        assert content.totalLines == 100


class TestCloudModel:
    """Tests for Cloud model."""

    def test_cloud_with_all_fields(self) -> None:
        """Test Cloud creation with all fields."""
        from unraid_api.models import (
            ApiKeyResponse,
            Cloud,
            CloudResponse,
            MinigraphqlResponse,
            RelayResponse,
        )

        cloud = Cloud(
            error=None,
            apiKey=ApiKeyResponse(valid=True, error=None),
            relay=RelayResponse(status="connected", timeout="5000", error=None),
            minigraphql=MinigraphqlResponse(status="CONNECTED", timeout=30, error=None),
            cloud=CloudResponse(status="ok", ip="192.168.1.100", error=None),
            allowedOrigins=["http://localhost"],
        )

        assert cloud.cloud is not None
        assert cloud.cloud.status == "ok"
        assert cloud.apiKey is not None
        assert cloud.apiKey.valid is True
        assert len(cloud.allowedOrigins) == 1

    def test_cloud_with_error(self) -> None:
        """Test Cloud creation with error state."""
        from unraid_api.models import ApiKeyResponse, Cloud, CloudResponse

        cloud = Cloud(
            error="Connection failed",
            apiKey=ApiKeyResponse(valid=False, error="Invalid key"),
            cloud=CloudResponse(status="error", error="Connection failed"),
        )

        assert cloud.error == "Connection failed"
        assert cloud.cloud is not None
        assert cloud.cloud.status == "error"


class TestConnectModel:
    """Tests for Connect model."""

    def test_connect_signed_in(self) -> None:
        """Test Connect creation when signed in."""
        from unraid_api.models import Connect, DynamicRemoteAccessStatus

        connect = Connect(
            id="connect:1",
            dynamicRemoteAccess=DynamicRemoteAccessStatus(
                enabledType="UPNP",
                runningType="UPNP",
                error=None,
            ),
        )

        assert connect.id == "connect:1"
        assert connect.dynamicRemoteAccess is not None
        assert connect.dynamicRemoteAccess.enabledType == "UPNP"

    def test_connect_not_signed_in(self) -> None:
        """Test Connect creation when not signed in."""
        from unraid_api.models import Connect, DynamicRemoteAccessStatus

        connect = Connect(
            id="connect:1",
            dynamicRemoteAccess=DynamicRemoteAccessStatus(
                enabledType="DISABLED",
                runningType="DISABLED",
            ),
        )

        assert connect.dynamicRemoteAccess is not None
        assert connect.dynamicRemoteAccess.enabledType == "DISABLED"


class TestRemoteAccessModel:
    """Tests for RemoteAccess model."""

    def test_remote_access_enabled(self) -> None:
        """Test RemoteAccess creation when enabled."""
        from unraid_api.models import RemoteAccess

        remote = RemoteAccess(
            accessType="ALWAYS",
            forwardType="UPNP",
            port=443,
        )

        assert remote.accessType == "ALWAYS"
        assert remote.forwardType == "UPNP"
        assert remote.port == 443

    def test_remote_access_disabled(self) -> None:
        """Test RemoteAccess creation when disabled."""
        from unraid_api.models import RemoteAccess

        remote = RemoteAccess(accessType="DISABLED")

        assert remote.accessType == "DISABLED"
        assert remote.port is None


class TestDockerContainerExtendedFields:
    """Tests for extended DockerContainer fields."""

    def test_container_with_extended_fields(self) -> None:
        """Test DockerContainer with all extended fields."""
        from unraid_api.models import ContainerHostConfig, DockerContainer

        container = DockerContainer(
            id="abc123",
            name="test-container",
            names=["/test-container"],
            state="running",
            status="Up 5 days",
            image="nginx:latest",
            imageId="sha256:abc123",
            command="/docker-entrypoint.sh nginx",
            created=1704067200,
            sizeRootFs=150000000,
            labels={"com.docker.compose.project": "test"},
            networkSettings={"Networks": {"bridge": {}}},
            mounts=[{"Type": "bind", "Source": "/data", "Destination": "/data"}],
            hostConfig=ContainerHostConfig(networkMode="bridge"),
        )

        assert container.imageId == "sha256:abc123"
        assert container.command == "/docker-entrypoint.sh nginx"
        assert container.created == 1704067200
        assert container.sizeRootFs == 150000000
        assert container.labels is not None
        assert container.labels["com.docker.compose.project"] == "test"
        assert container.mounts is not None
        assert len(container.mounts) == 1
        assert container.hostConfig is not None
        assert container.hostConfig.networkMode == "bridge"

    def test_container_from_api_response_with_extended_fields(self) -> None:
        """Test DockerContainer.from_api_response with extended fields."""
        from unraid_api.models import DockerContainer

        data = {
            "id": "abc123",
            "names": ["/myapp"],
            "state": "running",
            "status": "Up 2 hours",
            "image": "myapp:latest",
            "imageId": "sha256:def456",
            "command": "python main.py",
            "created": 1704067200,
            "sizeRootFs": 200000000,
            "labels": {"maintainer": "test"},
            "networkSettings": {"IPAddress": "172.17.0.2"},
            "mounts": [],
            "hostConfig": {"networkMode": "host"},
            "ports": [],
        }

        container = DockerContainer.from_api_response(data)

        assert container.name == "myapp"
        assert container.imageId == "sha256:def456"
        assert container.command == "python main.py"
        assert container.created == 1704067200
        assert container.sizeRootFs == 200000000
        assert container.hostConfig is not None
        assert container.hostConfig.networkMode == "host"


class TestDockerContainerStatsSanitization:
    """Tests for ANSI escape-sequence stripping in DockerContainerStats (#71)."""

    def test_id_strips_ansi_escape_sequences(self) -> None:
        """The clear-screen/cursor-home escapes glued onto the first row's id
        are removed, recovering the valid PrefixedID."""
        from unraid_api.models import DockerContainerStats

        # Real-world corruption: the PrefixedID prefix (``<prefix>:``) is intact
        # but ``\x1b[J\x1b[H`` is injected before the actual container id.
        corrupted = (
            "341df820ea490:\x1b[J\x1b[H"
            # pragma: allowlist nextline secret
            "25d9c2630a90520ed9d9f6b2366c3d5a3517f3efd3b5e260823081f0dbdf43cb"
        )
        stats = DockerContainerStats(id=corrupted)

        assert stats.id == (
            "341df820ea490:"
            # pragma: allowlist nextline secret
            "25d9c2630a90520ed9d9f6b2366c3d5a3517f3efd3b5e260823081f0dbdf43cb"
        )
        assert "\x1b" not in stats.id

    def test_clean_id_passes_through_unchanged(self) -> None:
        """An id with no escape sequences is returned verbatim."""
        from unraid_api.models import DockerContainerStats

        clean = "341df820ea490:f3f490ce40ec797acac2d42730a94d890eb0f811718905a6"
        stats = DockerContainerStats(id=clean)

        assert stats.id == clean

    def test_none_id_stays_none(self) -> None:
        """An explicit null id (as the API may send) passes through as None."""
        from unraid_api.models import DockerContainerStats

        stats = DockerContainerStats(id=None, cpuPercent=12.5)

        assert stats.id is None

    def test_other_string_fields_are_sanitized(self) -> None:
        """Escape sequences are stripped from all string fields, not just id."""
        from unraid_api.models import DockerContainerStats

        stats = DockerContainerStats(
            id="container:abc",
            memUsage="\x1b[H512MB / 2GB",
            netIO="100MB / 50MB\x1b[J",
            blockIO="10MB / 5MB",
        )

        assert stats.memUsage == "512MB / 2GB"
        assert stats.netIO == "100MB / 50MB"
        assert stats.blockIO == "10MB / 5MB"


class TestUPSExtendedFields:
    """Tests for UPS model extended fields."""

    def test_ups_battery_with_health(self) -> None:
        """Test UPSBattery with health field."""
        from unraid_api.models import UPSBattery

        battery = UPSBattery(
            chargeLevel=100,
            estimatedRuntime=1800,
            health="Good",
        )

        assert battery.chargeLevel == 100
        assert battery.estimatedRuntime == 1800
        assert battery.health == "Good"

    def test_ups_device_with_model(self) -> None:
        """Test UPSDevice with model field."""
        from unraid_api.models import UPSBattery, UPSDevice, UPSPower

        device = UPSDevice(
            id="ups:1",
            name="APC UPS",
            model="Back-UPS 1500",
            status="online",
            battery=UPSBattery(chargeLevel=95, estimatedRuntime=1200, health="Good"),
            power=UPSPower(
                inputVoltage=120.0, outputVoltage=120.0, loadPercentage=25.0
            ),
        )

        assert device.model == "Back-UPS 1500"
        assert device.battery.health == "Good"


class TestUserAccountModel:
    """Tests for UserAccount model."""

    def test_user_account_with_all_fields(self) -> None:
        """Test UserAccount creation with all fields."""
        from unraid_api.models import Permission, UserAccount

        user = UserAccount(
            id="user:abc123",
            name="admin",
            description="Admin user",
            roles=["ADMIN"],
            permissions=[Permission(resource="docker", actions=["read", "write"])],
        )

        assert user.id == "user:abc123"
        assert user.name == "admin"
        assert user.description == "Admin user"
        assert user.roles == ["ADMIN"]
        assert user.permissions is not None
        assert len(user.permissions) == 1
        assert user.permissions[0].resource == "docker"

    def test_user_account_with_minimal_fields(self) -> None:
        """Test UserAccount creation with minimal required fields."""
        from unraid_api.models import UserAccount

        user = UserAccount(id="user:abc123", name="viewer")

        assert user.id == "user:abc123"
        assert user.name == "viewer"
        assert user.description is None
        assert user.roles == []
        assert user.permissions is None


class TestApiKeyModel:
    """Tests for ApiKey model."""

    def test_api_key_with_all_fields(self) -> None:
        """Test ApiKey creation with all fields."""
        from unraid_api.models import ApiKey

        key = ApiKey(
            id="apikey:123",
            key="abc-def-ghi",
            name="My Key",
            description="Test key",
            roles=["ADMIN"],
            createdAt="2026-01-01T00:00:00Z",
        )

        assert key.id == "apikey:123"
        assert key.key == "abc-def-ghi"
        assert key.name == "My Key"
        assert key.description == "Test key"
        assert key.roles == ["ADMIN"]
        assert key.createdAt == "2026-01-01T00:00:00Z"

    def test_api_key_with_minimal_fields(self) -> None:
        """Test ApiKey creation with minimal fields."""
        from unraid_api.models import ApiKey

        key = ApiKey(id="apikey:123", name="Viewer Key")

        assert key.id == "apikey:123"
        assert key.key is None
        assert key.name == "Viewer Key"
        assert key.roles == []


class TestDockerContainerLogModels:
    """Tests for Docker container log models."""

    def test_log_line_creation(self) -> None:
        """Test DockerContainerLogLine creation."""
        from unraid_api.models import DockerContainerLogLine

        line = DockerContainerLogLine(
            timestamp="2026-01-15T10:30:00Z",
            message="Container started successfully",
        )

        assert line.timestamp == "2026-01-15T10:30:00Z"
        assert line.message == "Container started successfully"

    def test_container_logs_with_lines(self) -> None:
        """Test DockerContainerLogs with log lines."""
        from unraid_api.models import DockerContainerLogLine, DockerContainerLogs

        logs = DockerContainerLogs(
            containerId="container:abc123",
            lines=[
                DockerContainerLogLine(
                    timestamp="2026-01-15T10:30:00Z",
                    message="Starting...",
                ),
                DockerContainerLogLine(
                    timestamp="2026-01-15T10:30:01Z",
                    message="Ready.",
                ),
            ],
            cursor="2026-01-15T10:30:01Z",
        )

        assert logs.containerId == "container:abc123"
        assert len(logs.lines) == 2
        assert logs.lines[0].message == "Starting..."
        assert logs.cursor == "2026-01-15T10:30:01Z"

    def test_container_logs_empty(self) -> None:
        """Test DockerContainerLogs with no lines."""
        from unraid_api.models import DockerContainerLogs

        logs = DockerContainerLogs()

        assert logs.containerId is None
        assert logs.lines == []
        assert logs.cursor is None


class TestPermissionModel:
    """Tests for Permission model."""

    def test_permission_creation(self) -> None:
        """Test Permission creation."""
        from unraid_api.models import Permission

        perm = Permission(resource="docker", actions=["read", "write", "execute"])

        assert perm.resource == "docker"
        assert perm.actions == ["read", "write", "execute"]

    def test_permission_default_actions(self) -> None:
        """Test Permission creation with default empty actions."""
        from unraid_api.models import Permission

        perm = Permission(resource="array")

        assert perm.resource == "array"
        assert perm.actions == []


# =============================================================================
# Issue #15: format_bytes utility
# =============================================================================


class TestFormatBytes:
    """Tests for format_bytes utility function."""

    def test_none_returns_none(self) -> None:
        """Test that None input returns None."""
        assert format_bytes(None) is None

    def test_zero_bytes(self) -> None:
        """Test 0 bytes."""
        assert format_bytes(0) == "0 B"

    def test_bytes(self) -> None:
        """Test small byte values."""
        assert format_bytes(512) == "512 B"

    def test_kilobytes(self) -> None:
        """Test kilobyte values."""
        assert format_bytes(1024) == "1 KB"
        assert format_bytes(1536) == "1.5 KB"

    def test_megabytes(self) -> None:
        """Test megabyte values."""
        assert format_bytes(1048576) == "1 MB"

    def test_gigabytes(self) -> None:
        """Test gigabyte values."""
        assert format_bytes(1073741824) == "1 GB"

    def test_terabytes(self) -> None:
        """Test terabyte values."""
        assert format_bytes(1099511627776) == "1 TB"

    def test_petabytes(self) -> None:
        """Test petabyte values."""
        assert format_bytes(1125899906842624) == "1 PB"

    def test_fractional_gb(self) -> None:
        """Test fractional gigabyte values."""
        result = format_bytes(int(1.5 * 1073741824))
        assert result == "1.5 GB"


# =============================================================================
# Issue #15: _format_duration utility
# =============================================================================


class TestFormatDuration:
    """Tests for _format_duration utility."""

    def test_zero_seconds(self) -> None:
        """Test 0 seconds."""
        assert _format_duration(0) == "0 seconds"

    def test_one_second(self) -> None:
        """Test 1 second (singular)."""
        assert _format_duration(1) == "1 second"

    def test_seconds_only(self) -> None:
        """Test seconds-only values."""
        assert _format_duration(45) == "45 seconds"

    def test_minutes_and_seconds(self) -> None:
        """Test minutes and seconds."""
        assert _format_duration(90) == "1 minute 30 seconds"

    def test_hours_minutes_seconds(self) -> None:
        """Test hours, minutes, and seconds."""
        assert _format_duration(3661) == "1 hour 1 minute 1 second"

    def test_hours_only(self) -> None:
        """Test exact hours."""
        assert _format_duration(7200) == "2 hours"

    def test_negative_clamps_to_zero(self) -> None:
        """Test that negative values clamp to 0."""
        assert _format_duration(-5) == "0 seconds"

    def test_large_duration(self) -> None:
        """Test a large multi-hour duration."""
        # 2h 15m 30s = 8130 seconds
        assert _format_duration(8130) == "2 hours 15 minutes 30 seconds"


# =============================================================================
# Issue #15: SystemMetrics computed properties
# =============================================================================


class TestSystemMetricsComputedProperties:
    """Tests for SystemMetrics computed properties."""

    def test_average_cpu_temperature_multiple(self) -> None:
        """Test average CPU temp with multiple packages."""
        from unraid_api.models import SystemMetrics

        metrics = SystemMetrics(cpu_temperatures=[50.0, 60.0, 70.0])
        assert metrics.average_cpu_temperature == 60.0

    def test_average_cpu_temperature_single(self) -> None:
        """Test average CPU temp with single package."""
        from unraid_api.models import SystemMetrics

        metrics = SystemMetrics(cpu_temperatures=[55.0])
        assert metrics.average_cpu_temperature == 55.0

    def test_average_cpu_temperature_empty(self) -> None:
        """Test average CPU temp with no data."""
        from unraid_api.models import SystemMetrics

        metrics = SystemMetrics()
        assert metrics.average_cpu_temperature is None

    def test_memory_used_fallback_in_from_response(self) -> None:
        """Test memory_used falls back to total - available."""
        from unraid_api.models import SystemMetrics

        response = {
            "metrics": {
                "memory": {
                    "total": 32000000000,
                    "available": 20000000000,
                    "percentTotal": 37.5,
                }
            }
        }

        metrics = SystemMetrics.from_response(response)
        assert metrics.memory_used == 12000000000

    def test_memory_used_direct_value(self) -> None:
        """Test memory_used uses direct API value when available."""
        from unraid_api.models import SystemMetrics

        response = {
            "metrics": {
                "memory": {
                    "total": 32000000000,
                    "used": 15000000000,
                    "available": 20000000000,
                }
            }
        }

        metrics = SystemMetrics.from_response(response)
        assert metrics.memory_used == 15000000000


# =============================================================================
# Issue #16: ZFS disk usage fallback
# =============================================================================


class TestArrayDiskZFSFallback:
    """Tests for ArrayDisk ZFS usage fallback."""

    def test_fs_used_bytes_positive_value(self) -> None:
        """Test fs_used_bytes with a positive fsUsed value."""
        disk = ArrayDisk(id="disk:1", fsUsed=500)
        assert disk.fs_used_bytes == 512000

    def test_fs_used_bytes_zero_with_fallback(self) -> None:
        """Test fs_used_bytes falls back to fsSize-fsFree when fsUsed=0."""
        disk = ArrayDisk(id="disk:1", fsSize=1000, fsUsed=0, fsFree=700)
        assert disk.fs_used_bytes == 300 * 1024

    def test_fs_used_bytes_none_with_fallback(self) -> None:
        """Test fs_used_bytes falls back when fsUsed is None."""
        disk = ArrayDisk(id="disk:1", fsSize=1000, fsUsed=None, fsFree=700)
        assert disk.fs_used_bytes == 300 * 1024

    def test_fs_used_bytes_all_none(self) -> None:
        """Test fs_used_bytes returns None when all values are None."""
        disk = ArrayDisk(id="disk:1")
        assert disk.fs_used_bytes is None

    def test_usage_percent_zfs_fallback(self) -> None:
        """Test usage_percent uses fallback for ZFS (fsUsed=0)."""
        disk = ArrayDisk(id="disk:1", fsSize=1000, fsUsed=0, fsFree=700)
        assert disk.usage_percent == 30.0

    def test_usage_percent_positive_fsused(self) -> None:
        """Test usage_percent with positive fsUsed."""
        disk = ArrayDisk(id="disk:1", fsSize=1000, fsUsed=250)
        assert disk.usage_percent == 25.0

    def test_usage_percent_none_fssize(self) -> None:
        """Test usage_percent returns None when fsSize is None."""
        disk = ArrayDisk(id="disk:1", fsUsed=250)
        assert disk.usage_percent is None

    def test_usage_percent_zero_fssize(self) -> None:
        """Test usage_percent returns None when fsSize is 0."""
        disk = ArrayDisk(id="disk:1", fsSize=0, fsUsed=0)
        assert disk.usage_percent is None

    def test_fs_used_bytes_zero_no_fallback(self) -> None:
        """Test fs_used_bytes when fsUsed=0 and no fsFree for fallback."""
        disk = ArrayDisk(id="disk:1", fsUsed=0)
        assert disk.fs_used_bytes == 0

    def test_usage_percent_none_fsused_no_fsfree(self) -> None:
        """Test usage_percent when fsUsed is None and fsFree also None."""
        disk = ArrayDisk(id="disk:1", fsSize=1000, fsUsed=None, fsFree=None)
        assert disk.usage_percent is None


# =============================================================================
# Issue #17: State helper properties
# =============================================================================


class TestArrayDiskIsHealthy:
    """Tests for ArrayDisk.is_healthy property."""

    def test_healthy_disk(self) -> None:
        """Test is_healthy returns True for DISK_OK."""
        disk = ArrayDisk(id="disk:1", status="DISK_OK")
        assert disk.is_healthy is True

    def test_unhealthy_disk(self) -> None:
        """Test is_healthy returns False for non-OK status."""
        disk = ArrayDisk(id="disk:1", status="DISK_DSBL")
        assert disk.is_healthy is False

    def test_none_status(self) -> None:
        """Test is_healthy returns False for None status."""
        disk = ArrayDisk(id="disk:1")
        assert disk.is_healthy is False

    def test_case_insensitive(self) -> None:
        """Test is_healthy is case insensitive."""
        disk = ArrayDisk(id="disk:1", status="disk_ok")
        assert disk.is_healthy is True


class TestDockerContainerIsRunning:
    """Tests for DockerContainer.is_running property."""

    def test_running(self) -> None:
        """Test is_running for running container."""
        c = DockerContainer(id="c:1", name="test", state="running")
        assert c.is_running is True

    def test_stopped(self) -> None:
        """Test is_running for stopped container."""
        c = DockerContainer(id="c:1", name="test", state="exited")
        assert c.is_running is False

    def test_none_state(self) -> None:
        """Test is_running for None state."""
        c = DockerContainer(id="c:1", name="test")
        assert c.is_running is False

    def test_case_insensitive(self) -> None:
        """Test is_running is case insensitive."""
        c = DockerContainer(id="c:1", name="test", state="RUNNING")
        assert c.is_running is True


class TestVmDomainIsRunning:
    """Tests for VmDomain.is_running property."""

    def test_running(self) -> None:
        """Test is_running for running VM."""
        from unraid_api.models import VmDomain

        vm = VmDomain(id="vm:1", name="test", state="running")
        assert vm.is_running is True

    def test_idle(self) -> None:
        """Test is_running for idle VM."""
        from unraid_api.models import VmDomain

        vm = VmDomain(id="vm:1", name="test", state="idle")
        assert vm.is_running is True

    def test_shutoff(self) -> None:
        """Test is_running for shut off VM."""
        from unraid_api.models import VmDomain

        vm = VmDomain(id="vm:1", name="test", state="shutoff")
        assert vm.is_running is False

    def test_none_state(self) -> None:
        """Test is_running for None state."""
        from unraid_api.models import VmDomain

        vm = VmDomain(id="vm:1", name="test")
        assert vm.is_running is False


class TestParityCheckHelpers:
    """Tests for ParityCheck helper properties."""

    def test_is_running_active(self) -> None:
        """Test is_running when actively running."""
        from unraid_api.models import ParityCheck

        pc = ParityCheck(status="RUNNING")
        assert pc.is_running is True

    def test_is_running_paused(self) -> None:
        """Test is_running when paused."""
        from unraid_api.models import ParityCheck

        pc = ParityCheck(status="PAUSED")
        assert pc.is_running is True

    def test_is_running_idle(self) -> None:
        """Test is_running when idle."""
        from unraid_api.models import ParityCheck

        pc = ParityCheck(status="IDLE")
        assert pc.is_running is False

    def test_is_running_none_status(self) -> None:
        """Test is_running with None status."""
        from unraid_api.models import ParityCheck

        pc = ParityCheck()
        assert pc.is_running is False

    def test_has_problem_failed(self) -> None:
        """Test has_problem when failed."""
        from unraid_api.models import ParityCheck

        pc = ParityCheck(status="FAILED")
        assert pc.has_problem is True

    def test_has_problem_with_errors(self) -> None:
        """Test has_problem with errors."""
        from unraid_api.models import ParityCheck

        pc = ParityCheck(status="RUNNING", errors=5)
        assert pc.has_problem is True

    def test_has_problem_clean(self) -> None:
        """Test has_problem when clean."""
        from unraid_api.models import ParityCheck

        pc = ParityCheck(status="IDLE", errors=0)
        assert pc.has_problem is False

    def test_has_problem_none(self) -> None:
        """Test has_problem with no data."""
        from unraid_api.models import ParityCheck

        pc = ParityCheck()
        assert pc.has_problem is False


# =============================================================================
# Issue #18: ParityHistoryEntry model
# =============================================================================


class TestParityHistoryEntry:
    """Tests for ParityHistoryEntry model."""

    def test_creation_with_all_fields(self) -> None:
        """Test creating with all fields."""
        entry = ParityHistoryEntry(
            date="2024-01-15T10:30:00Z",
            duration=8130,
            speed="150 MB/s",
            status="OK",
            errors=0,
        )

        assert entry.date is not None
        assert entry.date.year == 2024
        assert entry.duration == 8130
        assert entry.speed == "150 MB/s"
        assert entry.status == "OK"
        assert entry.errors == 0

    def test_duration_formatted(self) -> None:
        """Test duration_formatted property."""
        entry = ParityHistoryEntry(duration=8130)
        assert entry.duration_formatted == "2 hours 15 minutes 30 seconds"

    def test_duration_formatted_none(self) -> None:
        """Test duration_formatted when duration is None."""
        entry = ParityHistoryEntry()
        assert entry.duration_formatted is None

    def test_epoch_date(self) -> None:
        """Test parsing epoch timestamp for date."""
        entry = ParityHistoryEntry(date=1705312200)
        assert entry.date is not None
        assert entry.date.year == 2024

    def test_date_none(self) -> None:
        """Test date when None."""
        entry = ParityHistoryEntry()
        assert entry.date is None

    def test_epoch_string_date(self) -> None:
        """Test parsing epoch as string for date."""
        entry = ParityHistoryEntry(date="1705312200")
        assert entry.date is not None

    def test_invalid_date_string(self) -> None:
        """Test invalid date string returns None."""
        entry = ParityHistoryEntry(date="not-a-date")
        assert entry.date is None

    def test_datetime_object_date(self) -> None:
        """Test passing datetime directly for date."""
        dt = datetime(2024, 1, 15, tzinfo=UTC)
        entry = ParityHistoryEntry(date=dt)
        assert entry.date == dt

    def test_parse_parity_date_datetime_passthrough(self) -> None:
        """Test _parse_parity_date with datetime input passes through."""
        from unraid_api.models import _parse_parity_date

        dt = datetime(2024, 1, 15, tzinfo=UTC)
        result = _parse_parity_date(dt)
        assert result is dt

    def test_float_epoch_date(self) -> None:
        """Test float epoch timestamp for date."""
        entry = ParityHistoryEntry(date=1705312200.5)
        assert entry.date is not None


# =============================================================================
# Issue #19: UPS helpers
# =============================================================================


class TestUPSBatteryRuntimeFormatted:
    """Tests for UPSBattery.runtime_formatted property."""

    def test_runtime_formatted(self) -> None:
        """Test runtime_formatted with a typical value."""
        from unraid_api.models import UPSBattery

        battery = UPSBattery(estimatedRuntime=8130)
        assert battery.runtime_formatted == "2 hours 15 minutes 30 seconds"

    def test_runtime_formatted_none(self) -> None:
        """Test runtime_formatted when no data."""
        from unraid_api.models import UPSBattery

        battery = UPSBattery()
        assert battery.runtime_formatted is None

    def test_runtime_formatted_zero(self) -> None:
        """Test runtime_formatted for 0 seconds."""
        from unraid_api.models import UPSBattery

        battery = UPSBattery(estimatedRuntime=0)
        assert battery.runtime_formatted == "0 seconds"

    def test_runtime_formatted_minutes_only(self) -> None:
        """Test runtime_formatted with minutes only."""
        from unraid_api.models import UPSBattery

        battery = UPSBattery(estimatedRuntime=1800)
        assert battery.runtime_formatted == "30 minutes"


class TestUPSDeviceHelpers:
    """Tests for UPSDevice helper methods."""

    def test_is_connected_online(self) -> None:
        """Test is_connected for online UPS."""
        from unraid_api.models import UPSDevice

        ups = UPSDevice(id="ups:1", name="test", status="ONLINE")
        assert ups.is_connected is True

    def test_is_connected_offline(self) -> None:
        """Test is_connected for offline UPS."""
        from unraid_api.models import UPSDevice

        ups = UPSDevice(id="ups:1", name="test", status="OFFLINE")
        assert ups.is_connected is False

    def test_is_connected_off(self) -> None:
        """Test is_connected for OFF UPS."""
        from unraid_api.models import UPSDevice

        ups = UPSDevice(id="ups:1", name="test", status="OFF")
        assert ups.is_connected is False

    def test_is_connected_none(self) -> None:
        """Test is_connected for None status."""
        from unraid_api.models import UPSDevice

        ups = UPSDevice(id="ups:1", name="test")
        assert ups.is_connected is False

    def test_calculate_power_watts(self) -> None:
        """Test power calculation."""
        from unraid_api.models import UPSDevice, UPSPower

        ups = UPSDevice(
            id="ups:1",
            name="test",
            power=UPSPower(loadPercentage=25.0),
        )
        result = ups.calculate_power_watts(1500)
        assert result == 375.0

    def test_calculate_power_watts_none_load(self) -> None:
        """Test power calculation with no load data."""
        from unraid_api.models import UPSDevice

        ups = UPSDevice(id="ups:1", name="test")
        assert ups.calculate_power_watts(1500) is None

    def test_calculate_power_watts_zero_load(self) -> None:
        """Test power calculation with zero load."""
        from unraid_api.models import UPSDevice, UPSPower

        ups = UPSDevice(
            id="ups:1",
            name="test",
            power=UPSPower(loadPercentage=0.0),
        )
        assert ups.calculate_power_watts(1500) == 0.0


class TestUPSPowerFields:
    """Tests for UPSPower nominalPower and currentPower fields."""

    def test_ups_power_with_nominal_and_current(self) -> None:
        """Test UPSPower with nominalPower and currentPower."""
        from unraid_api.models import UPSPower

        power = UPSPower(
            inputVoltage=120.0,
            outputVoltage=120.0,
            loadPercentage=25,
            nominalPower=1500,
            currentPower=375.0,
        )
        assert power.nominalPower == 1500
        assert power.currentPower == 375.0

    def test_ups_power_nominal_and_current_default_none(self) -> None:
        """Test nominalPower and currentPower default to None."""
        from unraid_api.models import UPSPower

        power = UPSPower()
        assert power.nominalPower is None
        assert power.currentPower is None

    def test_ups_power_nominal_without_current(self) -> None:
        """Test UPSPower with only nominalPower (no currentPower)."""
        from unraid_api.models import UPSPower

        power = UPSPower(nominalPower=900)
        assert power.nominalPower == 900
        assert power.currentPower is None


# =============================================================================
# Issue #21: VersionInfo model
# =============================================================================


class TestVersionInfo:
    """Tests for VersionInfo model."""

    def test_version_info_with_values(self) -> None:
        """Test VersionInfo with version strings."""
        vi = VersionInfo(api="4.29.2", unraid="7.2.0")
        assert vi.api == "4.29.2"
        assert vi.unraid == "7.2.0"

    def test_version_info_defaults(self) -> None:
        """Test VersionInfo default values."""
        vi = VersionInfo()
        assert vi.api == "unknown"
        assert vi.unraid == "unknown"


# =============================================================================
# Issue #17: Constants module
# =============================================================================


class TestConstants:
    """Tests for constants module."""

    def test_min_versions_defined(self) -> None:
        """Test that minimum version constants are defined."""
        from unraid_api.const import MIN_API_VERSION, MIN_UNRAID_VERSION

        assert MIN_API_VERSION == "4.31.1"
        assert MIN_UNRAID_VERSION == "7.2.4"

    def test_container_states_defined(self) -> None:
        """Test that container state constants are defined."""
        from unraid_api.const import CONTAINER_STATE_RUNNING, CONTAINER_STATE_STOPPED

        assert CONTAINER_STATE_RUNNING == "running"
        assert CONTAINER_STATE_STOPPED == "stopped"

    def test_disk_status_constants(self) -> None:
        """Test that disk status constants are defined."""
        from unraid_api.const import DISK_STATUS_OK

        assert DISK_STATUS_OK == "DISK_OK"


# =============================================================================
# v4.30.0 New Model Tests
# =============================================================================


class TestTailscaleStatus:
    """Tests for TailscaleStatus model."""

    def test_tailscale_status_all_fields(self) -> None:
        """TailscaleStatus must cover every field the schema exposes."""
        from unraid_api.models import TailscaleExitNodeStatus, TailscaleStatus

        status = TailscaleStatus(
            hostname="my-container",
            dnsName="my-container.tail12345.ts.net.",
            online=True,
            version="1.80.0",
            latestVersion="1.82.5",
            updateAvailable=True,
            relay="sea",
            relayName="Seattle",
            tailscaleIps=["100.64.0.2", "fd7a:115c:a1e0::2"],
            primaryRoutes=["10.0.0.0/24"],
            isExitNode=False,
            exitNodeStatus=TailscaleExitNodeStatus(
                online=True,
                tailscaleIps=["100.64.0.3"],
            ),
            webUiUrl="http://100.64.0.2:8080",
            keyExpiry="2026-10-01T12:00:00Z",
            keyExpiryDays=42,
            keyExpired=False,
            backendState="Running",
            authUrl=None,
        )

        assert status.hostname == "my-container"
        assert status.dnsName == "my-container.tail12345.ts.net."
        assert status.online is True
        assert status.version == "1.80.0"
        assert status.latestVersion == "1.82.5"
        assert status.updateAvailable is True
        assert status.relay == "sea"
        assert status.relayName == "Seattle"
        assert status.tailscaleIps == ["100.64.0.2", "fd7a:115c:a1e0::2"]
        assert status.primaryRoutes == ["10.0.0.0/24"]
        assert status.isExitNode is False
        assert status.exitNodeStatus is not None
        assert status.exitNodeStatus.online is True
        assert status.exitNodeStatus.tailscaleIps == ["100.64.0.3"]
        assert status.webUiUrl == "http://100.64.0.2:8080"
        assert status.keyExpiry == datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
        assert status.keyExpiryDays == 42
        assert status.keyExpired is False
        assert status.backendState == "Running"
        assert status.authUrl is None

    def test_tailscale_status_defaults(self) -> None:
        """Test TailscaleStatus with default (None) values."""
        from unraid_api.models import TailscaleStatus

        status = TailscaleStatus()

        assert status.hostname is None
        assert status.dnsName is None
        assert status.online is None
        assert status.version is None
        assert status.latestVersion is None
        assert status.updateAvailable is None
        assert status.tailscaleIps is None
        assert status.primaryRoutes is None
        assert status.isExitNode is None
        assert status.exitNodeStatus is None
        assert status.keyExpiry is None
        assert status.keyExpiryDays is None
        assert status.keyExpired is None
        assert status.backendState is None
        assert status.authUrl is None

    def test_tailscale_exit_node_status(self) -> None:
        """TailscaleExitNodeStatus is the nested exit-node shape from the API."""
        from unraid_api.models import TailscaleExitNodeStatus

        exit_node = TailscaleExitNodeStatus(
            online=True,
            tailscaleIps=["100.64.0.99"],
        )

        assert exit_node.online is True
        assert exit_node.tailscaleIps == ["100.64.0.99"]

        empty = TailscaleExitNodeStatus()
        assert empty.online is None
        assert empty.tailscaleIps is None


class TestContainerTemplatePort:
    """Tests for ContainerTemplatePort model."""

    def test_template_port_all_fields(self) -> None:
        """Test ContainerTemplatePort with all fields."""
        from unraid_api.models import ContainerTemplatePort

        port = ContainerTemplatePort(
            ip="0.0.0.0",
            privatePort=8080,
            publicPort=8080,
            type="tcp",
        )

        assert port.ip == "0.0.0.0"
        assert port.privatePort == 8080
        assert port.publicPort == 8080
        assert port.type == "tcp"


class TestContainerUpdateStatus:
    """Tests for ContainerUpdateStatus model."""

    def test_update_status_up_to_date(self) -> None:
        """Test ContainerUpdateStatus for an up-to-date container."""
        from unraid_api.models import ContainerUpdateStatus

        status = ContainerUpdateStatus(
            name="plex",
            updateStatus="UP_TO_DATE",
        )

        assert status.name == "plex"
        assert status.updateStatus == "UP_TO_DATE"

    def test_update_status_update_available(self) -> None:
        """Test ContainerUpdateStatus for a container with available update."""
        from unraid_api.models import ContainerUpdateStatus

        status = ContainerUpdateStatus(
            name="sonarr",
            updateStatus="UPDATE_AVAILABLE",
        )

        assert status.name == "sonarr"
        assert status.updateStatus == "UPDATE_AVAILABLE"


class TestUPSConfiguration:
    """Tests for UPSConfiguration model."""

    def test_ups_config_all_fields(self) -> None:
        """Test UPSConfiguration with all fields."""
        from unraid_api.models import UPSConfiguration

        config = UPSConfiguration(
            service=None,
            upsCable="usb",
            customUpsCable=None,
            upsType=None,
            device=None,
            overrideUpsCapacity=False,
            batteryLevel=10,
            minutes=5,
            timeout=0,
            killUps=False,
            nisIp="",
            netServer=None,
            upsName="ups",
            modelName=None,
        )

        assert config.upsCable == "usb"
        assert config.batteryLevel == 10
        assert config.minutes == 5
        assert config.killUps is False
        assert config.upsName == "ups"

    def test_ups_config_defaults(self) -> None:
        """Test UPSConfiguration with default values."""
        from unraid_api.models import UPSConfiguration

        config = UPSConfiguration()

        assert config.service is None
        assert config.upsCable is None
        assert config.batteryLevel is None


class TestDisplaySettings:
    """Tests for DisplaySettings model."""

    def test_display_settings_all_fields(self) -> None:
        """Test DisplaySettings with all fields."""
        from unraid_api.models import DisplaySettings

        settings = DisplaySettings(
            theme="white",
            unit="CELSIUS",
            scale=False,
            tabs=True,
            resize=False,
            wwn=False,
            total=True,
            usage=False,
            text=False,
            warning=70,
            critical=90,
            hot=45,
            max=55,
            locale="en_US",
        )

        assert settings.theme == "white"
        assert settings.unit == "CELSIUS"
        assert settings.scale is False
        assert settings.tabs is True
        assert settings.warning == 70
        assert settings.critical == 90
        assert settings.hot == 45
        assert settings.max == 55
        assert settings.locale == "en_US"

    def test_display_settings_defaults(self) -> None:
        """Test DisplaySettings with default values."""
        from unraid_api.models import DisplaySettings

        settings = DisplaySettings()

        assert settings.theme is None
        assert settings.unit is None
        assert settings.warning is None


class TestDockerPortConflicts:
    """Tests for DockerPortConflicts models."""

    def test_port_conflicts_with_data(self) -> None:
        """Test DockerPortConflicts with conflict data."""
        from unraid_api.models import (
            DockerLanPortConflict,
            DockerPortConflictContainer,
            DockerPortConflicts,
        )

        conflicts = DockerPortConflicts(
            lanPorts=[
                DockerLanPortConflict(
                    containers=[
                        DockerPortConflictContainer(name="container-a"),
                        DockerPortConflictContainer(name="container-b"),
                    ]
                )
            ]
        )

        assert len(conflicts.lanPorts) == 1
        assert len(conflicts.lanPorts[0].containers) == 2
        assert conflicts.lanPorts[0].containers[0].name == "container-a"

    def test_port_conflicts_empty(self) -> None:
        """Test DockerPortConflicts with no conflicts."""
        from unraid_api.models import DockerPortConflicts

        conflicts = DockerPortConflicts()

        assert conflicts.lanPorts == []


class TestKeyFile:
    """Tests for KeyFile model."""

    def test_key_file_with_data(self) -> None:
        """Test KeyFile with location and contents."""
        from unraid_api.models import KeyFile

        key_file = KeyFile(
            location="/boot/config/Plus.key",
            contents="--- KEY FILE CONTENTS ---",
        )

        assert key_file.location == "/boot/config/Plus.key"
        assert key_file.contents == "--- KEY FILE CONTENTS ---"

    def test_key_file_defaults(self) -> None:
        """Test KeyFile with default values."""
        from unraid_api.models import KeyFile

        key_file = KeyFile()

        assert key_file.location is None
        assert key_file.contents is None


class TestExtendedArrayDisk:
    """Tests for new ArrayDisk fields (v4.30.0)."""

    def test_disk_with_extended_fields(self) -> None:
        """Test ArrayDisk with new v4.30.0 fields."""
        disk = ArrayDisk(
            id="disk:1",
            idx=1,
            name="Disk 1",
            rotational=True,
            numReads=123456,
            numWrites=78901,
            numErrors=0,
            warning=40,
            critical=50,
            color="green-on",
            format="MBR: 4KiB-aligned",
            transport="sata",
            comment="Main storage",
            exportable=True,
        )

        assert disk.rotational is True
        assert disk.numReads == 123456
        assert disk.numWrites == 78901
        assert disk.numErrors == 0
        assert disk.warning == 40
        assert disk.critical == 50
        assert disk.color == "green-on"
        assert disk.format == "MBR: 4KiB-aligned"
        assert disk.transport == "sata"
        assert disk.comment == "Main storage"
        assert disk.exportable is True

    def test_disk_extended_fields_default_none(self) -> None:
        """Test new fields default to None."""
        disk = ArrayDisk(id="disk:1")

        assert disk.rotational is None
        assert disk.numReads is None
        assert disk.numWrites is None
        assert disk.numErrors is None
        assert disk.warning is None
        assert disk.critical is None
        assert disk.color is None
        assert disk.format is None
        assert disk.transport is None
        assert disk.comment is None
        assert disk.exportable is None


class TestExtendedShare:
    """Tests for new Share fields (v4.30.0)."""

    def test_share_with_extended_fields(self) -> None:
        """Test Share with new v4.30.0 fields."""
        share = Share(
            id="share:appdata",
            name="appdata",
            size=1000,
            used=400,
            free=600,
            cache="prefer",
            include=["disk1", "disk2"],
            exclude=["disk3"],
            nameOrig="appdata",
            allocator="highwater",
            splitLevel="0",
            floor="0",
            cow="auto",
            color="green-on",
            luksStatus="0",
        )

        assert share.cache == "prefer"
        assert share.include == ["disk1", "disk2"]
        assert share.exclude == ["disk3"]
        assert share.nameOrig == "appdata"
        assert share.allocator == "highwater"
        assert share.splitLevel == "0"
        assert share.floor == "0"
        assert share.cow == "auto"
        assert share.color == "green-on"
        assert share.luksStatus == "0"

    def test_share_extended_fields_default_none(self) -> None:
        """Test new share fields default to None."""
        share = Share(id="share:test", name="test")

        assert share.cache is None
        assert share.include is None
        assert share.exclude is None
        assert share.nameOrig is None
        assert share.allocator is None


class TestDockerContainerStats:
    """Tests for DockerContainerStats model (subscription-only)."""

    def test_stats_with_all_fields(self) -> None:
        """Test DockerContainerStats with all fields populated."""
        from unraid_api.models import DockerContainerStats

        stats = DockerContainerStats(
            id="container:abc123",
            cpuPercent=15.3,
            memUsage="256MB / 2GB",
            memPercent=12.5,
            netIO="1.2GB / 500MB",
            blockIO="50MB / 100MB",
        )
        assert stats.id == "container:abc123"
        assert stats.cpuPercent == 15.3
        assert stats.memUsage == "256MB / 2GB"
        assert stats.memPercent == 12.5
        assert stats.netIO == "1.2GB / 500MB"
        assert stats.blockIO == "50MB / 100MB"

    def test_stats_defaults_none(self) -> None:
        """Test DockerContainerStats defaults to None."""
        from unraid_api.models import DockerContainerStats

        stats = DockerContainerStats()
        assert stats.id is None
        assert stats.cpuPercent is None
        assert stats.memUsage is None
        assert stats.memPercent is None
        assert stats.netIO is None
        assert stats.blockIO is None


class TestExtendedDockerContainer:
    """Tests for new DockerContainer fields (v4.30.0)."""

    def test_container_with_extended_fields(self) -> None:
        """Test DockerContainer with new v4.30.0 fields."""
        from unraid_api.models import ContainerTemplatePort, TailscaleStatus

        container = DockerContainer(
            id="container:abc123",
            name="plex",
            state="RUNNING",
            sizeRw=1024,
            sizeLog=512,
            autoStartOrder=1,
            autoStartWait=5,
            shell="bash",
            templatePath="/boot/config/plugins/dockerMan/templates-user/my-plex.xml",
            projectUrl="https://plex.tv",
            registryUrl="https://hub.docker.com/r/plexinc/pms-docker",
            supportUrl="https://forums.plex.tv",
            tailscaleEnabled=True,
            tailscaleStatus=TailscaleStatus(
                hostname="plex",
                dnsName="plex.tail12345.ts.net.",
                online=True,
            ),
            isRebuildReady=False,
            templatePorts=[
                ContainerTemplatePort(
                    ip="0.0.0.0", privatePort=32400, publicPort=32400, type="tcp"
                )
            ],
            lanIpPorts=["32400/tcp"],
        )

        assert container.sizeRw == 1024
        assert container.sizeLog == 512
        assert container.autoStartOrder == 1
        assert container.autoStartWait == 5
        assert container.shell == "bash"
        assert container.templatePath is not None
        assert container.projectUrl == "https://plex.tv"
        assert container.tailscaleEnabled is True
        assert container.tailscaleStatus is not None
        assert container.tailscaleStatus.hostname == "plex"
        assert container.tailscaleStatus.online is True
        assert container.isRebuildReady is False
        assert container.templatePorts is not None
        assert len(container.templatePorts) == 1
        assert container.lanIpPorts == ["32400/tcp"]

    def test_from_api_response_with_extended_fields(self) -> None:
        """Test from_api_response with new v4.30.0 fields."""
        data = {
            "id": "container:abc123",
            "names": ["/plex"],
            "state": "RUNNING",
            "status": "Up 5 days",
            "image": "plexinc/pms-docker:latest",
            "imageId": "sha256:abc",
            "autoStart": True,
            "sizeRw": 2048,
            "sizeLog": 1024,
            "autoStartOrder": 2,
            "autoStartWait": 10,
            "shell": "sh",
            "templatePath": "/path/to/template.xml",
            "projectUrl": "https://project.example.com",
            "registryUrl": "https://registry.example.com",
            "supportUrl": "https://support.example.com",
            "tailscaleEnabled": False,
            "tailscaleStatus": None,
            "isRebuildReady": True,
            "templatePorts": [
                {
                    "ip": "0.0.0.0",
                    "privatePort": 8080,
                    "publicPort": 8080,
                    "type": "tcp",
                }
            ],
            "lanIpPorts": ["8080/tcp", "443/tcp"],
            "ports": [],
        }

        container = DockerContainer.from_api_response(data)

        assert container.name == "plex"
        assert container.sizeRw == 2048
        assert container.sizeLog == 1024
        assert container.autoStartOrder == 2
        assert container.autoStartWait == 10
        assert container.shell == "sh"
        assert container.tailscaleEnabled is False
        assert container.tailscaleStatus is None
        assert container.isRebuildReady is True
        assert container.templatePorts is not None
        assert len(container.templatePorts) == 1
        assert container.templatePorts[0].privatePort == 8080
        assert container.lanIpPorts == ["8080/tcp", "443/tcp"]

    def test_from_api_response_with_tailscale_status(self) -> None:
        """Test from_api_response with tailscale status data."""
        data = {
            "id": "container:abc123",
            "names": ["/test"],
            "tailscaleEnabled": True,
            "tailscaleStatus": {
                "hostname": "my-container",
                "dnsName": "my-container.ts.net.",
                "online": True,
            },
            "ports": [],
        }

        container = DockerContainer.from_api_response(data)

        assert container.tailscaleEnabled is True
        assert container.tailscaleStatus is not None
        assert container.tailscaleStatus.hostname == "my-container"
        assert container.tailscaleStatus.online is True


class TestExtendedRegistration:
    """Tests for new Registration fields (v4.30.0)."""

    def test_registration_with_key_file(self) -> None:
        """Test Registration with keyFile field."""
        from unraid_api.models import KeyFile, Registration

        reg = Registration(
            id="reg:1",
            type="Pro",
            state="valid",
            keyFile=KeyFile(
                location="/boot/config/Pro.key",
                contents="key contents here",
            ),
        )

        assert reg.type == "Pro"
        assert reg.keyFile is not None
        assert reg.keyFile.location == "/boot/config/Pro.key"

    def test_registration_key_file_default_none(self) -> None:
        """Test Registration keyFile defaults to None."""
        from unraid_api.models import Registration

        reg = Registration(id="reg:1")

        assert reg.keyFile is None


class TestExtendedUnraidArray:
    """Tests for new UnraidArray fields (v4.30.0)."""

    def test_array_with_boot_devices(self) -> None:
        """Test UnraidArray with bootDevices field."""
        array = UnraidArray(
            state="STARTED",
            capacity=ArrayCapacity(),
            bootDevices=[
                ArrayDisk(id="boot:1", name="Boot Device 1"),
            ],
        )

        assert len(array.bootDevices) == 1
        assert array.bootDevices[0].name == "Boot Device 1"

    def test_array_boot_devices_default_empty(self) -> None:
        """Test UnraidArray bootDevices defaults to empty list."""
        array = UnraidArray(capacity=ArrayCapacity())

        assert array.bootDevices == []


class TestExtendedVars:
    """Tests for new Vars fields (v4.30.0)."""

    def test_vars_with_new_fields(self) -> None:
        """Test Vars with new v4.30.0 fields."""
        from unraid_api.models import Vars

        vars_data = Vars(
            sbVersion="1.0",
            joinStatus="JOINED",
            pollAttributesStatus="ACTIVE",
        )

        assert vars_data.sb_version == "1.0"
        assert vars_data.join_status == "JOINED"
        assert vars_data.poll_attributes_status == "ACTIVE"

    def test_vars_new_fields_default_none(self) -> None:
        """Test new Vars fields default to None."""
        from unraid_api.models import Vars

        vars_data = Vars()

        assert vars_data.sb_version is None
        assert vars_data.join_status is None
        assert vars_data.poll_attributes_status is None


class TestCpuMetrics:
    """Tests for CpuMetrics and CpuCore subscription models."""

    def test_cpu_metrics_with_all_fields(self) -> None:
        """Test CpuMetrics with cores."""
        from unraid_api.models import CpuCore, CpuMetrics

        metrics = CpuMetrics(
            percentTotal=45.2,
            cpus=[CpuCore(percentTotal=50.0), CpuCore(percentTotal=40.4)],
        )
        assert metrics.percentTotal == 45.2
        assert len(metrics.cpus) == 2
        assert metrics.cpus[0].percentTotal == 50.0
        assert metrics.cpus[1].percentTotal == 40.4

    def test_cpu_metrics_defaults(self) -> None:
        """Test CpuMetrics defaults."""
        from unraid_api.models import CpuMetrics

        metrics = CpuMetrics()
        assert metrics.percentTotal is None
        assert metrics.cpus == []

    def test_cpu_core_defaults(self) -> None:
        """Test CpuCore defaults."""
        from unraid_api.models import CpuCore

        core = CpuCore()
        assert core.percentTotal is None


class TestCpuTelemetryMetrics:
    """Tests for CpuTelemetryMetrics subscription model."""

    def test_telemetry_with_all_fields(self) -> None:
        """Test CpuTelemetryMetrics with all fields."""
        from unraid_api.models import CpuTelemetryMetrics

        metrics = CpuTelemetryMetrics(totalPower=125.5, power=110.0, temp=65.0)
        assert metrics.totalPower == 125.5
        assert metrics.power == 110.0
        assert metrics.temp == 65.0

    def test_telemetry_defaults(self) -> None:
        """Test CpuTelemetryMetrics defaults."""
        from unraid_api.models import CpuTelemetryMetrics

        metrics = CpuTelemetryMetrics()
        assert metrics.totalPower is None
        assert metrics.power is None
        assert metrics.temp is None

    def test_telemetry_with_list_values(self) -> None:
        """Test CpuTelemetryMetrics with list values (real server format)."""
        from unraid_api.models import CpuTelemetryMetrics

        metrics = CpuTelemetryMetrics(totalPower=125.5, power=[0.7], temp=[35])
        assert metrics.totalPower == 125.5
        assert metrics.power == [0.7]
        assert metrics.temp == [35]


class TestMemoryMetrics:
    """Tests for MemoryMetrics subscription model."""

    def test_memory_metrics_with_all_fields(self) -> None:
        """Test MemoryMetrics with all fields."""
        from unraid_api.models import MemoryMetrics

        metrics = MemoryMetrics(
            total=16777216, used=8388608, free=8388608, percentTotal=50.0
        )
        assert metrics.total == 16777216
        assert metrics.used == 8388608
        assert metrics.free == 8388608
        assert metrics.percentTotal == 50.0

    def test_memory_metrics_defaults(self) -> None:
        """Test MemoryMetrics defaults."""
        from unraid_api.models import MemoryMetrics

        metrics = MemoryMetrics()
        assert metrics.total is None
        assert metrics.used is None
        assert metrics.free is None
        assert metrics.percentTotal is None


class TestArraySubscriptionUpdate:
    """Tests for ArraySubscriptionUpdate subscription model."""

    def test_update_with_all_fields(self) -> None:
        """Test ArraySubscriptionUpdate with capacity."""
        from unraid_api.models import (
            ArrayCapacity,
            ArraySubscriptionUpdate,
            CapacityKilobytes,
        )

        update = ArraySubscriptionUpdate(
            state="STARTED",
            capacity=ArrayCapacity(
                kilobytes=CapacityKilobytes(total=1000000, used=500000, free=500000)
            ),
        )
        assert update.state == "STARTED"
        assert update.capacity is not None
        assert update.capacity.kilobytes.total == 1000000

    def test_update_defaults(self) -> None:
        """Test ArraySubscriptionUpdate defaults."""
        from unraid_api.models import ArraySubscriptionUpdate

        update = ArraySubscriptionUpdate()
        assert update.state is None
        assert update.capacity is None


# =============================================================================
# Issue #38: Missing Memory Fields Tests
# =============================================================================


class TestMemoryUtilizationExtended:
    """Tests for extended MemoryUtilization fields (active, buffcache, swapFree)."""

    def test_memory_utilization_new_fields(self) -> None:
        """Test MemoryUtilization includes active, buffcache, and swapFree."""
        from unraid_api.models import MemoryUtilization

        mem = MemoryUtilization(
            total=33328332800,
            used=31918235648,
            free=1410097152,
            available=27213021184,
            active=6115311616,
            buffcache=28791951360,
            percentTotal=18.35,
            swapTotal=0,
            swapUsed=0,
            swapFree=0,
            percentSwapTotal=0.0,
        )

        assert mem.active == 6115311616
        assert mem.buffcache == 28791951360
        assert mem.swapFree == 0

    def test_memory_utilization_backward_compat(self) -> None:
        """Test MemoryUtilization works without new fields (backward compat)."""
        from unraid_api.models import MemoryUtilization

        mem = MemoryUtilization(
            total=33328332800,
            used=31918235648,
            free=1410097152,
            available=27213021184,
            percentTotal=18.35,
            swapTotal=0,
            swapUsed=0,
            percentSwapTotal=0.0,
        )

        assert mem.active is None
        assert mem.buffcache is None
        assert mem.swapFree is None

    def test_system_metrics_new_memory_fields(self) -> None:
        """Test SystemMetrics includes new memory fields from from_response."""
        from unraid_api.models import SystemMetrics

        response = {
            "metrics": {
                "cpu": {"percentTotal": 25.0},
                "memory": {
                    "total": 33328332800,
                    "used": 31918235648,
                    "free": 1410097152,
                    "available": 27213021184,
                    "active": 6115311616,
                    "buffcache": 28791951360,
                    "percentTotal": 18.35,
                    "swapTotal": 8589934592,
                    "swapUsed": 100000000,
                    "swapFree": 8489934592,
                    "percentSwapTotal": 1.2,
                },
            },
            "info": {
                "os": {"uptime": "2024-01-15T10:30:00Z"},
                "cpu": {"packages": {"temp": [55.0], "totalPower": 65.5}},
            },
        }

        metrics = SystemMetrics.from_response(response)

        assert metrics.memory_active == 6115311616
        assert metrics.memory_buffcache == 28791951360
        assert metrics.swap_free == 8489934592

    def test_system_metrics_missing_new_memory_fields(self) -> None:
        """Test SystemMetrics from_response with missing new fields."""
        from unraid_api.models import SystemMetrics

        response = {
            "metrics": {
                "cpu": {"percentTotal": 10.0},
                "memory": {
                    "total": 33328332800,
                    "used": 31918235648,
                    "percentTotal": 18.35,
                },
            },
        }

        metrics = SystemMetrics.from_response(response)

        assert metrics.memory_active is None
        assert metrics.memory_buffcache is None
        assert metrics.swap_free is None


# =============================================================================
# Issue #37: Temperature Models Tests
# =============================================================================


class TestTemperatureEnums:
    """Tests for temperature enum types."""

    def test_sensor_type_values(self) -> None:
        """Test SensorType enum values."""
        from unraid_api.models import SensorType

        assert SensorType.CPU_PACKAGE == "CPU_PACKAGE"
        assert SensorType.DISK == "DISK"
        assert SensorType.NVME == "NVME"
        assert SensorType.CUSTOM == "CUSTOM"

    def test_temperature_unit_values(self) -> None:
        """Test TemperatureUnit enum values."""
        from unraid_api.models import TemperatureUnit

        assert TemperatureUnit.CELSIUS == "CELSIUS"
        assert TemperatureUnit.FAHRENHEIT == "FAHRENHEIT"

    def test_temperature_status_values(self) -> None:
        """Test TemperatureStatus enum values."""
        from unraid_api.models import TemperatureStatus

        assert TemperatureStatus.NORMAL == "NORMAL"
        assert TemperatureStatus.WARNING == "WARNING"
        assert TemperatureStatus.CRITICAL == "CRITICAL"
        assert TemperatureStatus.UNKNOWN == "UNKNOWN"


class TestTemperatureReading:
    """Tests for TemperatureReading model."""

    def test_reading_with_all_fields(self) -> None:
        """Test TemperatureReading with all fields."""
        from unraid_api.models import TemperatureReading

        reading = TemperatureReading(value=45.0, unit="CELSIUS", status="NORMAL")

        assert reading.value == 45.0
        assert reading.unit == "CELSIUS"
        assert reading.status == "NORMAL"

    def test_reading_defaults(self) -> None:
        """Test TemperatureReading defaults to None."""
        from unraid_api.models import TemperatureReading

        reading = TemperatureReading()

        assert reading.value is None
        assert reading.unit is None
        assert reading.status is None


class TestTemperatureSensor:
    """Tests for TemperatureSensor model."""

    def test_sensor_full_data(self) -> None:
        """Test TemperatureSensor with complete data."""
        from unraid_api.models import TemperatureReading, TemperatureSensor

        sensor = TemperatureSensor(
            id="disk:WKD07FR0",
            name="ST8000VN004-2M2101",
            type="DISK",
            location=None,
            current=TemperatureReading(value=30.0, unit="CELSIUS", status="NORMAL"),
            min=TemperatureReading(value=28.0, unit="CELSIUS"),
            max=TemperatureReading(value=35.0, unit="CELSIUS"),
            warning=50,
            critical=60,
        )

        assert sensor.id == "disk:WKD07FR0"
        assert sensor.name == "ST8000VN004-2M2101"
        assert sensor.type == "DISK"
        assert sensor.temperature == 30.0
        assert sensor.is_critical is False
        assert sensor.is_warning is False
        assert sensor.warning == 50
        assert sensor.critical == 60

    def test_sensor_critical_status(self) -> None:
        """Test TemperatureSensor is_critical property."""
        from unraid_api.models import TemperatureReading, TemperatureSensor

        sensor = TemperatureSensor(
            id="cpu:0",
            current=TemperatureReading(value=95.0, unit="CELSIUS", status="CRITICAL"),
        )

        assert sensor.is_critical is True
        assert sensor.is_warning is False

    def test_sensor_warning_status(self) -> None:
        """Test TemperatureSensor is_warning property."""
        from unraid_api.models import TemperatureReading, TemperatureSensor

        sensor = TemperatureSensor(
            id="cpu:0",
            current=TemperatureReading(value=75.0, unit="CELSIUS", status="WARNING"),
        )

        assert sensor.is_critical is False
        assert sensor.is_warning is True

    def test_sensor_no_current_reading(self) -> None:
        """Test TemperatureSensor with no current reading."""
        from unraid_api.models import TemperatureSensor

        sensor = TemperatureSensor(id="test:1")

        assert sensor.temperature is None
        assert sensor.is_critical is False
        assert sensor.is_warning is False


class TestTemperatureMetrics:
    """Tests for TemperatureMetrics model."""

    def test_metrics_with_sensors(self) -> None:
        """Test TemperatureMetrics with summary and sensors."""
        from unraid_api.models import (
            TemperatureMetrics,
            TemperatureReading,
            TemperatureSensor,
            TemperatureSensorSummary,
            TemperatureSummary,
        )

        metrics = TemperatureMetrics(
            id="temp:1",
            summary=TemperatureSummary(
                average=35.0,
                hottest=TemperatureSensorSummary(
                    name="CPU",
                    current=TemperatureReading(value=55.0, unit="CELSIUS"),
                ),
                coolest=TemperatureSensorSummary(
                    name="SSD",
                    current=TemperatureReading(value=25.0, unit="CELSIUS"),
                ),
                warningCount=0,
                criticalCount=0,
            ),
            sensors=[
                TemperatureSensor(
                    id="cpu:0",
                    name="CPU Package",
                    type="CPU_PACKAGE",
                    current=TemperatureReading(
                        value=55.0, unit="CELSIUS", status="NORMAL"
                    ),
                ),
                TemperatureSensor(
                    id="disk:1",
                    name="ST8000VN004",
                    type="DISK",
                    current=TemperatureReading(
                        value=30.0, unit="CELSIUS", status="NORMAL"
                    ),
                ),
                TemperatureSensor(
                    id="nvme:1",
                    name="Samsung 970 EVO",
                    type="NVME",
                    current=TemperatureReading(
                        value=35.0, unit="CELSIUS", status="NORMAL"
                    ),
                ),
            ],
        )

        assert metrics.id == "temp:1"
        assert metrics.summary is not None
        # Summary is recomputed from the sensors: (55 + 30 + 35) / 3 = 40.0
        assert metrics.summary.average == 40.0
        assert metrics.summary.warningCount == 0
        assert metrics.summary.criticalCount == 0
        assert metrics.summary.hottest is not None
        assert metrics.summary.hottest.name == "CPU Package"
        assert metrics.summary.coolest is not None
        assert metrics.summary.coolest.name == "ST8000VN004"
        assert len(metrics.sensors) == 3

    def test_sensor_type_filtering(self) -> None:
        """Test filtering sensors by type."""
        from unraid_api.models import (
            TemperatureMetrics,
            TemperatureReading,
            TemperatureSensor,
        )

        metrics = TemperatureMetrics(
            sensors=[
                TemperatureSensor(
                    id="cpu:0",
                    type="CPU_PACKAGE",
                    current=TemperatureReading(value=55.0),
                ),
                TemperatureSensor(
                    id="cpu:1",
                    type="CPU_CORE",
                    current=TemperatureReading(value=50.0),
                ),
                TemperatureSensor(
                    id="disk:0",
                    type="DISK",
                    current=TemperatureReading(value=30.0),
                ),
                TemperatureSensor(
                    id="nvme:0",
                    type="NVME",
                    current=TemperatureReading(value=35.0),
                ),
                TemperatureSensor(
                    id="custom:0",
                    type="CUSTOM",
                    current=TemperatureReading(value=1.0),
                ),
            ],
        )

        assert len(metrics.disk_sensors) == 1
        assert len(metrics.nvme_sensors) == 1
        assert len(metrics.cpu_sensors) == 2
        assert len(metrics.get_sensors_by_type("CUSTOM")) == 1

    def test_metrics_defaults(self) -> None:
        """Test TemperatureMetrics with default values."""
        from unraid_api.models import TemperatureMetrics

        metrics = TemperatureMetrics()

        assert metrics.id is None
        assert metrics.summary is None
        assert metrics.sensors == []
        assert metrics.disk_sensors == []
        assert metrics.nvme_sensors == []
        assert metrics.cpu_sensors == []

    def test_temperature_in_system_metrics(self) -> None:
        """Test temperature data is included in SystemMetrics.from_response."""
        from unraid_api.models import SystemMetrics

        response = {
            "metrics": {
                "cpu": {"percentTotal": 25.0},
                "memory": {"percentTotal": 50.0},
                "temperature": {
                    "id": "temp:1",
                    "summary": {
                        "average": 40.0,
                        "warningCount": 0,
                        "criticalCount": 0,
                    },
                    "sensors": [
                        {
                            "id": "disk:1",
                            "name": "ST8000VN004",
                            "type": "DISK",
                            "current": {
                                "value": 30.0,
                                "unit": "CELSIUS",
                                "status": "NORMAL",
                            },
                            "warning": 50,
                            "critical": 60,
                        }
                    ],
                },
            },
            "info": {
                "cpu": {"packages": {"temp": [55.0], "totalPower": 65.5}},
            },
        }

        metrics = SystemMetrics.from_response(response)

        assert metrics.temperature is not None
        assert metrics.temperature.id == "temp:1"
        assert len(metrics.temperature.sensors) == 1
        assert metrics.temperature.sensors[0].name == "ST8000VN004"
        assert metrics.temperature.sensors[0].temperature == 30.0
        assert metrics.temperature.summary is not None
        # Summary is recomputed from the one visible sensor (30.0 °C).
        assert metrics.temperature.summary.average == 30.0

    def test_temperature_missing_from_response(self) -> None:
        """Test SystemMetrics.from_response with no temperature data."""
        from unraid_api.models import SystemMetrics

        response = {
            "metrics": {
                "cpu": {"percentTotal": 25.0},
                "memory": {"percentTotal": 50.0},
            },
        }

        metrics = SystemMetrics.from_response(response)

        assert metrics.temperature is None

    def test_temperature_from_live_response(self) -> None:
        """Test temperature models parse a realistic API response."""
        from unraid_api.models import TemperatureMetrics

        # Realistic data based on actual Unraid API response
        data = {
            "id": "abc123:temperature-metrics",
            "summary": {
                "average": 35.5,
                "hottest": {
                    "name": "CPU Package",
                    "current": {"value": 55.0, "unit": "CELSIUS"},
                },
                "coolest": {
                    "name": "NVMe SSD",
                    "current": {"value": 29.0, "unit": "CELSIUS"},
                },
                "warningCount": 0,
                "criticalCount": 0,
            },
            "sensors": [
                {
                    "id": "disk:WKD07FR0",
                    "name": "ST8000VN004-2M2101",
                    "type": "DISK",
                    "location": None,
                    "current": {
                        "value": 30.0,
                        "unit": "CELSIUS",
                        "status": "NORMAL",
                    },
                    "min": {"value": 30.0, "unit": "CELSIUS"},
                    "max": {"value": 30.0, "unit": "CELSIUS"},
                    "warning": 50,
                    "critical": 60,
                },
                {
                    "id": "disk:A240910N4M051200021",
                    "name": "SPCC M.2 PCIe SSD",
                    "type": "NVME",
                    "location": None,
                    "current": {
                        "value": 29.0,
                        "unit": "CELSIUS",
                        "status": "NORMAL",
                    },
                    "min": {"value": 29.0, "unit": "CELSIUS"},
                    "max": {"value": 29.0, "unit": "CELSIUS"},
                    "warning": 50,
                    "critical": 60,
                },
            ],
        }

        metrics = TemperatureMetrics(**data)

        assert len(metrics.sensors) == 2
        assert metrics.sensors[0].name == "ST8000VN004-2M2101"
        assert metrics.sensors[0].type == "DISK"
        assert metrics.sensors[0].temperature == 30.0
        assert metrics.sensors[1].type == "NVME"
        assert len(metrics.disk_sensors) == 1
        assert len(metrics.nvme_sensors) == 1
        assert metrics.summary is not None
        # Summary recomputed from visible sensors: (30 + 29) / 2 = 29.5
        assert metrics.summary.average == 29.5
        assert metrics.summary.hottest is not None
        assert metrics.summary.hottest.name == "ST8000VN004-2M2101"
        assert metrics.summary.coolest is not None
        assert metrics.summary.coolest.name == "SPCC M.2 PCIe SSD"


class TestTemperatureBogusSensorFiltering:
    """Bogus sensor filtering and summary recomputation.

    The Unraid API occasionally surfaces voltage rails, fan tachometers,
    and disconnected PECI/TSI pins inside its temperature metrics. These
    must be filtered out so downstream consumers (like the Home Assistant
    integration) never see nonsense values such as 3,892,313 °C or a
    530,831 °C "average".
    """

    def _sensor(
        self,
        *,
        id: str,
        name: str | None = None,
        value: float | None,
        sensor_type: str = "CUSTOM",
        status: str = "NORMAL",
    ):
        from unraid_api.models import TemperatureReading, TemperatureSensor

        return TemperatureSensor(
            id=id,
            name=name,
            type=sensor_type,
            current=TemperatureReading(value=value, unit="CELSIUS", status=status),
        )

    def test_filters_voltage_rail_sensors(self) -> None:
        """Sensors named like 'nct6793 in0' are voltage rails, not temps."""
        from unraid_api.models import TemperatureMetrics

        metrics = TemperatureMetrics(
            sensors=[
                self._sensor(
                    id="nct6793-isa-0290:in0:in0_input",
                    name="nct6793-isa-0290 in0",
                    value=0.63,
                ),
                self._sensor(
                    id="nct6793-isa-0290:in12:in12_input",
                    name="nct6793-isa-0290 in12",
                    value=1.83,
                ),
                self._sensor(
                    id="cpu:0",
                    name="CPU Package",
                    value=45.0,
                    sensor_type="CPU_PACKAGE",
                ),
            ],
        )

        assert len(metrics.sensors) == 1
        assert metrics.sensors[0].id == "cpu:0"

    def test_filters_fan_tachometer_sensors(self) -> None:
        """Sensors named like 'Array Fan' report RPM, not temperature."""
        from unraid_api.models import TemperatureMetrics

        metrics = TemperatureMetrics(
            sensors=[
                self._sensor(
                    id="nct6793-isa-0290:Array Fan:fan5_input",
                    name="nct6793-isa-0290 Array Fan",
                    value=1478.0,
                    status="CRITICAL",
                ),
                self._sensor(
                    id="disk:1",
                    name="ST8000VN004",
                    value=42.0,
                    sensor_type="DISK",
                ),
            ],
        )

        assert len(metrics.sensors) == 1
        assert metrics.sensors[0].id == "disk:1"

    def test_filters_out_of_range_values(self) -> None:
        """Values far outside the plausible temperature range are bogus."""
        from unraid_api.models import TemperatureMetrics

        metrics = TemperatureMetrics(
            sensors=[
                self._sensor(
                    id="nct6793:TSI7_TEMP:temp20_input",
                    name="nct6793-isa-0290 TSI7_TEMP",
                    value=3892313.99,
                    status="CRITICAL",
                ),
                self._sensor(
                    id="nct6793:SYSTIN:temp1_input",
                    name="nct6793-isa-0290 SYSTIN",
                    value=115.0,
                    status="CRITICAL",
                ),
                self._sensor(
                    id="nct6793:AUXTIN1:temp4_input",
                    name="nct6793-isa-0290 AUXTIN1",
                    value=108.0,
                    status="CRITICAL",
                ),
                self._sensor(
                    id="cpu:0",
                    name="CPU Package",
                    value=55.0,
                    sensor_type="CPU_PACKAGE",
                ),
            ],
        )

        kept_ids = {s.id for s in metrics.sensors}
        assert kept_ids == {"cpu:0"}

    def test_filters_non_finite_values(self) -> None:
        """NaN and infinity are never plausible temperature readings."""
        from unraid_api.models import TemperatureMetrics

        metrics = TemperatureMetrics(
            sensors=[
                self._sensor(id="bad:nan", name="bad nan", value=float("nan")),
                self._sensor(id="bad:inf", name="bad inf", value=float("inf")),
                self._sensor(
                    id="cpu:0",
                    name="CPU Package",
                    value=50.0,
                    sensor_type="CPU_PACKAGE",
                ),
            ],
        )

        assert [s.id for s in metrics.sensors] == ["cpu:0"]

    def test_keeps_sensor_with_missing_current(self) -> None:
        """Sensors with no current reading are not filtered as bogus."""
        from unraid_api.models import TemperatureMetrics, TemperatureSensor

        metrics = TemperatureMetrics(
            sensors=[
                TemperatureSensor(id="disk:standby", name="Sleeping disk"),
                self._sensor(
                    id="cpu:0",
                    name="CPU Package",
                    value=50.0,
                    sensor_type="CPU_PACKAGE",
                ),
            ],
        )

        kept_ids = {s.id for s in metrics.sensors}
        assert kept_ids == {"disk:standby", "cpu:0"}

    def test_summary_recomputed_after_filtering(self) -> None:
        """Server-provided bogus summary must be replaced with accurate values."""
        from unraid_api.models import (
            TemperatureMetrics,
            TemperatureReading,
            TemperatureSensorSummary,
            TemperatureSummary,
        )

        metrics = TemperatureMetrics(
            summary=TemperatureSummary(
                average=530831.433409091,
                hottest=TemperatureSensorSummary(
                    name="nct6793-isa-0290 TSI7_TEMP",
                    current=TemperatureReading(value=3892313.99, unit="CELSIUS"),
                ),
                coolest=TemperatureSensorSummary(
                    name="nct6793-isa-0290 in11",
                    current=TemperatureReading(value=0.14, unit="CELSIUS"),
                ),
                warningCount=1,
                criticalCount=11,
            ),
            sensors=[
                self._sensor(
                    id="nct6793:in0:in0_input",
                    name="nct6793-isa-0290 in0",
                    value=0.63,
                ),
                self._sensor(
                    id="nct6793:TSI7_TEMP:temp20_input",
                    name="nct6793-isa-0290 TSI7_TEMP",
                    value=3892313.99,
                    status="CRITICAL",
                ),
                self._sensor(
                    id="cpu:0",
                    name="CPU Package",
                    value=50.0,
                    sensor_type="CPU_PACKAGE",
                ),
                self._sensor(
                    id="disk:1",
                    name="Array disk",
                    value=40.0,
                    sensor_type="DISK",
                ),
                self._sensor(
                    id="disk:2",
                    name="Cache SSD",
                    value=30.0,
                    sensor_type="NVME",
                    status="WARNING",
                ),
            ],
        )

        assert len(metrics.sensors) == 3
        assert metrics.summary is not None
        assert metrics.summary.average == 40.0
        assert metrics.summary.hottest is not None
        assert metrics.summary.hottest.name == "CPU Package"
        assert metrics.summary.hottest.current is not None
        assert metrics.summary.hottest.current.value == 50.0
        assert metrics.summary.coolest is not None
        assert metrics.summary.coolest.name == "Cache SSD"
        assert metrics.summary.coolest.current is not None
        assert metrics.summary.coolest.current.value == 30.0
        assert metrics.summary.warningCount == 1
        assert metrics.summary.criticalCount == 0

    def test_summary_none_when_no_valid_sensors(self) -> None:
        """If every sensor is bogus, summary collapses to None."""
        from unraid_api.models import TemperatureMetrics

        metrics = TemperatureMetrics(
            sensors=[
                self._sensor(
                    id="nct6793:in0:in0_input",
                    name="nct6793-isa-0290 in0",
                    value=0.5,
                ),
                self._sensor(
                    id="nct6793:TSI7_TEMP:temp20_input",
                    name="nct6793-isa-0290 TSI7_TEMP",
                    value=3892313.99,
                ),
            ],
        )

        assert metrics.sensors == []
        assert metrics.summary is None

    def test_realistic_live_response_filters_all_bogus(self) -> None:
        """End-to-end: the exact shape of the broken live response."""
        from unraid_api.models import TemperatureMetrics

        data = {
            "summary": {
                "average": 530831.433409091,
                "hottest": {
                    "name": "nct6793-isa-0290 TSI7_TEMP",
                    "current": {"value": 3892313.99, "unit": "CELSIUS"},
                },
                "coolest": {
                    "name": "nct6793-isa-0290 in11",
                    "current": {"value": 0.14, "unit": "CELSIUS"},
                },
                "warningCount": 1,
                "criticalCount": 11,
            },
            "sensors": [
                # Voltage rails
                *[
                    {
                        "id": f"nct6793-isa-0290:in{i}:in{i}_input",
                        "name": f"nct6793-isa-0290 in{i}",
                        "type": "CUSTOM",
                        "current": {
                            "value": v,
                            "unit": "CELSIUS",
                            "status": "NORMAL",
                        },
                    }
                    for i, v in enumerate(
                        [
                            0.63,
                            1.83,
                            3.44,
                            3.42,
                            0.26,
                            0.14,
                            0.8,
                            3.42,
                            3.26,
                            1.12,
                            0.16,
                            0.14,
                            1.83,
                            1.64,
                            0.19,
                        ]
                    )
                ],
                # Fan tachometer
                {
                    "id": "nct6793-isa-0290:Array Fan:fan5_input",
                    "name": "nct6793-isa-0290 Array Fan",
                    "type": "CUSTOM",
                    "current": {
                        "value": 1478.0,
                        "unit": "CELSIUS",
                        "status": "CRITICAL",
                    },
                },
                # Disconnected motherboard temps
                {
                    "id": "nct6793-isa-0290:SYSTIN:temp1_input",
                    "name": "nct6793-isa-0290 SYSTIN",
                    "type": "CUSTOM",
                    "current": {
                        "value": 115.0,
                        "unit": "CELSIUS",
                        "status": "CRITICAL",
                    },
                },
                # Bogus PECI/TSI garbage
                *[
                    {
                        "id": f"nct6793-isa-0290:TSI{i}_TEMP:temp{i}_input",
                        "name": f"nct6793-isa-0290 TSI{i}_TEMP",
                        "type": "CUSTOM",
                        "current": {
                            "value": 3892313.99,
                            "unit": "CELSIUS",
                            "status": "CRITICAL",
                        },
                    }
                    for i in range(2, 8)
                ],
                # Real sensors
                {
                    "id": "coretemp-isa-0000:Core 0:temp2_input",
                    "name": "coretemp-isa-0000 Core 0",
                    "type": "CPU_CORE",
                    "current": {
                        "value": 41.0,
                        "unit": "CELSIUS",
                        "status": "NORMAL",
                    },
                },
                {
                    "id": "nvme-pci-0100:Composite:temp1_input",
                    "name": "nvme-pci-0100 Composite",
                    "type": "NVME",
                    "current": {
                        "value": 30.0,
                        "unit": "CELSIUS",
                        "status": "NORMAL",
                    },
                },
                {
                    "id": "disk:WKD07FR0",
                    "name": "ST8000VN004-2M2101",
                    "type": "DISK",
                    "current": {
                        "value": 42.0,
                        "unit": "CELSIUS",
                        "status": "NORMAL",
                    },
                },
            ],
        }

        metrics = TemperatureMetrics(**data)

        kept_names = {s.name for s in metrics.sensors}
        assert kept_names == {
            "coretemp-isa-0000 Core 0",
            "nvme-pci-0100 Composite",
            "ST8000VN004-2M2101",
        }
        assert metrics.summary is not None
        assert metrics.summary.average is not None
        assert 30.0 <= metrics.summary.average <= 50.0
        assert metrics.summary.hottest is not None
        assert metrics.summary.hottest.name == "ST8000VN004-2M2101"
        assert metrics.summary.coolest is not None
        assert metrics.summary.coolest.name == "nvme-pci-0100 Composite"
        assert metrics.summary.warningCount == 0
        assert metrics.summary.criticalCount == 0


# =============================================================================
# Audit Fix Tests - Schema alignment verification
# =============================================================================


class TestVmDomainSchemaAlignment:
    """Verify VmDomain only has fields that exist in the GraphQL schema."""

    def test_only_schema_fields(self) -> None:
        """VmDomain exposes identity, state and the optional upstream UUID."""
        from unraid_api.models import VmDomain

        vm = VmDomain(id="vm:1", name="TestVM", state="running")
        assert vm.id == "vm:1"
        assert vm.name == "TestVM"
        assert vm.state == "running"
        assert set(VmDomain.model_fields) == {"id", "name", "state", "uuid"}
        assert vm.uuid is None
        assert VmDomain(id="vm:1", name="Test", uuid="uuid-1").uuid == "uuid-1"
        # These fields were removed as they don't exist in the schema
        assert not hasattr(VmDomain.model_fields, "memory")
        assert "memory" not in VmDomain.model_fields
        assert "vcpu" not in VmDomain.model_fields
        assert "autostart" not in VmDomain.model_fields
        assert "cpuMode" not in VmDomain.model_fields
        assert "iconUrl" not in VmDomain.model_fields
        assert "primaryGpu" not in VmDomain.model_fields

    def test_ignores_extra_fields(self) -> None:
        """VmDomain should silently ignore unknown fields."""
        from unraid_api.models import VmDomain

        vm = VmDomain(id="vm:1", name="Test", memory=1024, vcpu=2)
        assert vm.id == "vm:1"
        assert vm.name == "Test"


class TestShareComment:
    """Verify Share model includes comment field."""

    def test_comment_field(self) -> None:
        """Share should have comment field."""
        from unraid_api.models import Share

        share = Share(id="share:1", name="appdata", comment="Application data")
        assert share.comment == "Application data"

    def test_comment_default_none(self) -> None:
        """Share comment should default to None."""
        from unraid_api.models import Share

        share = Share(id="share:1", name="appdata")
        assert share.comment is None


class TestNotificationAllFields:
    """Verify Notification model has all schema fields."""

    def test_all_fields(self) -> None:
        """Notification should have link, type, and formattedTimestamp."""
        from unraid_api.models import Notification

        n = Notification(
            id="n:1",
            title="Test",
            subject="Subject",
            description="Desc",
            importance="alert",
            link="https://example.com",
            type="UNREAD",
            timestamp="2024-01-01T00:00:00Z",
            formattedTimestamp="Jan 1, 2024",
        )
        assert n.link == "https://example.com"
        assert n.type == "UNREAD"
        assert n.formattedTimestamp == "Jan 1, 2024"


class TestCpuCoreAllFields:
    """Verify CpuCore model has all per-CPU metric fields."""

    def test_all_fields(self) -> None:
        """CpuCore should have all 8 per-CPU fields."""
        from unraid_api.models import CpuCore

        core = CpuCore(
            percentTotal=50.0,
            percentUser=30.0,
            percentSystem=15.0,
            percentIdle=50.0,
            percentNice=0.5,
            percentIrq=0.1,
            percentGuest=0.0,
            percentSteal=0.0,
        )
        assert core.percentTotal == 50.0
        assert core.percentUser == 30.0
        assert core.percentSystem == 15.0
        assert core.percentIdle == 50.0
        assert core.percentNice == 0.5
        assert core.percentIrq == 0.1
        assert core.percentGuest == 0.0
        assert core.percentSteal == 0.0

    def test_defaults_none(self) -> None:
        """All CpuCore fields should default to None."""
        from unraid_api.models import CpuCore

        core = CpuCore()
        assert core.percentTotal is None
        assert core.percentUser is None
        assert core.percentNice is None
        assert core.percentIrq is None
        assert core.percentGuest is None
        assert core.percentSteal is None


class TestPhysicalDiskExtendedFields:
    """Verify PhysicalDisk model has all schema fields."""

    def test_extended_fields(self) -> None:
        """PhysicalDisk should have serialNum, firmwareRevision, partitions."""
        from unraid_api.models import DiskPartition, PhysicalDisk

        disk = PhysicalDisk(
            id="disk:1",
            device="sda",
            name="WDC WD40EFAX",
            vendor="Western Digital",
            size=4000787030016,
            serialNum="WD-WX11A12B3456",
            firmwareRevision="83.00A83",
            partitions=[
                DiskPartition(name="sda1", fsType="xfs", size=4000785088512),
            ],
        )
        assert disk.serialNum == "WD-WX11A12B3456"
        assert disk.firmwareRevision == "83.00A83"
        assert disk.partitions is not None
        assert len(disk.partitions) == 1
        assert disk.partitions[0].name == "sda1"
        assert disk.partitions[0].fsType == "xfs"

    def test_extended_fields_default_none(self) -> None:
        """Extended fields should default to None."""
        from unraid_api.models import PhysicalDisk

        disk = PhysicalDisk(id="disk:1")
        assert disk.serialNum is None
        assert disk.firmwareRevision is None
        assert disk.partitions is None


class TestExportedModels:
    """Verify newly exported models are accessible."""

    def test_disk_partition_exported(self) -> None:
        """DiskPartition should be importable from unraid_api."""
        from unraid_api import DiskPartition

        p = DiskPartition(name="sda1", fsType="xfs", size=1000)
        assert p.name == "sda1"

    def test_memory_utilization_exported(self) -> None:
        """MemoryUtilization should be importable from unraid_api."""
        from unraid_api import MemoryUtilization

        m = MemoryUtilization(
            total=16000000000, active=6000000000, buffcache=8000000000
        )
        assert m.total == 16000000000
        assert m.active == 6000000000

    def test_notification_overview_counts_exported(self) -> None:
        """NotificationOverviewCounts should be importable from unraid_api."""
        from unraid_api import NotificationOverviewCounts

        c = NotificationOverviewCounts(info=5, warning=2, alert=1, total=8)
        assert c.total == 8


class TestNetworkModels:
    """Network and AccessUrl models reflect the Unraid GraphQL schema."""

    def test_access_url_populates_all_fields(self) -> None:
        from unraid_api.models import AccessUrl

        url = AccessUrl(
            type="LAN",
            name="Tower",
            ipv4="http://192.168.1.10",
            ipv6="http://[fd00::1]",
        )
        assert url.type == "LAN"
        assert url.name == "Tower"
        assert url.ipv4 == "http://192.168.1.10"
        assert url.ipv6 == "http://[fd00::1]"

    def test_network_parses_nested_access_urls(self) -> None:
        from unraid_api.models import Network

        net = Network(
            id="network:default",
            accessUrls=[
                {
                    "type": "LAN",
                    "name": "Tower",
                    "ipv4": "http://192.168.1.10",
                    "ipv6": None,
                },
                {
                    "type": "WAN",
                    "name": None,
                    "ipv4": "https://remote.example.com",
                    "ipv6": None,
                },
            ],
        )
        assert net.id == "network:default"
        assert net.accessUrls is not None
        assert len(net.accessUrls) == 2
        assert net.accessUrls[0].type == "LAN"
        assert net.accessUrls[1].ipv4 == "https://remote.example.com"

    def test_network_and_access_url_exported(self) -> None:
        from unraid_api import AccessUrl, Network

        assert Network is not None
        assert AccessUrl is not None


class TestParityCheckSubscriptionFields:
    """ParityCheck model must carry all fields returned by parityHistorySubscription."""

    def test_parity_check_accepts_subscription_payload(self) -> None:
        """Validate a payload shaped like parityHistorySubscription output."""
        from unraid_api.models import ParityCheck

        pc = ParityCheck(
            date="2026-04-11T09:00:00Z",
            duration=3600,
            speed="150.5 MB/s",
            status="RUNNING",
            errors=0,
            progress=42,
            correcting=True,
            paused=False,
            running=True,
        )
        assert pc.status == "RUNNING"
        assert pc.progress == 42
        assert pc.speed == "150.5 MB/s"
        assert pc.duration == 3600
        assert pc.correcting is True
        assert pc.date == datetime(2026, 4, 11, 9, 0, 0, tzinfo=UTC)


# =============================================================================
# New Schema v4.37.x Models Tests
# =============================================================================


class TestInfoNetworkInterfaceModels:
    """Tests for InfoNetworkInterface and IP address models."""

    def test_network_interface_full_parse(self) -> None:
        from unraid_api.models import InfoNetworkInterface

        data = {
            "id": "interface:eth0",
            "name": "eth0",
            "description": "Primary Ethernet",
            "ipAddress": "192.168.1.100",
            "netmask": "255.255.255.0",
            "gateway": "192.168.1.1",
            "macAddress": "00:11:22:33:44:55",
            "speed": 1000,
            "duplex": "full",
            "mtu": 1500,
            "internal": False,
            "virtual": False,
            "useDhcp": True,
            "useDhcp6": False,
            "protocol": "ipv4",
            "operstate": "up",
            "status": "UP",
            "type": "ethernet",
            "vlanId": 10,
            "ipv4Addresses": [{"address": "192.168.1.100", "netmask": "255.255.255.0"}],
            "ipv6Address": "fe80::1",
            "ipv6Addresses": [{"address": "fe80::1", "prefixLength": 64}],
            "ipv6Gateway": "fe80::gateway",
            "ipv6Netmask": "/64",
        }
        iface = InfoNetworkInterface(**data)
        assert iface.id == "interface:eth0"
        assert iface.name == "eth0"
        assert iface.speed == 1000
        assert iface.macAddress == "00:11:22:33:44:55"
        assert iface.mac == "00:11:22:33:44:55"
        assert iface.useDhcp is True
        assert iface.dhcp is True
        assert len(iface.ipv4Addresses) == 1
        assert iface.ipv4Addresses[0].address == "192.168.1.100"
        assert iface.ipv4Addresses[0].netmask == "255.255.255.0"
        assert len(iface.ipv6Addresses) == 1
        assert iface.ipv6Addresses[0].prefixLength == 64


class TestDockerOrganizerModels:
    """Tests for ResolvedOrganizerV1, ResolvedOrganizerView, FlatOrganizerEntry."""

    def test_organizer_model(self) -> None:
        from unraid_api.models import FlatOrganizerEntry, ResolvedOrganizerV1

        data = {
            "version": 1.0,
            "views": [
                {
                    "id": "view:docker",
                    "name": "Docker",
                    "rootId": "root:1",
                    "prefs": {"showHidden": True},
                    "flatEntries": [
                        {
                            "id": "entry:1",
                            "name": "Media",
                            "type": "folder",
                            "depth": 0.0,
                            "hasChildren": True,
                            "childrenIds": ["c1", "c2"],
                            "path": ["Media"],
                            "position": 1.0,
                        }
                    ],
                }
            ],
        }
        org = ResolvedOrganizerV1(**data)
        assert org.version == 1.0
        assert len(org.views) == 1
        assert org.views[0].name == "Docker"
        assert org.views[0].prefs == {"showHidden": True}
        assert len(org.views[0].flatEntries) == 1
        entry = org.views[0].flatEntries[0]
        assert isinstance(entry, FlatOrganizerEntry)
        assert entry.name == "Media"
        assert entry.type == "folder"
        assert entry.hasChildren is True
        assert entry.childrenIds == ["c1", "c2"]


class TestServerAndProfileModels:
    """Tests for Server and ProfileModel."""

    def test_server_model(self) -> None:
        from unraid_api.models import Server

        data = {
            "id": "server:tower",
            "name": "Tower",
            "guid": "guid-12345",
            "lanip": "192.168.1.10",
            "wanip": "203.0.113.1",
            "localurl": "http://tower.local",
            "remoteurl": "https://remote.myunraid.net",
            "status": "ONLINE",
            "comment": "Main NAS",
            "apikey": "key-xyz",  # pragma: allowlist secret
            "owner": {
                "id": "owner:1",
                "username": "admin",
                "avatar": "https://avatar.url",
                "url": "https://profile.url",
            },
        }
        server = Server(**data)
        assert server.id == "server:tower"
        assert server.name == "Tower"
        assert server.status == "ONLINE"
        assert server.owner is not None
        assert server.owner.username == "admin"


class TestPluginInstallModels:
    """Tests for PluginInstallOperation and PluginInstallEvent."""

    def test_plugin_install_operation(self) -> None:
        from datetime import UTC

        from unraid_api.models import PluginInstallOperation

        data = {
            "id": "op:123",
            "name": "community.applications",
            "url": "https://example.com/plugin.plg",
            "status": "COMPLETED",
            "output": ["Downloading package...", "Plugin installed successfully"],
            "createdAt": "2026-09-02T00:00:00Z",
            "updatedAt": "2026-09-02T00:01:00Z",
            "finishedAt": "2026-09-02T00:01:05Z",
        }
        op = PluginInstallOperation(**data)
        assert op.id == "op:123"
        assert op.status == "COMPLETED"
        assert len(op.output) == 2
        assert op.output[1] == "Plugin installed successfully"
        assert op.createdAt == datetime(2026, 9, 2, 0, 0, tzinfo=UTC)

    def test_plugin_install_event(self) -> None:
        from datetime import UTC

        from unraid_api.models import PluginInstallEvent

        event = PluginInstallEvent(
            operationId="op:123",
            status="RUNNING",
            output=["Downloading package..."],
            timestamp="2026-09-02T00:00:30Z",
        )
        assert event.operationId == "op:123"
        assert event.status == "RUNNING"
        assert event.output == ["Downloading package..."]
        assert event.timestamp == datetime(2026, 9, 2, 0, 0, 30, tzinfo=UTC)


class TestExtendedHardwareModels:
    """Tests for MemoryLayout, InfoDisplay, InfoDevices, InfoBaseboard."""

    def test_hardware_models(self) -> None:
        from unraid_api.models import (
            InfoBaseboard,
            InfoDevices,
            InfoDisplay,
            InfoGpu,
            InfoMemory,
            MemoryLayout,
            PackageVersions,
        )

        mem = InfoMemory(
            layout=[
                MemoryLayout(
                    id="dimm:1",
                    size=17179869184,
                    bank="BANK 0",
                    type="DDR4",
                    clockSpeed=3200,
                    manufacturer="Corsair",
                    partNum="CMK32GX4M2B3200C16",
                    serialNum="12345678",
                )
            ]
        )
        assert len(mem.layout) == 1
        assert mem.layout[0].clockSpeed == 3200

        disp = InfoDisplay(
            theme="azure",
            unit="CELSIUS",
            warning=45,
            critical=55,
        )
        assert disp.theme == "azure"
        assert disp.warning == 45

        dev = InfoDevices(
            gpu=[
                InfoGpu(
                    class_="VGA compatible controller", vendorname="NVIDIA Corporation"
                )
            ]
        )
        assert len(dev.gpu) == 1
        assert dev.gpu[0].class_ == "VGA compatible controller"

        base = InfoBaseboard(manufacturer="ASUS", model="ROG STRIX", memSlots=4)
        assert base.manufacturer == "ASUS"
        assert base.memSlots == 4

        pkg = PackageVersions(docker="27.0.3", nginx="1.26.1", node="20.15.0")
        assert pkg.docker == "27.0.3"
