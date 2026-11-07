# Unraid API

The library describes Unraid servers, their resources, and the operations available through the Unraid GraphQL API.

## Language

**Unraid server**:
An Unraid system offering storage and workload management through its API.
_Avoid_: Home Assistant device

**API version**:
The version of the server’s GraphQL API, which may be upgraded independently of the operating system.
_Avoid_: Unraid OS version

**Unraid OS version**:
The version of the operating system installed on the server.
_Avoid_: API version

**Server capability**:
A field or operation the server’s API is understood to support.
_Avoid_: OS-version guarantee

**Server UUID**:
The firmware-reported server identifier; some machines report a placeholder shared by multiple systems.
_Avoid_: universally unique configured-server identity

**API key**:
A credential authorizing access to the Unraid API.
_Avoid_: array decryption credential

**Array**:
The server’s managed storage array, including data disks and any assigned parity disks.
_Avoid_: all physical storage

**Array disk**:
A disk in the array’s storage view, including its data, parity, cache, and boot categories.
_Avoid_: physical disk as an interchangeable term

**Physical disk**:
A hardware storage device that may or may not be assigned to the array.
_Avoid_: array slot

**Disk standby**:
The low-power state of a disk that is not spinning.
_Avoid_: disk removed

**Standby-safe temperature collection**:
Temperature collection that respects disk standby rather than waking a sleeping disk to obtain a reading.
_Avoid_: all disk reads are safe

**Array decryption credential**:
A password or keyfile value supplied to unlock encrypted array storage when starting it.
_Avoid_: API key

**Share**:
A named storage location exposed by the server.
_Avoid_: disk

**Parity check**:
An operation that verifies array parity and may correct it when requested.
_Avoid_: parity history

**Parity status**:
The state and available progress, timing, and error information for a parity operation.
_Avoid_: parity history

**Parity history**:
Records of completed parity operations.
_Avoid_: current parity status

**Docker container**:
An application workload managed by Docker, with a name and an identity that may change on recreation.
_Avoid_: Docker image

**Container update status**:
Information about whether a newer image is available for a container.
_Avoid_: installed application version

**Docker organizer**:
The server’s arrangement of containers into folders and ordered entries.
_Avoid_: Docker network

**Virtual machine (VM)**:
A guest machine managed by the server.
_Avoid_: Docker container

**UPS**:
An uninterruptible power supply protecting the server.
_Avoid_: server power consumption

**Notification**:
An Unraid message with its own identity, content, importance, and read or archived state.
_Avoid_: Home Assistant repair

**Notification overview**:
Counts summarizing notifications by state and importance.
_Avoid_: notification content

**Plugin install operation**:
A tracked attempt to install an Unraid plugin or language package, with its own progress and result.
_Avoid_: installed plugin

**Unraid Connect**:
The Unraid facility for connecting and managing servers, distinct from the server’s local API endpoint.
_Avoid_: local API
