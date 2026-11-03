"""Vulkan device inspection used by AI-upscaler preflight.

Real-ESRGAN's ncnn-vulkan binary can enumerate a software Vulkan device such
as llvmpipe. That proves the Vulkan loader works, not that a usable GPU is
available. This probe deliberately distinguishes hardware from CPU drivers.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from functools import lru_cache
from typing import Any

_SOFTWARE_TOKENS = (
    "llvmpipe",
    "lavapipe",
    "swiftshader",
    "softpipe",
    "swrast",
    "software rasterizer",
)


def parse_vulkan_summary(output: str) -> dict[str, Any]:
    """Parse vulkaninfo summary text and classify enumerated physical devices."""
    if not isinstance(output, str) or not output.strip():
        return {"status": "no_device", "reason": "vulkaninfo returned no device summary", "devices": []}

    starts = list(re.finditer(r"(?m)^GPU\\d+:\\s*$", output))
    blocks: list[str] = []
    if starts:
        for index, match in enumerate(starts):
            end = starts[index + 1].start() if index + 1 < len(starts) else len(output)
            blocks.append(output[match.end():end])
    elif re.search(r"(?m)^\\s*deviceName\\s*=", output):
        blocks = [output]

    devices = []
    for block in blocks:
        def field(name: str) -> str | None:
            match = re.search(rf"(?m)^\\s*{re.escape(name)}\\s*=\\s*(.*?)\\s*$", block)
            return match.group(1).strip() if match else None

        name = field("deviceName") or "unnamed Vulkan device"
        device_type = field("deviceType") or "unknown"
        driver_name = field("driverName") or "unknown"
        driver_info = field("driverInfo") or "unknown"
        fingerprint = " ".join((name, device_type, driver_name, driver_info)).lower()
        software = "physical_device_type_cpu" in device_type.lower() or any(
            token in fingerprint for token in _SOFTWARE_TOKENS
        )
        devices.append({
            "device_name": name,
            "device_type": device_type,
            "driver_name": driver_name,
            "driver_info": driver_info,
            "software": software,
        })

    if not devices:
        return {
            "status": "no_device",
            "reason": "vulkaninfo completed but did not report a physical device",
            "devices": [],
        }

    hardware = [device for device in devices if not device["software"]]
    if hardware:
        return {
            "status": "hardware_available",
            "reason": f"{len(hardware)} hardware-backed Vulkan device(s) detected",
            "devices": devices,
        }
    names = ", ".join(device["device_name"] for device in devices)
    return {
        "status": "software_only",
        "reason": f"Vulkan exposes only CPU/software device(s): {names}",
        "devices": devices,
    }


@lru_cache(maxsize=1)
def inspect_vulkan_hardware() -> dict[str, Any]:
    """Return cached hardware/software Vulkan state without guessing from device files."""
    executable = shutil.which("vulkaninfo")
    if not executable:
        return {
            "status": "probe_unavailable",
            "reason": "vulkaninfo is not installed or is not on PATH",
            "devices": [],
        }
    try:
        result = subprocess.run(
            [executable, "--summary"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "probe_timeout",
            "reason": "vulkaninfo exceeded its 15-second diagnostic timeout",
            "devices": [],
        }
    except OSError as exc:
        return {
            "status": "probe_failed",
            "reason": f"Could not execute vulkaninfo: {exc}",
            "devices": [],
        }
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown Vulkan probe error").strip()[-800:]
        return {
            "status": "probe_failed",
            "reason": f"vulkaninfo exited with code {result.returncode}: {detail}",
            "devices": [],
        }
    return parse_vulkan_summary(result.stdout or "")
