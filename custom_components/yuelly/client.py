"""Yuelly TCP Client 模块，负责所有网络通信和数据管理。"""

import asyncio
import json
from typing import Optional, TYPE_CHECKING
from asyncio import TimerHandle

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .const import (
    LOGGER,
    TCP_TIMEOUT,
    RECONNECT_DELAY,
    HEARTBEAT_INTERVAL,
    MESSAGE_DELIMITER,
    BUFFER_SIZE,
)

# 延迟导入 DataUpdateCoordinator 以防万一
if TYPE_CHECKING:
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


class YuellyClient:
    """管理 Yuelly TCP 连接、心跳和数据接收的客户端类."""

    # 【修改 1】新增 token 参数到初始化签名中
    def __init__(self, hass: HomeAssistant, host: str, port: int, token: str = None):
        """初始化客户端."""
        self.hass = hass
        self._host = host
        self._port = port
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._is_running = True

        # 【修改 2】存储 token
        self._token = token

        self._reconnect_task: Optional[TimerHandle] = None
        self._heartbeat_task: Optional[TimerHandle] = None
        self._listen_task: Optional[asyncio.Task] = None

        self._buffer = b""
        self.data = {}
        self.coordinator: Optional["DataUpdateCoordinator"] = None  # 添加协调器引用
        LOGGER.debug(f"YuellyClient initialized for {self._host}:{self._port}")

    def set_update_coordinator(self, coordinator):
        """设置数据更新协调器引用。"""
        self.coordinator = coordinator

    # --- 【新增】发送命令方法 ---
    async def send_command(self, command: dict) -> bool:
        """格式化命令为 JSON 并通过 TCP 发送。"""
        if not self._writer or not self._is_running:
            LOGGER.warning("Attempted to send command, but connection is not active.")
            return False

        try:
            # 1. 在命令中添加 token (如果协议要求)
            command_with_token = command.copy()
            if self._token:
                command_with_token["token"] = self._token

            # 2. 序列化 JSON 命令并添加分隔符
            message_str = json.dumps(command_with_token)
            message_bytes = message_str.encode("utf-8") + MESSAGE_DELIMITER

            # 3. 发送数据
            self._writer.write(message_bytes)
            await self._writer.drain()
            LOGGER.debug(f"Command sent successfully: {message_str}")
            return True

        except Exception as e:
            LOGGER.error(f"Error sending command: {e}")
            return False

    # --- 连接管理 (保持不变) ---
    async def connect(self):
        """尝试建立 TCP 连接，并启动监听和心跳."""
        if not self._is_running:
            return

        LOGGER.info(f"Attempting connection to {self._host}:{self._port}...")

        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=TCP_TIMEOUT,
            )
            LOGGER.info("Connection established successfully.")

            # 清理重连定时器
            if self._reconnect_task:
                if isinstance(self._reconnect_task, TimerHandle):
                    self._reconnect_task.cancel()
                self._reconnect_task = None
            if self._heartbeat_task:
                if isinstance(self._heartbeat_task, TimerHandle):
                    self._heartbeat_task.cancel()
                self._heartbeat_task = None

            self._listen_task = self.hass.async_create_task(self._listen())
            self._start_heartbeat()
            return True

        except (ConnectionRefusedError, asyncio.TimeoutError, OSError) as err:
            LOGGER.warning(f"Connection failed: {err}. Retrying in {RECONNECT_DELAY}s.")
            self._schedule_reconnect()
            return False

    def _schedule_reconnect(self):
        """调度一个断线重连任务 (用于 connect 失败的 except 块)。"""
        if self._reconnect_task:
            if isinstance(self._reconnect_task, TimerHandle):
                self._reconnect_task.cancel()

        self._reconnect_task = None

        LOGGER.debug(f"Scheduling reconnection attempt in {RECONNECT_DELAY} seconds.")

        self._reconnect_task = async_call_later(
            self.hass, RECONNECT_DELAY, self._handle_reconnect
        )

    async def _handle_reconnect(self, _):
        """处理定时器触发的重连."""
        LOGGER.info("Reconnect timer triggered. Attempting to connect now.")
        await self.connect()

    async def _close_connection(self):
        """关闭 TCP 连接并清理相关任务."""
        if self._listen_task:
            self._listen_task.cancel()
            self._listen_task = None

        if self._heartbeat_task:
            if isinstance(self._heartbeat_task, TimerHandle):
                self._heartbeat_task.cancel()
        self._heartbeat_task = None

        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as e:
                LOGGER.debug(f"Error closing writer: {e}")
            finally:
                self._reader = None
                self._writer = None

    async def _handle_disconnect(self):
        """处理连接断开后的清理和重连调度。"""
        if not self._is_running:
            return

        # 1. **关键：** 在清理之前，先调度重连任务
        if self._is_running:
            LOGGER.warning(
                f"Scheduling direct connection attempt in {RECONNECT_DELAY} seconds."
            )

            # 使用 async_add_job 强制调度 async_call_later
            # 注意: 这里应该直接使用 async_call_later，它会在主线程中调度 _handle_reconnect
            self._reconnect_task = async_call_later(
                self.hass, RECONNECT_DELAY, self._handle_reconnect
            )

        # 2. 清理连接和任务 (位于调度之后)
        LOGGER.warning("Handling connection disconnect: Initiating cleanup now.")
        await self._close_connection()

    # --- 数据接收与处理 ---

    async def _listen(self):
        """在连接成功后，循环监听数据。"""
        LOGGER.debug("Starting TCP listen loop.")
        reconnect_needed = False
        try:
            while self._is_running and self._reader:
                # 监听数据
                data = await self._reader.read(BUFFER_SIZE)

                if not data:
                    LOGGER.warning(
                        "Connection closed by server. Initiating disconnect handler."
                    )
                    reconnect_needed = True
                    break

                self._buffer += data
                self._process_buffer()

        except asyncio.IncompleteReadError:
            LOGGER.warning("Incomplete read error during listen.")
            reconnect_needed = True
        except ConnectionResetError:
            LOGGER.warning("Connection reset by peer.")
            reconnect_needed = True
        except Exception as e:
            LOGGER.error(f"Error during listening: {e.__class__.__name__}: {e}.")
            reconnect_needed = True
        finally:
            pass

        # 任务结束后，如果需要重连，则调用处理程序
        if reconnect_needed:
            await self._handle_disconnect()

    def _process_buffer(self):
        """从缓冲区中提取并处理完整消息，解析 JSON 数据。"""

        while MESSAGE_DELIMITER in self._buffer:
            message_part, self._buffer = self._buffer.split(MESSAGE_DELIMITER, 1)

            try:
                message_str = message_part.decode("utf-8", errors="ignore").strip()
                # 尝试解析 JSON
                message_json = json.loads(message_str)
                LOGGER.debug(f"Received and decoded JSON message: {message_json}")
                if message_json.get("type") == "device":
                    self._handle_device_data(message_json.get("data", []))

                # TODO: 添加其他类型的消息处理

            except json.JSONDecodeError as e:
                LOGGER.error(
                    f"JSON decode error: {e} for message: {message_str[:50]}..."
                )
            except Exception as e:
                LOGGER.error(f"Error processing message part: {e}", exc_info=True)

    def _handle_device_data(self, device_list: list):
        """将解析后的设备状态数据存储到 self.data 中，并通知 HA 更新。"""
        data_changed = False

        for device in device_list:
            device_id = device.get("id")
            if device_id:
                # 检查数据是否真的有变化
                if self.data.get(device_id) != device:
                    self.data[device_id] = device
                    data_changed = True

        # 触发协调器更新
        if data_changed and self.coordinator:
            try:
                # 确保协调器通知不会因为任何异常而中断客户端消息循环
                self.coordinator.notify_data_received()
            except Exception as e:
                LOGGER.error(
                    f"Error notifying coordinator of data update: {e}", exc_info=True
                )

    # --- 心跳机制 ---

    def _start_heartbeat(self):
        """启动心跳定时器。"""
        if self._heartbeat_task:
            if isinstance(self._heartbeat_task, TimerHandle):
                self._heartbeat_task.cancel()
            self._heartbeat_task = None

        self._heartbeat_task = async_call_later(
            self.hass, HEARTBEAT_INTERVAL, self._send_heartbeat_wrapper
        )

    async def _send_heartbeat_wrapper(self, _):
        """发送心跳并调度下一次心跳。"""
        try:
            await self.send_heartbeat()
        except Exception as e:
            LOGGER.warning(f"Error sending heartbeat: {e}")

        if self._is_running and self._writer:
            self._start_heartbeat()

    async def send_heartbeat(self):
        """实际发送心跳消息。"""
        if self._writer and self._is_running and self.coordinator:
            device_ids = self.coordinator.get_known_device_protocols()

            # 【修改 3】在心跳数据中包含 token
            heartbeat_data = {"type": "heartbeatToken", "device_data": device_ids}
            if self._token:
                heartbeat_data["token"] = self._token

            message_str = json.dumps(heartbeat_data)
            heartbeat_msg = message_str.encode("utf-8") + MESSAGE_DELIMITER

            self._writer.write(heartbeat_msg)
            await self._writer.drain()
            LOGGER.debug("Heartbeat PING sent.")
            return True
        return False

    # --- 停止/清理 ---

    async def shutdown(self):
        """停止客户端并关闭所有任务和连接。"""
        LOGGER.info("Shutting down Yuelly Client.")
        self._is_running = False

        if self._reconnect_task:
            if isinstance(self._reconnect_task, TimerHandle):
                self._reconnect_task.cancel()
        if self._heartbeat_task:
            if isinstance(self._heartbeat_task, TimerHandle):
                self._heartbeat_task.cancel()

        await self._close_connection()
