"""Yuelly 集成的 Switch 平台 (开关实体)."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, LOGGER
from .coordinator import YuellyDataCoordinator  # 导入协调器

# ----------------------------------------------------------------------
# 实体设置 (Setup)
# ----------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """从配置项设置 Switch 平台。"""

    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: YuellyDataCoordinator = data["coordinator"]  # 确保从字典中获取

    # 1. 告诉协调器如何动态添加实体
    coordinator.set_entity_adder("switch", async_add_entities)  # 必须调用此方法

    # 2. 首次获取数据并订阅更新
    await coordinator.async_config_entry_first_refresh()

    # 3. 基于 client.data 创建实体
    entities = []
    for device_id in coordinator._known_device_ids:
        entities.append(YuellySwitch(coordinator, device_id))

    async_add_entities(entities)


# ----------------------------------------------------------------------
# 开关实体 (Switch Entity)
# ----------------------------------------------------------------------
class YuellySwitch(SwitchEntity):
    """代表 Yuelly 设备开关机状态的 Switch 实体。"""

    # ... (YuellySwitch 类保持不变) ...
    def __init__(self, coordinator: YuellyDataCoordinator, device_id: str):
        """初始化实体。"""
        self.coordinator = coordinator
        self._device_id = device_id
        self.client = coordinator.client
        # 从协调器引用的数据中获取当前设备状态
        self._device_data = coordinator.data.get(device_id, {})

        self._attr_name = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_switch"

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
    def is_on(self) -> bool:
        """返回开关的状态。"""
        return self._device_data.get("status", 0) == 1

    async def async_turn_on(self, **kwargs) -> None:
        """打开设备。"""
        LOGGER.info(f"Turning ON device {self._device_id}")
        protocal_value = self._device_data.get("protocal", 0)
        status_value = self._device_data.get("status", 0)
        mode_value = self._device_data.get("mode", "")
        command = {
            "type": "command",
            "data": {
                "id": self._device_id,
                "status": 1,
                "protocal": protocal_value,
                "currentStatus": status_value,
                "currentMode": mode_value,
                "type": "status",
            },
        }

        success = await self.client.send_command(command)

        if success:
            LOGGER.info(f"Command to turn ON device {self._device_id} sent.")
            # 乐观更新 (Optimistic update)：假设命令发送成功，立即更新 HA 状态
            self._device_data["status"] = 1
            self.async_write_ha_state()
        else:
            LOGGER.error(
                f"Failed to send turn ON command for device {self._device_id}. HA state remains unchanged."
            )

    async def async_turn_off(self, **kwargs) -> None:
        """关闭设备。"""
        LOGGER.info(f"Turning OFF device {self._device_id}")
        protocal_value = self._device_data.get("protocal", 0)
        status_value = self._device_data.get("status", 0)
        mode_value = self._device_data.get("mode", "")
        command = {
            "type": "command",
            "data": {
                "id": self._device_id,
                "status": 0,
                "protocal": protocal_value,
                "currentStatus": status_value,
                "currentMode": mode_value,
                "type": "status",
            },
        }

        success = await self.client.send_command(command)

        if success:
            LOGGER.info(f"Command to turn OFF device {self._device_id} sent.")
            # 乐观更新 (Optimistic update)
            self._device_data["status"] = 0
            self.async_write_ha_state()
        else:
            LOGGER.error(
                f"Failed to send turn OFF command for device {self._device_id}. HA state remains unchanged."
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
