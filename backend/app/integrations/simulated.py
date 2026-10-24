"""Simulated device integration for testing"""

import time
from datetime import UTC, datetime
from typing import Any

from .base import DeviceCommand, DeviceIntegration, DeviceState, IntegrationResult


class SimulatedIntegration(DeviceIntegration):
    """Simulated integration for testing without real devices"""

    @property
    def name(self) -> str:
        return "simulated"

    @property
    def type(self) -> str:
        return "simulated"

    def __init__(self):
        self._devices: dict[str, dict[str, Any]] = {}
        self._device_id = 1
        self._started = time.monotonic()

    def add_device(self, device: dict[str, Any]):
        """Add a simulated device"""
        device_id = f"sim_{self._device_id}"
        self._devices[device_id] = {
            **device,
            "is_online": True,
            "last_updated": datetime.now(UTC).isoformat(),
        }
        self._device_id += 1

    async def discover_devices(self) -> list[dict[str, Any]]:
        """Discover simulated devices"""
        return list(self._devices.values())

    async def get_device_state(self, device_id: str) -> DeviceState:
        """Get device state"""
        if device_id not in self._devices:
            raise ValueError(f"Device {device_id} not found")

        device = self._devices[device_id]
        state = DeviceState(
            on=device.get("is_on", False),
            brightness=device.get("brightness", 100),
            color_temp=device.get("color_temp"),
            color=device.get("color"),
            mode=device.get("mode"),
            temperature=device.get("temperature"),
            target_temperature=device.get("target_temperature"),
            fan_mode=device.get("fan_mode"),
            humidity=device.get("humidity"),
            target_humidity=device.get("target_humidity"),
            is_online=device.get("is_online", True),
            last_updated=device.get("last_updated"),
        )

        return state

    async def send_command(
        self, device_id: str, command: DeviceCommand
    ) -> IntegrationResult:
        """Send command to device"""
        if device_id not in self._devices:
            return IntegrationResult(
                success=False,
                message=f"Device {device_id} not found",
                error="Device not found",
            )

        # Simulate command execution
        import uuid

        result_id = str(uuid.uuid4())

        return IntegrationResult(
            success=True,
            message=f"Command {command.command} sent to device {device_id}",
            data={"result_id": result_id},
        )

    async def check_health(self) -> dict[str, Any]:
        """Check integration health"""
        return {
            "status": "healthy",
            "name": self.name,
            "device_count": len(self._devices),
            "uptime_seconds": int(time.monotonic() - self._started),
        }


# Register simulated integration
simulated = SimulatedIntegration()
