"""Yuelly 集成的 Number 平台 (数字输入实体)."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.const import Platform

from .const import DOMAIN, LOGGER
from .coordinator import YuellyDataCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """从配置项设置 Number 平台。"""

    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: YuellyDataCoordinator = data["coordinator"]

    # 1. 告诉协调器如何动态添加实体
    coordinator.set_entity_adder(Platform.NUMBER, async_add_entities)

    # 2. 首次加载时，基于协调器已知的设备 ID 来创建实体
    entities = []
    for device_id, device_data in coordinator.data.items():
        # 仅当设备数据中包含 'setTemp' 字段时才创建
        if device_data.get("setTemp") is not None:
            entities.append(YuellyTemperatureNumber(coordinator, device_id))

    async_add_entities(entities)


# ----------------------------------------------------------------------
# 温度设置实体 (Temperature Setpoint Entity)
# ----------------------------------------------------------------------
class YuellyTemperatureNumber(NumberEntity):
    """代表 Yuelly 设备温度设置值的 Number 实体。"""

    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = "°C"

    def __init__(self, coordinator: YuellyDataCoordinator, device_id: str):
        """初始化实体。"""
        self.coordinator = coordinator
        self.client = coordinator.client
        self._device_id = device_id

        self._device_data = coordinator.data.get(device_id, {})

        self._attr_name = f"{device_id} Set Temperature"
        self._attr_unique_id = f"{DOMAIN}_{device_id}_set_temperature"

    @property
    def device_info(self) -> DeviceInfo:
        """返回设备信息，用于分组。"""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._device_id,
            manufacturer="Yuelly",
            model="",
        )

    @property
    def available(self) -> bool:
        """返回设备的可用性 (onLine 状态)。"""
        # 确保只有在线时才能控制
        return self._device_data.get("onLine", 0) == 1

    @property
    def native_value(self) -> float | None:
        """返回当前设置温度的值。"""
        set_temp_str = self._device_data.get("setTemp")
        if set_temp_str is not None:
            try:
                return float(set_temp_str)
            except ValueError:
                LOGGER.warning(
                    f"setTemp value '{set_temp_str}' for device {self._device_id} is not a valid number."
                )
        return None

    @property
    def native_min_value(self) -> float:
        """返回最小设置温度（从设备数据中获取）。"""
        min_str = self._device_data.get("min", "15")
        try:
            return float(min_str)
        except ValueError:
            return 15.0

    @property
    def native_max_value(self) -> float:
        """返回最大设置温度（从设备数据中获取）。"""
        max_str = self._device_data.get("max", "65")
        try:
            return float(max_str)
        except ValueError:
            return 65.0

    @property
    def native_step(self) -> float:
        """设置步长，默认为 1.0"""
        return 1.0

    async def async_set_native_value(self, value: float) -> None:
        """设置新的温度值，并发送命令。"""

        protocal_value = self._device_data.get("protocal", 0)
        status_value = self._device_data.get("status", 0)

        mode_value = self._device_data.get("mode", "")
        # 强制转换为整数，以匹配通常的设置温度命令格式
        command = {
            "type": "command",
            "data": {
                "id": self._device_id,
                "setTemp": int(value),
                "protocal": protocal_value,
                "currentStatus": status_value,
                "currentMode": mode_value,
                "type": "temp",
            },
        }

        success = await self.client.send_command(command)

        if success:
            LOGGER.info(
                f"Command to set temp for device {self._device_id} to {int(value)} sent."
            )
            # 乐观更新
            self._device_data["setTemp"] = str(int(value))
            self.async_write_ha_state()
        else:
            LOGGER.error(
                f"Failed to send set temp command for device {self._device_id}."
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """协调器通知数据更新时调用。"""
        new_data = self.coordinator.data.get(self._device_id, {})

        if self._device_data != new_data:
            self._device_data = new_data
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """实体首次添加到 HA 时调用。"""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self.async_write_ha_state()
