"""Yuelly 集成的 Sensor 平台 (传感器实体)."""

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import UnitOfTemperature
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
    """从配置项设置 Sensor 平台。"""

    data = hass.data[DOMAIN][config_entry.entry_id]
    # 从 hass.data 中获取协调器实例
    coordinator: YuellyDataCoordinator = data["coordinator"]

    # 1. 告诉协调器如何动态添加实体 (传入平台名称 "sensor")
    coordinator.set_entity_adder(Platform.SENSOR, async_add_entities)

    # 2. 首次加载时，基于协调器已知的设备 ID 来创建 Sensor 实体
    entities = []
    for device_id, device_data in coordinator.data.items():
        # 仅当设备数据中包含 'temp' 字段时才创建传感器
        if device_data.get("temp") is not None:
            entities.append(YuellyTemperatureSensor(coordinator, device_id))

    async_add_entities(entities)


# ----------------------------------------------------------------------
# 温度传感器实体 (Temperature Sensor Entity)
# ----------------------------------------------------------------------
class YuellyTemperatureSensor(SensorEntity):
    """代表 Yuelly 设备温度的 Sensor 实体。"""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: YuellyDataCoordinator, device_id: str):
        """初始化实体。"""
        self.coordinator = coordinator
        self._device_id = device_id

        # 从协调器引用的数据中获取当前设备状态
        self._device_data = coordinator.data.get(device_id, {})

        self._attr_name = f"{device_id} Temperature"
        self._attr_unique_id = f"{DOMAIN}_{device_id}_temperature_sensor"

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
        return self._device_data.get("onLine", 0) == 1

    @property
    def native_value(self) -> float | None:
        """返回温度的当前值。"""
        temp_str = self._device_data.get("temp")
        if temp_str is not None:
            try:
                # 温度字段是字符串，需要转换为浮点数
                return float(temp_str)
            except ValueError:
                LOGGER.warning(
                    f"Temperature value '{temp_str}' for device {self._device_id} is not a valid number."
                )
        return None

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
