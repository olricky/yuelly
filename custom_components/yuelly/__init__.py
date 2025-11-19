"""Yuelly 集成的 Home Assistant 入口文件"""

import asyncio
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME  # 导入 CONF_USERNAME

# 【新增】导入配置流程中定义的存储键
from .config_flow import CONF_TOKEN, CONF_HOST, CONF_PORT

from .const import DOMAIN, LOGGER, PLATFORMS
from .client import YuellyClient
from .coordinator import YuellyDataCoordinator


async def async_setup(hass: HomeAssistant, config: dict):
    """设置 Yuelly 集成 (配置加载前)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """从配置项加载集成"""
    LOGGER.debug("Setting up component Yuelly from config entry.")

    # 【修改】从 entry.data 中读取配置条目存储的所有数据
    token = entry.data[CONF_TOKEN]
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]

    # 1. 实例化客户端，【关键：传入 token】
    # ⚠️ 必须确保 YuellyClient 的 __init__ 已更新以接受 token 参数
    client = YuellyClient(hass, host=host, port=port, token=token)

    # 2. 实例化协调器
    coordinator = YuellyDataCoordinator(hass, client)

    # 3. 将客户端和协调器存储在 hass.data 中
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    # 4. 启动 TCP 连接任务
    # client.connect() 现在可以使用存储的 token 进行连接或认证
    hass.async_create_task(client.connect())

    # 5. 转发到平台（switch, sensor 等）
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """卸载集成配置项"""
    LOGGER.debug("Unloading component Yuelly.")

    # 1. 卸载所有平台
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # 2. 关闭客户端连接和任务
    if unload_ok and entry.entry_id in hass.data[DOMAIN]:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        client: YuellyClient = data["client"]  # 从字典中取出 client
        await client.shutdown()

    return unload_ok
