"""Constants for Unraid API state values and configuration."""

from __future__ import annotations

# =============================================================================
# Version Requirements
# =============================================================================

MIN_API_VERSION = "4.31.1"
# Feature threshold, not a compatibility minimum: https://github.com/unraid/api/pull/2091
MIN_STANDBY_SAFE_TEMPERATURE_API_VERSION = "4.37.6"
MIN_UNRAID_VERSION = "7.2.4"

# =============================================================================
# Docker Container States
# =============================================================================

CONTAINER_STATE_RUNNING = "running"
CONTAINER_STATE_STOPPED = "stopped"
CONTAINER_STATE_PAUSED = "paused"
CONTAINER_STATE_EXITED = "exited"
CONTAINER_STATE_CREATED = "created"
CONTAINER_STATE_RESTARTING = "restarting"
CONTAINER_STATE_DEAD = "dead"

# =============================================================================
# VM Domain States
# =============================================================================

VM_STATE_RUNNING = "running"
VM_STATE_IDLE = "idle"
VM_STATE_PAUSED = "paused"
VM_STATE_SHUT_OFF = "shutoff"
VM_STATE_PMSUSPENDED = "pmsuspended"
VM_STATE_CRASHED = "crashed"

# =============================================================================
# Array Disk States
# =============================================================================

DISK_STATUS_OK = "DISK_OK"
DISK_STATUS_DISABLED = "DISK_DSBL"
DISK_STATUS_DSBL_NEW = "DISK_DSBL_NEW"
DISK_STATUS_NP = "DISK_NP"
DISK_STATUS_NP_DSBL = "DISK_NP_DSBL"
DISK_STATUS_NP_MISSING = "DISK_NP_MISSING"
DISK_STATUS_WRONG = "DISK_WRONG"
DISK_STATUS_NEW = "DISK_NEW"

# =============================================================================
# Parity Check States
# =============================================================================

PARITY_STATUS_RUNNING = "RUNNING"
PARITY_STATUS_PAUSED = "PAUSED"
PARITY_STATUS_FAILED = "FAILED"
PARITY_STATUS_IDLE = "IDLE"

# =============================================================================
# UPS States
# =============================================================================

UPS_STATUS_ONLINE = "ONLINE"
UPS_STATUS_ON_BATTERY = "ONBATT"
UPS_STATUS_OFFLINE = "OFFLINE"
UPS_STATUS_LOW_BATTERY = "LOWBATT"

# =============================================================================
# Array States
# =============================================================================

ARRAY_STATE_STARTED = "STARTED"
ARRAY_STATE_STOPPED = "STOPPED"
ARRAY_STATE_NEW = "NEW_ARRAY"
