"""Yuelly 集成的数据更新协调器。"""

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.const import Platform
from typing import Callable, Awaitable, Any, Optional, Set, Dict
import asyncio

from .const import DOMAIN, LOGGER
from .client import YuellyClient


# ----------------------------------------------------------------------
# 类型定义
# ----------------------------------------------------------------------

# 定义一个字典来存储不同平台添加实体的方法
# Key: 平台名称 (例如 "switch", "sensor", "number")
# Value: AddEntitiesCallback 函数
AddEntitiesCallbacks = Dict[str, Optional[Callable[[list[Any]], Awaitable[None]]]]


# ----------------------------------------------------------------------
# 协调器类
# ----------------------------------------------------------------------


class YuellyDataCoordinator(DataUpdateCoordinator):
    """管理从 YuellyClient 获取数据的协调器，并处理动态实体发现。"""

    def __init__(self, hass: HomeAssistant, client: YuellyClient):
        """初始化协调器。"""
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=None,
        )
        self.client = client
        self.data = client.data
        # 【核心修改】添加 number 平台的回调槽
        self._async_add_entities: AddEntitiesCallbacks = {
            Platform.SWITCH: None,
            Platform.SENSOR: None,
            Platform.NUMBER: None,
            Platform.SELECT: None,
        }
        self._known_device_ids: Set[str] = set()

        # 确保客户端持有协调器的引用，以便在数据更新时通知
        self.client.set_update_coordinator(self)

    def set_entity_adder(
        self,
        platform: str,
        async_add_entities_func: Callable[[list[Any]], Awaitable[None]],
    ):
        """由各平台调用，设置异步添加实体的回调函数。"""
        self._async_add_entities[platform] = async_add_entities_func
        # 确保启动时协调器已知所有设备，避免重复添加
        self._known_device_ids.update(self.data.keys())

    async def _async_update_data(self):
        """协调器被要求更新数据时调用（仅用于首次加载）。"""
        return self.client.data

    def get_known_device_ids(self) -> list[str]:
        """返回当前协调器已知的所有设备 ID 列表。"""
        # self.data 存储了所有设备的最新状态，key 就是设备ID
        return list(self.data.keys())

    def get_known_device_protocols(self) -> list[dict]:
        """返回mac与protocal"""
        device_data_list = []
        for device_id, device_data in self.data.items():
            # 提取协议号，如果不存在则使用 0 作为默认值
            protocal_value = device_data.get("protocal", 0)
            device_data_list.append({"id": device_id, "protocal": protocal_value})
        return device_data_list

    # 辅助异步方法，用于调度实体添加任务
    async def _async_add_new_entities(
        self, platform: str, new_entities: list[Any]
    ) -> None:
        """异步执行指定平台的实体添加回调。"""
        coro = self._async_add_entities[platform]
        if coro:
            result = coro(new_entities)
            if result is not None:
                await result

    @callback
    def notify_data_received(self):
        """由 YuellyClient 调用，以通知协调器数据已更新。"""

        # 1. 检查是否有新设备需要添加 (动态发现)

        if any(self._async_add_entities.values()):
            # 必须在这里导入实体类，以避免循环依赖问题
            from .switch import YuellySwitch
            from .sensor import YuellyTemperatureSensor
            from .number import YuellyTemperatureNumber
            from .select import YuellyModeSelect

            new_switch_entities = []
            new_sensor_entities = []
            new_number_entities = []
            new_select_entities = []

            for device_id, device_data in self.data.items():
                if device_id not in self._known_device_ids:
                    LOGGER.info(
                        f"Dynamically discovered new device: {device_id}. Adding entities."
                    )

                    # 总是尝试添加 Switch 实体
                    new_switch_entities.append(YuellySwitch(self, device_id))

                    # 检查 'temp' 字段，添加 Sensor 实体
                    if device_data.get("temp") is not None:
                        new_sensor_entities.append(
                            YuellyTemperatureSensor(self, device_id)
                        )

                    if device_data.get("setTemp") is not None:
                        new_number_entities.append(
                            YuellyTemperatureNumber(self, device_id)
                        )
                    if (
                        device_data.get("mode") is not None
                        and device_data.get("modeList") is not None
                    ):
                        new_select_entities.append(YuellyModeSelect(self, device_id))

                    self._known_device_ids.add(device_id)

            # 调度 Switch 实体添加任务
            if new_switch_entities and self._async_add_entities["switch"]:
                self.hass.async_create_task(
                    self._async_add_new_entities("switch", new_switch_entities)
                )

            # 调度 Sensor 实体添加任务
            if new_sensor_entities and self._async_add_entities["sensor"]:
                self.hass.async_create_task(
                    self._async_add_new_entities("sensor", new_sensor_entities)
                )

            # 【新增】调度 Number 实体添加任务
            if new_number_entities and self._async_add_entities["number"]:
                self.hass.async_create_task(
                    self._async_add_new_entities("number", new_number_entities)
                )
            if new_select_entities and self._async_add_entities[Platform.SELECT]:
                self.hass.async_create_task(
                    self._async_add_new_entities(Platform.SELECT, new_select_entities)
                )

        # 2. 通知所有监听者更新现有实体状态
        self.async_set_updated_data(self.data)
