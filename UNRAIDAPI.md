# Unraid GraphQL API Reference

> **API Version:** 4.37.x+
> **Unraid Version:** 7.3.x+
> **Last Updated:** September 2026

This document provides a comprehensive reference for the Unraid GraphQL API, sourced from the official [unraid/api](https://github.com/unraid/api) repository.

## Table of Contents

- [Authentication](#authentication)
- [Scalars](#scalars)
- [Enums](#enums)
- [Types](#types)
- [Queries](#queries)
- [Mutations](#mutations)
- [Subscriptions](#subscriptions)

---

## Authentication

Include the API key in your requests as a header:

```
x-api-key: YOUR_API_KEY_HERE
```

### Creating an API Key

```graphql
mutation {
  apiKey {
    create(input: {
      name: "My API Key"
      description: "API key for my application"
      roles: [ADMIN]
    }) {
      id
      key
      name
      roles
      permissions
    }
  }
}
```

---

## Scalars

| Scalar | Description |
|--------|-------------|
| `PrefixedID` | ID prefixed with server identifier (e.g., `server123:resource456`) |
| `BigInt` | Non-fractional signed whole numeric values |
| `DateTime` | UTC date-time string (e.g., `2019-12-03T09:54:33Z`) |
| `JSON` | JSON values per ECMA-404 |
| `Port` | Valid TCP port (0-65535) |
| `URL` | Standard URL format per RFC3986 |

---

## Enums

### Array & Disk

```graphql
enum ArrayState {
  STARTED
  STOPPED
  NEW_ARRAY
  RECON_DISK
  DISABLE_DISK
  SWAP_DSBL
  INVALID_EXPANSION
  PARITY_NOT_BIGGEST
  TOO_MANY_MISSING_DISKS
  NEW_DISK_TOO_SMALL
  NO_DATA_DISKS
}

enum ArrayDiskStatus {
  DISK_NP          # Not present
  DISK_OK          # Normal
  DISK_NP_MISSING  # Missing
  DISK_INVALID     # Invalid
  DISK_WRONG       # Wrong disk
  DISK_DSBL        # Disabled
  DISK_NP_DSBL     # Not present, disabled
  DISK_DSBL_NEW    # Disabled, new
  DISK_NEW         # New disk
}

enum ArrayDiskType {
  DATA
  PARITY
  FLASH
  CACHE
}

enum ArrayDiskFsColor {
  GREEN_ON
  GREEN_BLINK
  BLUE_ON
  BLUE_BLINK
  YELLOW_ON
  YELLOW_BLINK
  RED_ON
  RED_OFF
  GREY_OFF
}

enum DiskFsType {
  XFS
  BTRFS
  VFAT
  ZFS
  EXT4
  NTFS
}

enum DiskInterfaceType {
  SAS
  SATA
  USB
  PCIE
  UNKNOWN
}

enum DiskSmartStatus {
  OK
  UNKNOWN
}
```

### Parity Check

```graphql
enum ParityCheckStatus {
  NEVER_RUN
  RUNNING
  PAUSED
  COMPLETED
  CANCELLED
  FAILED
}
```

### Docker

```graphql
enum ContainerState {
  RUNNING
  PAUSED
  EXITED
}

enum ContainerPortType {
  TCP
  UDP
}

enum UpdateStatus {
  UP_TO_DATE
  UPDATE_AVAILABLE
  REBUILD_READY
  UNKNOWN
}
```

### VM

```graphql
enum VmState {
  NOSTATE
  RUNNING
  IDLE
  PAUSED
  SHUTDOWN
  SHUTOFF
  CRASHED
  PMSUSPENDED
}
```

### Authentication & Permissions

```graphql
enum Role {
  ADMIN    # Full administrative access
  CONNECT  # Internal role for Unraid Connect
  GUEST    # Basic read access to user profile only
  VIEWER   # Read-only access to all resources
}

enum Resource {
  ACTIVATION_CODE
  API_KEY
  ARRAY
  CLOUD
  CONFIG
  CONNECT
  CONNECT__REMOTE_ACCESS
  CUSTOMIZATIONS
  DASHBOARD
  DISK
  DISPLAY
  DOCKER
  FLASH
  INFO
  LOGS
  ME
  NETWORK
  NOTIFICATIONS
  ONLINE
  OS
  OWNER
  PERMISSION
  REGISTRATION
  SERVERS
  SERVICES
  SHARE
  VARS
  VMS
  WELCOME
}

enum AuthAction {
  CREATE_ANY
  CREATE_OWN
  READ_ANY
  READ_OWN
  UPDATE_ANY
  UPDATE_OWN
  DELETE_ANY
  DELETE_OWN
}
```

### Registration

```graphql
enum registrationType {
  BASIC
  PLUS
  PRO
  STARTER
  UNLEASHED
  LIFETIME
  INVALID
  TRIAL
}

enum RegistrationState {
  TRIAL
  BASIC
  PLUS
  PRO
  STARTER
  UNLEASHED
  LIFETIME
  EEXPIRED
  EGUID
  EGUID1
  ETRIAL
  ENOKEYFILE
  ENOKEYFILE1
  ENOKEYFILE2
  ENOFLASH
  ENOFLASH1
  ENOFLASH2
  ENOFLASH3
  ENOFLASH4
  ENOFLASH5
  ENOFLASH6
  ENOFLASH7
  EBLACKLISTED
  EBLACKLISTED1
  EBLACKLISTED2
  ENOCONN
}
```

### Notifications

```graphql
enum NotificationImportance {
  ALERT
  INFO
  WARNING
}

enum NotificationType {
  UNREAD
  ARCHIVE
}
```

### UPS

```graphql
enum UPSServiceState {
  ENABLE
  DISABLE
}

enum UPSCableType {
  USB
  SIMPLE
  SMART
  ETHER
  CUSTOM
}

enum UPSType {
  USB
  APCSMART
  NET
  SNMP
  DUMB
  PCNET
  MODBUS
}

enum UPSKillPower {
  YES
  NO
}
```

### Display & Theme

```graphql
enum ThemeName {
  azure
  black
  gray
  white
}

enum Temperature {
  CELSIUS
  FAHRENHEIT
}
```

### Network & Connect

```graphql
enum URL_TYPE {
  LAN
  WIREGUARD
  WAN
  MDNS
  OTHER
  DEFAULT
}

enum WAN_ACCESS_TYPE {
  DYNAMIC
  ALWAYS
  DISABLED
}

enum WAN_FORWARD_TYPE {
  UPNP
  STATIC
}

enum DynamicRemoteAccessType {
  STATIC
  UPNP
  DISABLED
}

enum ServerStatus {
  ONLINE
  OFFLINE
  NEVER_CONNECTED
}

enum MinigraphStatus {
  PRE_INIT
  CONNECTING
  CONNECTED
  PING_FAILURE
  ERROR_RETRYING
}
```

---

## Types

### Array

```graphql
type UnraidArray {
  id: PrefixedID!
  state: ArrayState!
  capacity: ArrayCapacity!
  boot: ArrayDisk
  parities: [ArrayDisk!]!
  parityCheckStatus: ParityCheck!
  disks: [ArrayDisk!]!
  caches: [ArrayDisk!]!
}

type ArrayCapacity {
  kilobytes: Capacity!
  disks: Capacity!
}

type Capacity {
  free: String!
  used: String!
  total: String!
}

type ArrayDisk {
  id: PrefixedID!
  idx: Int!                    # Slot number (parity1=0, parity2=29, data=1-28, cache=30-53, flash=54)
  name: String
  device: String
  size: BigInt                 # KB
  status: ArrayDiskStatus
  rotational: Boolean          # HDD or SSD
  temp: Int                    # Temperature (NaN if array not started)
  numReads: BigInt
  numWrites: BigInt
  numErrors: BigInt
  fsSize: BigInt               # KB - filesystem total
  fsFree: BigInt               # KB - filesystem free
  fsUsed: BigInt               # KB - filesystem used
  exportable: Boolean
  type: ArrayDiskType!
  warning: Int                 # % disk space warning threshold
  critical: Int                # % disk space critical threshold
  fsType: String
  comment: String
  format: String               # e.g., "MBR: 4KiB-aligned"
  transport: String            # ata | nvme | usb
  color: ArrayDiskFsColor
  isSpinning: Boolean
}

type ParityCheck {
  date: DateTime
  duration: Int                # seconds
  speed: String                # MB/s
  status: ParityCheckStatus!
  errors: Int
  progress: Int                # percentage
  correcting: Boolean
  paused: Boolean
  running: Boolean
}
```

### Docker

```graphql
type Docker {
  id: PrefixedID!
  containers(skipCache: Boolean = false): [DockerContainer!]!
  networks(skipCache: Boolean = false): [DockerNetwork!]!
  portConflicts(skipCache: Boolean = false): DockerPortConflicts!
  logs(id: PrefixedID!, since: DateTime, tail: Int): DockerContainerLogs!
  container(id: PrefixedID!): DockerContainer
  organizer(skipCache: Boolean = false): ResolvedOrganizerV1!
  containerUpdateStatuses: [ExplicitStatusItem!]!
}

type DockerContainer {
  id: PrefixedID!
  names: [String!]!
  image: String!
  imageId: String!
  command: String!
  created: Int!
  ports: [ContainerPort!]!
  lanIpPorts: [String!]
  sizeRootFs: BigInt           # Total size in bytes
  sizeRw: BigInt               # Writable layer size
  sizeLog: BigInt              # Log size
  labels: JSON
  state: ContainerState!
  status: String!
  hostConfig: ContainerHostConfig
  networkSettings: JSON
  mounts: [JSON!]
  autoStart: Boolean!
  autoStartOrder: Int
  autoStartWait: Int           # seconds
  templatePath: String
  projectUrl: String
  registryUrl: String
  supportUrl: String
  iconUrl: String
  webUiUrl: String
  shell: String
  templatePorts: [ContainerPort!]
  isOrphaned: Boolean!
  isUpdateAvailable: Boolean
  isRebuildReady: Boolean
  tailscaleEnabled: Boolean!
  tailscaleStatus(forceRefresh: Boolean = false): TailscaleStatus
}

type DockerContainerStats {
  id: PrefixedID!
  cpuPercent: Float!
  memUsage: String!            # e.g., "100MB / 1GB"
  memPercent: Float!
  netIO: String!               # e.g., "100MB / 1GB"
  blockIO: String!             # e.g., "100MB / 1GB"
}

type ContainerPort {
  ip: String
  privatePort: Port
  publicPort: Port
  type: ContainerPortType!
}

type DockerContainerLogs {
  containerId: PrefixedID!
  lines: [DockerContainerLogLine!]!
  cursor: DateTime
}

type DockerContainerLogLine {
  timestamp: DateTime!
  message: String!
}
```

### VM

```graphql
type Vms {
  id: PrefixedID!
  domains: [VmDomain!]
  domain: [VmDomain!]
}

type VmDomain {
  id: PrefixedID!              # UUID
  name: String
  state: VmState!
  uuid: String @deprecated     # Use id instead; selected by typed_get_vms only when present
}
```

### Info (System Information)

```graphql
type Info {
  id: PrefixedID!
  time: DateTime!
  baseboard: InfoBaseboard!
  cpu: InfoCpu!
  devices: InfoDevices!
  display: InfoDisplay!
  machineId: ID
  memory: InfoMemory!
  os: InfoOs!
  system: InfoSystem!
  versions: InfoVersions!
}

type InfoVersions {
  id: PrefixedID!
  core: CoreVersions!
  packages: PackageVersions
}

type CoreVersions {
  unraid: String
  api: String
  kernel: String
}

type PackageVersions {
  openssl: String
  node: String
  npm: String
  pm2: String
  git: String
  nginx: String
  php: String
  docker: String
}

type InfoCpu {
  id: PrefixedID!
  manufacturer: String
  brand: String
  vendor: String
  family: String
  model: String
  stepping: Int
  revision: String
  voltage: String
  speed: Float                 # GHz
  speedmin: Float
  speedmax: Float
  threads: Int
  cores: Int
  processors: Int
  socket: String
  cache: JSON
  flags: [String!]
  topology: [[[Int!]!]!]!
  packages: CpuPackages!
}

type InfoMemory {
  id: PrefixedID!
  layout: [MemoryLayout!]!
}

type MemoryLayout {
  id: PrefixedID!
  size: BigInt!                # bytes
  bank: String
  type: String                 # e.g., DDR4
  clockSpeed: Int              # MHz
  partNum: String
  serialNum: String
  manufacturer: String
  formFactor: String
  voltageConfigured: Int       # mV
  voltageMin: Int
  voltageMax: Int
}

type InfoOs {
  id: PrefixedID!
  platform: String
  distro: String
  release: String
  codename: String
  kernel: String
  arch: String
  hostname: String
  fqdn: String
  build: String
  servicepack: String
  uptime: String               # ISO string
  logofile: String
  serial: String
  uefi: Boolean
}

type InfoBaseboard {
  id: PrefixedID!
  manufacturer: String
  model: String
  version: String
  serial: String
  assetTag: String
  memMax: Float                # bytes
  memSlots: Float
}

type InfoSystem {
  id: PrefixedID!
  manufacturer: String
  model: String
  version: String
  serial: String
  uuid: String
  sku: String
  virtual: Boolean
}

type InfoDisplay {
  id: PrefixedID!
  case: InfoDisplayCase!
  theme: ThemeName!
  unit: Temperature!
  scale: Boolean
  tabs: Boolean
  resize: Boolean
  wwn: Boolean
  total: Boolean
  usage: Boolean
  text: Boolean
  warning: Int!                # Temperature threshold
  critical: Int!
  hot: Int!
  max: Int
  locale: String
}

type InfoDevices {
  id: PrefixedID!
  gpu: [InfoGpu!]
  network: [InfoNetwork!]
  pci: [InfoPci!]
  usb: [InfoUsb!]
}
```

### Metrics

```graphql
type Metrics {
  id: PrefixedID!
  cpu: CpuUtilization
  memory: MemoryUtilization
}

type CpuUtilization {
  id: PrefixedID!
  percentTotal: Float!
  cpus: [CpuLoad!]!
}

type CpuLoad {
  percentTotal: Float!
  percentUser: Float!
  percentSystem: Float!
  percentNice: Float!
  percentIdle: Float!
  percentIrq: Float!
  percentGuest: Float!
  percentSteal: Float!
}

type CpuPackages {
  id: PrefixedID!
  totalPower: Float!           # Watts
  power: [Float!]!             # Per package
  temp: [Float!]!              # °C per package
}

type MemoryUtilization {
  id: PrefixedID!
  total: BigInt!               # bytes
  used: BigInt!
  free: BigInt!
  available: BigInt!
  active: BigInt!
  buffcache: BigInt!
  percentTotal: Float!
  swapTotal: BigInt!
  swapUsed: BigInt!
  swapFree: BigInt!
  percentSwapTotal: Float!
}
```

### Notifications

```graphql
type Notifications {
  id: PrefixedID!
  overview: NotificationOverview!
  list(filter: NotificationFilter!): [Notification!]!
  warningsAndAlerts: [Notification!]!
}

type NotificationOverview {
  unread: NotificationCounts!
  archive: NotificationCounts!
}

type NotificationCounts {
  info: Int!
  warning: Int!
  alert: Int!
  total: Int!
}

type Notification {
  id: PrefixedID!
  title: String!               # aka 'event'
  subject: String!
  description: String!
  importance: NotificationImportance!
  link: String
  type: NotificationType!
  timestamp: String
  formattedTimestamp: String
}
```

### UPS

```graphql
type UPSDevice {
  id: ID!
  name: String!
  model: String!
  status: String!              # Online, On Battery, Low Battery, etc.
  battery: UPSBattery!
  power: UPSPower!
}

type UPSBattery {
  chargeLevel: Int!            # 0-100%
  estimatedRuntime: Int!       # seconds
  health: String!              # Good, Replace, Unknown
}

type UPSPower {
  inputVoltage: Float!         # Volts
  outputVoltage: Float!        # Volts
  loadPercentage: Int!         # 0-100%
  nominalPower: Int            # Nominal capacity in watts (optional, UPS-dependent)
  currentPower: Float          # Current consumption in watts (derived from nominal × load)
}

type UPSConfiguration {
  service: String
  upsCable: String
  customUpsCable: String
  upsType: String
  device: String
  overrideUpsCapacity: Int
  batteryLevel: Int
  minutes: Int
  timeout: Int
  killUps: String
  nisIp: String
  netServer: String
  upsName: String
  modelName: String
}
```

### Shares

```graphql
type Share {
  id: PrefixedID!
  name: String
  free: BigInt                 # KB
  used: BigInt                 # KB
  size: BigInt                 # KB
  include: [String!]
  exclude: [String!]
  cache: Boolean
  nameOrig: String
  comment: String
  allocator: String
  splitLevel: String
  floor: String
  cow: String
  color: String
  luksStatus: String
}
```

### Physical Disks

```graphql
type Disk {
  id: PrefixedID!
  device: String!              # e.g., /dev/sdb
  type: String!                # SSD, HDD
  name: String!                # Model name
  vendor: String!
  size: Float!                 # bytes
  bytesPerSector: Float!
  totalCylinders: Float!
  totalHeads: Float!
  totalSectors: Float!
  totalTracks: Float!
  tracksPerCylinder: Float!
  sectorsPerTrack: Float!
  firmwareRevision: String!
  serialNum: String!
  interfaceType: DiskInterfaceType!
  smartStatus: DiskSmartStatus!
  temperature: Float           # Celsius
  partitions: [DiskPartition!]!
  isSpinning: Boolean!
}

type DiskPartition {
  name: String!
  fsType: DiskFsType!
  size: Float!                 # bytes
}
```

### Registration & Vars

```graphql
type Registration {
  id: PrefixedID!
  type: registrationType
  keyFile: KeyFile
  state: RegistrationState
  expiration: String
  updateExpiration: String
}

type Vars {
  id: PrefixedID!
  version: String              # Unraid version
  name: String                 # Hostname
  timeZone: String
  comment: String
  useSsl: Boolean
  port: Int                    # HTTP port
  portssl: Int                 # HTTPS port
  # ... many more configuration variables
}
```

### Users & API Keys

```graphql
type UserAccount {
  id: PrefixedID!
  name: String!
  description: String!
  roles: [Role!]!
  permissions: [Permission!]
}

type ApiKey {
  id: PrefixedID!
  key: String!
  name: String!
  description: String
  roles: [Role!]!
  createdAt: String!
  permissions: [Permission!]!
}

type Permission {
  resource: Resource!
  actions: [AuthAction!]!
}
```

### Network & Cloud

```graphql
type Network {
  id: PrefixedID!
  accessUrls: [AccessUrl!]
}

type AccessUrl {
  type: URL_TYPE!
  name: String
  ipv4: URL
  ipv6: URL
}

type Cloud {
  error: String
  apiKey: ApiKeyResponse!
  relay: RelayResponse
  minigraphql: MinigraphqlResponse!
  cloud: CloudResponse!
  allowedOrigins: [String!]!
}

type Connect {
  id: PrefixedID!
  dynamicRemoteAccess: DynamicRemoteAccessStatus!
  settings: ConnectSettings!
}

type RemoteAccess {
  accessType: WAN_ACCESS_TYPE!
  forwardType: WAN_FORWARD_TYPE
  port: Int
}

type InfoNetworkInterface {
  id: PrefixedID!
  name: String!
  description: String
  ipAddress: String
  netmask: String
  gateway: String
  macAddress: String
  speed: Int
  duplex: String
  mtu: Int
  internal: Boolean
  virtual: Boolean
  useDhcp: Boolean
  useDhcp6: Boolean
  protocol: String
  operstate: String
  status: String
  type: String
  vlanId: Int
  ipv4Addresses: [InfoNetworkIpv4Address!]!
  ipv6Address: String
  ipv6Gateway: String
  ipv6Netmask: String
  ipv6Addresses: [InfoNetworkIpv6Address!]!
}

type InfoNetworkIpv4Address {
  address: String!
  netmask: String!
}

type InfoNetworkIpv6Address {
  address: String!
  prefixLength: Int!
}
```

### Docker Organizer

```graphql
type ResolvedOrganizerV1 {
  version: Float!
  views: [ResolvedOrganizerView!]!
}

type ResolvedOrganizerView {
  id: String!
  name: String!
  rootId: String!
  prefs: JSON
  flatEntries: [FlatOrganizerEntry!]!
}

type FlatOrganizerEntry {
  id: String!
  name: String!
  type: String!
  parentId: String
  childrenIds: [String!]!
  depth: Float!
  hasChildren: Boolean!
  path: [String!]!
  position: Float!
}
```

### Server & Connect

```graphql
type Server {
  id: PrefixedID!
  name: String!
  comment: String
  guid: String
  lanip: String
  wanip: String
  localurl: String
  remoteurl: String
  status: ServerStatus
  apikey: String
  owner: ProfileModel
}

type ProfileModel {
  id: String
  username: String!
  avatar: String
  url: String
}
```

### Plugin Background Operations

Both install mutations install software and return a background operation.
`installLanguage` accepts a language-pack URL, not a language code. Optional
`name` and `forced` values are passed in `InstallPluginInput` alongside `url`.
Follow progress with `pluginInstallUpdates(operationId: ...)`.

```graphql
# Variables: {"input": {"url": "https://example.test/plugin.plg"}}
mutation InstallPlugin($input: InstallPluginInput!) {
  unraidPlugins {
    installPlugin(input: $input) {
      id name url status output createdAt updatedAt finishedAt
    }
  }
}

# Variables: {"input": {"url": "https://example.test/language.xml"}}
mutation InstallLanguage($input: InstallPluginInput!) {
  unraidPlugins {
    installLanguage(input: $input) {
      id name url status output createdAt updatedAt finishedAt
    }
  }
}

type PluginInstallOperation {
  id: ID!
  name: String
  url: String!
  status: PluginInstallStatus!
  output: [String!]!
  createdAt: DateTime!
  updatedAt: DateTime
  finishedAt: DateTime
}

type PluginInstallEvent {
  operationId: ID!
  status: PluginInstallStatus!
  output: [String!]!
  timestamp: DateTime!
}
```

---

## Queries

### System Queries

```graphql
# Check if server is online
query { online }

# Get system information
query {
  info {
    time
    os { hostname uptime kernel }
    cpu { brand cores threads }
    memory { layout { size type clockSpeed manufacturer } }
    versions { core { unraid api kernel } }
    baseboard { manufacturer model memMax memSlots }
    display { theme unit warning critical }
  }
}

# Get system metrics
query {
  metrics {
    cpu { percentTotal cpus { percentTotal percentUser percentSystem } }
    memory { total used free percentTotal swapTotal swapUsed }
  }
}

# Get system variables
query {
  vars {
    version
    name
    timeZone
    useSsl
    port
    portssl
  }
}

# Get registration info
query {
  registration {
    type
    state
    expiration
  }
}
```

### Array Queries

```graphql
query {
  array {
    state
    capacity {
      kilobytes { free used total }
      disks { free used total }
    }
    parityCheckStatus {
      status
      progress
      running
      paused
      errors
    }
    boot { name device size }
    parities { name device size status type temp }
    disks {
      name device size status type temp
      fsSize fsFree fsUsed
      numReads numWrites numErrors
      isSpinning
    }
    caches { name device size status type temp fsSize fsFree fsUsed }
  }
}

# Get parity history
query { parityHistory { date duration speed status errors } }

# Get physical disks
query {
  disks {
    device name vendor size
    interfaceType smartStatus temperature
    isSpinning
    partitions { name fsType size }
  }
}
```

### Docker Queries

```graphql
query {
  docker {
    containers {
      id names image state status
      autoStart autoStartOrder
      ports { ip privatePort publicPort type }
      isUpdateAvailable isOrphaned
      webUiUrl iconUrl
    }
  }
}

# Get single container
query {
  docker {
    container(id: "container:abc123") {
      names image state status
      sizeRootFs sizeRw sizeLog
    }
  }
}

# Get container logs
query {
  docker {
    logs(id: "container:abc123", tail: 100) {
      lines { timestamp message }
      cursor
    }
  }
}

# Get container update statuses
query {
  docker {
    containerUpdateStatuses { name updateStatus }
  }
}
```

### VM Queries

```graphql
query {
  vms {
    domains {
      id name state
    }
  }
}
```

### Notification Queries

```graphql
query {
  notifications {
    overview {
      unread { info warning alert total }
      archive { info warning alert total }
    }
    warningsAndAlerts { title subject description importance timestamp }
    list(filter: { type: UNREAD, offset: 0, limit: 20 }) {
      id title subject description importance timestamp
    }
  }
}
```

### Share Queries

```graphql
query {
  shares {
    name free used size
    include exclude cache
    comment
  }
}
```

### UPS Queries

```graphql
query {
  upsDevices {
    id name model status
    battery { chargeLevel estimatedRuntime health }
    power { inputVoltage outputVoltage loadPercentage }
  }
  upsConfiguration {
    service upsCable upsType device
    batteryLevel minutes timeout
  }
}
```

### User & API Key Queries

```graphql
query {
  me { id name description roles }
  apiKeys { id name description roles createdAt }
  apiKeyPossibleRoles
  apiKeyPossiblePermissions { resource actions }
}
```

### Other Queries

```graphql
# Services
query { services { name online version uptime { timestamp } } }

# Plugins
query { plugins { name version hasApiModule hasCliModule } }
query { installedUnraidPlugins }
query {
  pluginInstallOperations {
    id name url status output createdAt updatedAt finishedAt
  }
}

# Network Interfaces
query {
  networkInterfaces {
    id name description ipAddress netmask gateway macAddress
    speed duplex mtu internal virtual useDhcp useDhcp6 protocol
    operstate status type vlanId
    ipv4Addresses { address netmask }
    ipv6Address ipv6Gateway ipv6Netmask
    ipv6Addresses { address prefixLength }
  }
}

# Docker Organizer
query {
  docker {
    organizer(skipCache: false) {
      version
      views {
        id name rootId prefs
        flatEntries {
          id name type parentId childrenIds depth hasChildren path position
        }
      }
    }
  }
}

# Server & Connect Identity
query {
  servers {
    id name guid lanip wanip localurl remoteurl status comment apikey
    owner { id username avatar url }
  }
}
query {
  server {
    id name guid lanip wanip localurl remoteurl status comment apikey
    owner { id username avatar url }
  }
}

# Log files
query { logFiles { name path size modifiedAt } }
query { logFile(path: "/var/log/syslog", lines: 100) { path content totalLines } }

# Flash drive
query { flash { guid vendor product } }

# Settings
query { settings { unified { dataSchema uiSchema values } } }

# Cloud/Connect status
query {
  cloud { error apiKey { valid } minigraphql { status } }
  connect { dynamicRemoteAccess { enabledType runningType error } }
  remoteAccess { accessType forwardType port }
  network { accessUrls { type name ipv4 ipv6 } }
}
```

---

## Mutations

### Array Mutations

```graphql
# Start array
mutation {
  array {
    setState(input: { desiredState: START }) { state }
  }
}

# Start an encrypted array over certificate-verified HTTPS.
# Secrets go in variables, never query text.
# Variables: {"input": {"desiredState": "START", "decryptionPassword": "...",
#                      "decryptionKeyfile": "<data URL or raw base64 contents>"}}
mutation StartEncryptedArray($input: ArrayStateInput!) {
  array { setState(input: $input) { id state } }
}

# Stop array
mutation {
  array {
    setState(input: { desiredState: STOP }) { state }
  }
}

# Add disk to array
mutation {
  array {
    addDiskToArray(input: { id: "disk:abc", slot: 1 }) { state }
  }
}

# Historical only: removed upstream after v4.36.0 (unraid/api#2068).
# Use Unraid Core storage workflows; only older schemas support this mutation.
mutation {
  array {
    removeDiskFromArray(input: { id: "disk:abc" }) { state }
  }
}

# Mount/unmount disk
mutation {
  array {
    mountArrayDisk(id: "disk:1") { id name isSpinning }
    unmountArrayDisk(id: "disk:1") { id name isSpinning }
  }
}

# Clear disk statistics
mutation {
  array {
    clearArrayDiskStatistics(id: "disk:1")
  }
}
```

### Parity Check Mutations

```graphql
mutation {
  parityCheck {
    start(correct: false)  # or true for correcting parity
  }
}

mutation { parityCheck { pause } }
mutation { parityCheck { resume } }
mutation { parityCheck { cancel } }
```

### Docker Mutations

```graphql
# Native restart (when DockerMutations.restart is available)
mutation RestartContainer($id: PrefixedID!) {
  docker { restart(id: $id) { id state status } }
}

# Start container
mutation {
  docker {
    start(id: "container:abc123") { id names state status }
  }
}

# Stop container
mutation {
  docker {
    stop(id: "container:abc123") { id names state status }
  }
}

# Pause/unpause container
mutation {
  docker {
    pause(id: "container:abc123") { id state }
    unpause(id: "container:abc123") { id state }
  }
}

# Remove container
mutation {
  docker {
    removeContainer(id: "container:abc123", withImage: false)
  }
}

# Update container to latest image
mutation {
  docker {
    updateContainer(id: "container:abc123") { id names image }
  }
}

# Update multiple containers
mutation {
  docker {
    updateContainers(ids: ["container:abc", "container:def"]) { id names }
  }
}

# Update all containers
mutation {
  docker {
    updateAllContainers { id names }
  }
}

# Update auto-start configuration
mutation {
  docker {
    updateAutostartConfiguration(entries: [
      { id: "container:abc", autoStart: true, wait: 5 }
    ])
  }
}

# Docker Folder Management
mutation {
  createDockerFolder(name: "Media", childrenIds: ["container:1", "container:2"]) {
    version
    views { id name flatEntries { id name type } }
  }
}

mutation {
  renameDockerFolder(folderId: "folder:1", newName: "New Media") {
    version
    views { id name flatEntries { id name type } }
  }
}

mutation {
  deleteDockerEntries(entryIds: ["folder:1"]) {
    version
    views { id name flatEntries { id name type } }
  }
}

mutation {
  moveDockerEntriesToFolder(sourceEntryIds: ["container:1"], destinationFolderId: "folder:2") {
    version
    views { id name flatEntries { id name type } }
  }
}
```

### Server Identity Mutations

```graphql
# Update server identity
mutation {
  updateServerIdentity(name: "Tower", comment: "Main NAS", sysModel: "Custom Unraid") {
    id
    name
    comment
    guid
    lanip
    wanip
    localurl
    remoteurl
    status
    apikey
  }
}
```

### VM Mutations

```graphql
mutation { vm { start(id: "vm:uuid") } }      # Returns Boolean!
mutation { vm { stop(id: "vm:uuid") } }
mutation { vm { pause(id: "vm:uuid") } }
mutation { vm { resume(id: "vm:uuid") } }
mutation { vm { forceStop(id: "vm:uuid") } }
mutation { vm { reboot(id: "vm:uuid") } }
mutation { vm { reset(id: "vm:uuid") } }
```

### API Key Mutations

```graphql
# Create API key
mutation {
  apiKey {
    create(input: {
      name: "My Key"
      description: "For my app"
      roles: [ADMIN]
    }) {
      id key name roles
    }
  }
}

# Update API key
mutation {
  apiKey {
    update(input: { id: "apikey:123", name: "New Name" }) { id name }
  }
}

# Delete API keys
mutation {
  apiKey {
    delete(input: { ids: ["apikey:123", "apikey:456"] })
  }
}

# Add/remove role
mutation { apiKey { addRole(input: { apiKeyId: "apikey:123", role: VIEWER }) } }
mutation { apiKey { removeRole(input: { apiKeyId: "apikey:123", role: VIEWER }) } }
```

### Notification Mutations

```graphql
# Create notification
mutation {
  createNotification(input: {
    title: "Test"
    subject: "Test Subject"
    description: "Test description"
    importance: INFO
  }) { id }
}

# Archive notification
mutation { archiveNotification(id: "notification:123") { id } }
mutation { archiveNotifications(ids: ["notification:123"]) { unread { total } } }
mutation { archiveAll(importance: WARNING) { unread { total } } }

# Unarchive
mutation { unreadNotification(id: "notification:123") { id } }
mutation { unarchiveNotifications(ids: ["notification:123"]) { archive { total } } }
mutation { unarchiveAll(importance: INFO) { archive { total } } }

# Delete
mutation { deleteNotification(id: "notification:123", type: ARCHIVE) { unread { total } } }
mutation { deleteArchivedNotifications { archive { total } } }
```

### Settings Mutations

```graphql
# Update settings
mutation {
  updateSettings(input: { /* JSON settings */ }) {
    restartRequired
    values
    warnings
  }
}

# Configure UPS
mutation {
  configureUps(config: {
    service: ENABLE
    upsCable: USB
    upsType: USB
    device: "/dev/usb/hiddev0"
    batteryLevel: 10
    minutes: 5
  })
}
```

### Theme Mutations

```graphql
mutation {
  customization {
    setTheme(theme: black) { name }
  }
}
```

---

## Subscriptions

Real-time updates via WebSocket:

```graphql
# Array state changes
subscription { arraySubscription { state capacity { kilobytes { free used total } } } }

# Parity history updates
subscription { parityHistorySubscription { date status progress errors } }

# Docker container stats (live)
subscription {
  dockerContainerStats {
    id cpuPercent memUsage memPercent netIO blockIO
  }
}

# System metrics
subscription { systemMetricsCpu { percentTotal cpus { percentTotal } } }
subscription { systemMetricsCpuTelemetry { totalPower power temp } }
subscription { systemMetricsMemory { total used free percentTotal } }

# Notifications
subscription { notificationAdded { id title subject importance } }
subscription { notificationsOverview { unread { total } archive { total } } }
subscription { notificationsWarningsAndAlerts { title importance } }

# UPS updates
subscription { upsUpdates { id status battery { chargeLevel } } }

# Log file streaming
subscription { logFile(path: "/var/log/syslog") { content } }

# Server/owner updates
subscription { ownerSubscription { username avatar } }
subscription { serversSubscription { name status } }
```

---

## Example: Complete System Status Query

```graphql
query SystemStatus {
  online
  info {
    os { hostname uptime }
    cpu { brand cores threads }
    versions { core { unraid api } }
  }
  metrics {
    cpu { percentTotal }
    memory { percentTotal }
  }
  array {
    state
    capacity { kilobytes { free used total } }
    parityCheckStatus { status progress running }
  }
  docker {
    containers { names state isUpdateAvailable }
  }
  vms {
    domains { name state }
  }
  notifications {
    overview { unread { alert warning } }
  }
  upsDevices {
    status
    battery { chargeLevel }
  }
}
```

---

## Notes

- All IDs use `PrefixedID` format: `serverIdentifier:resourceId`
- Sizes in `ArrayDisk` and `Share` are in **kilobytes (KB)**
- Sizes in `Disk` and `DiskPartition` are in **bytes**
- Temperature values are in **Celsius** unless `InfoDisplay.unit` is `FAHRENHEIT`
- The API uses nested mutation types (e.g., `array.setState`, `docker.start`)
- VM mutations return `Boolean!`, not `VmDomain`
