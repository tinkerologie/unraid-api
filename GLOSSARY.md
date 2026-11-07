# Unraid API

This glossary gives terms for Unraid servers and the Unraid GraphQL API.

## Language

**Unraid server**:
An Unraid system that supplies storage and controls workloads through its API.
_Avoid_: Home Assistant device

**API version**:
The version of the Unraid GraphQL API. You can update the API independently of Unraid OS.
_Avoid_: Unraid OS version

**Unraid OS version**:
The version of the Unraid operating system on the server.
_Avoid_: API version

**Server capability**:
A GraphQL field or operation that the client identifies as available on the server.
_Avoid_: OS-version guarantee

**Server UUID**:
The server identifier that the firmware gives. Some servers give the same placeholder UUID.
_Avoid_: universally unique configured-server identity

**API key**:
A credential that gives access to the Unraid API.
_Avoid_: array decryption credential

**Array**:
The Unraid storage array with data disks and parity disks if present.
_Avoid_: all physical storage

**Array disk**:
A disk in the array storage view. The view has data, parity, cache, and boot disks.
_Avoid_: physical disk as an interchangeable term

**Physical disk**:
A hardware storage device. The disk can belong to the array storage view or be separate.
_Avoid_: array slot

**Disk standby**:
The low-power condition of a disk when the disk does not rotate.
_Avoid_: disk removed

**Standby-safe temperature collection**:
A temperature query that lets a disk stay in standby.
_Avoid_: all disk reads are safe

**Array decryption credential**:
A password or keyfile value that unlocks encrypted array storage when the array starts.
_Avoid_: API key

**Share**:
A storage location with a name that Unraid makes available.
_Avoid_: disk

**Parity check**:
An operation that checks array parity. The operation can also correct parity if you request correction.
_Avoid_: parity history

**Parity status**:
The current condition, progress, elapsed time, and errors for a parity operation.
_Avoid_: parity history

**Parity history**:
The record of completed parity operations.
_Avoid_: current parity status

**Docker container**:
A workload that the Docker engine controls. A new container can have the same name and a different ID.
_Avoid_: Docker image

**Container update status**:
Information about whether a newer image is available for a container.
_Avoid_: installed application version

**Docker organizer**:
The Unraid list of containers in folders and their order.
_Avoid_: Docker network

**Virtual machine (VM)**:
A guest machine that the Unraid server controls.
_Avoid_: Docker container

**UPS**:
An uninterruptible power supply for the Unraid server.
_Avoid_: server power consumption

**Notification**:
An Unraid message with an ID, content, importance, and read or archive status.
_Avoid_: Home Assistant repair

**Notification overview**:
The number of notifications for each status and level of importance.
_Avoid_: notification content

**Plugin install operation**:
An operation that installs an Unraid plugin or language package. It has a progress value and a result.
_Avoid_: installed plugin

**Unraid Connect**:
The Unraid service for connection to servers and for server control.
_Avoid_: local API
