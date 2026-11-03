import unittest
from unittest.mock import patch

from src.heyaa.gpu import inspect_vulkan_hardware, parse_vulkan_summary


class VulkanProbeTests(unittest.TestCase):
    def tearDown(self):
        inspect_vulkan_hardware.cache_clear()

    def test_llvmpipe_is_classified_as_software_only(self):
        summary = """Devices:
========
GPU0:
    deviceType = PHYSICAL_DEVICE_TYPE_CPU
    deviceName = llvmpipe (LLVM 20.1.2, 256 bits)
    driverName = llvmpipe
    driverInfo = Mesa 25.2.8
"""
        result = parse_vulkan_summary(summary)
        self.assertEqual(result["status"], "software_only")
        self.assertEqual(result["devices"][0]["device_name"], "llvmpipe (LLVM 20.1.2, 256 bits)")

    def test_radeon_hardware_device_is_classified_as_available(self):
        summary = """Devices:
========
GPU0:
    deviceType = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
    deviceName = AMD Radeon RX 540 Series
    driverName = DRIVER_ID_MESA_RADV
    driverInfo = Mesa 25.2.8
"""
        result = parse_vulkan_summary(summary)
        self.assertEqual(result["status"], "hardware_available")
        self.assertFalse(result["devices"][0]["software"])

    def test_probe_reports_missing_vulkaninfo_without_claiming_gpu_absence(self):
        with patch("src.heyaa.gpu.shutil.which", return_value=None):
            result = inspect_vulkan_hardware()
        self.assertEqual(result["status"], "probe_unavailable")
        self.assertIn("not installed", result["reason"])

    def test_probe_classifies_actual_vulkan_summary(self):
        summary = """GPU0:
    deviceType = PHYSICAL_DEVICE_TYPE_CPU
    deviceName = llvmpipe
    driverName = llvmpipe
"""
        with patch("src.heyaa.gpu.shutil.which", return_value="/usr/bin/vulkaninfo"), patch(
            "src.heyaa.gpu.subprocess.run",
            return_value=type("Result", (), {"returncode": 0, "stdout": summary, "stderr": ""})(),
        ):
            result = inspect_vulkan_hardware()
        self.assertEqual(result["status"], "software_only")


if __name__ == "__main__":
    unittest.main()
