"""Device integration interface"""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class DeviceState(BaseModel):
    """Device state model"""

    on: bool
    brightness: int | None = None
    color_temp: int | None = None
    color: dict[str, float] | None = None
    mode: str | None = None
    temperature: float | None = None
    target_temperature: float | None = None
    fan_mode: str | None = None
    humidity: float | None = None
    target_humidity: float | None = None
    is_online: bool = False
    last_updated: str | None = None


class DeviceCommand(BaseModel):
    """Device command model"""

    command: str
    payload: dict[str, Any] = {}


class IntegrationResult(BaseModel):
    """Integration result"""

    success: bool
    message: str
    data: Any | None = None
    error: str | None = None


class DeviceIntegration(ABC):
    """Abstract base class for device integrations"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Integration name"""

    @property
    @abstractmethod
    def type(self) -> str:
        """Integration type"""

    @abstractmethod
    async def discover_devices(self) -> list[dict[str, Any]]:
        """Discover available devices"""

    @abstractmethod
    async def get_device_state(self, device_id: str) -> DeviceState:
        """Get current device state"""

    @abstractmethod
    async def send_command(
        self, device_id: str, command: DeviceCommand
    ) -> IntegrationResult:
        """Send command to device"""

    @abstractmethod
    async def check_health(self) -> dict[str, Any]:
        """Check integration health"""
