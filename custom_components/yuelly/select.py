"""Yuelly 集成的 Select 平台 (模式选择实体)."""

from homeassistant.components.select import SelectEntity
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
    """从配置项设置 Select 平台。"""

    data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: YuellyDataCoordinator = data["coordinator"]

    # 1. 告诉协调器如何动态添加实体
    coordinator.set_entity_adder(Platform.SELECT, async_add_entities)

    # 2. 首次加载时，基于协调器已知的设备 ID 来创建实体
    entities = []
    for device_id, device_data in coordinator.data.items():
        # 仅当设备数据中包含 'mode' 和 'modeList' 字段时才创建
        if (
            device_data.get("mode") is not None
            and device_data.get("modeList") is not None
        ):
            entities.append(YuellyModeSelect(coordinator, device_id))

    async_add_entities(entities)


# ----------------------------------------------------------------------
# 模式选择实体 (Mode Select Entity)
# ----------------------------------------------------------------------
class YuellyModeSelect(SelectEntity):
    """代表 Yuelly 设备操作模式选择的 Select 实体。"""

    def __init__(self, coordinator: YuellyDataCoordinator, device_id: str):
        """初始化实体。"""
        self.coordinator = coordinator
        self.client = coordinator.client
        self._device_id = device_id

        self._device_data = coordinator.data.get(device_id, {})

        self._attr_name = f"{device_id} Mode Selection"
        self._attr_unique_id = f"{DOMAIN}_{device_id}_mode_selection"

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
        # 模式选择只有在设备在线时才可用
        return self._device_data.get("onLine", 0) == 1

    @property
    def current_option(self) -> str | None:
        """返回当前选中的模式。"""
        return self._device_data.get("mode")

    @property
    def options(self) -> list[str]:
        """返回所有可选的模式列表。"""
        # 确保返回一个列表，如果 modeList 不存在则返回空列表
        return self._device_data.get("modeList", [])

    async def async_select_option(self, option: str) -> None:
        """发送命令以切换到选定的模式。"""

        protocal_value = self._device_data.get("protocal", 0)

        status_value = self._device_data.get("status", 0)

        mode_value = self._device_data.get("mode", "")

        # 构建设置模式的命令
        command = {
            "type": "command",
            "data": {
                "id": self._device_id,
                "mode": option,  # 使用用户选择的模式
                "protocal": protocal_value,
                "currentStatus": status_value,
                "currentMode": mode_value,
                "type": "mode",
            },
        }

        success = await self.client.send_command(command)

        if success:
            LOGGER.info(
                f"Command to set mode for device {self._device_id} to {option} sent."
            )
            # 乐观更新
            self._device_data["mode"] = option
            self.async_write_ha_state()
        else:
            LOGGER.error(
                f"Failed to send set mode command for device {self._device_id}."
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
