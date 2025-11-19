"""Constants for Yuelly."""

from homeassistant.const import Platform
from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "yuelly"
ATTRIBUTION = "Data provided by http://www.mini-clouds.com/"
# --- 连接配置和协议常量 ---
TCP_TIMEOUT = 10
RECONNECT_DELAY = 60
HEARTBEAT_INTERVAL = 6
MESSAGE_DELIMITER = b"$$##"
BUFFER_SIZE = 4096
# 【新增】默认连接信息
DEFAULT_HOST = "www.mini-clouds.com"
DEFAULT_PORT = 19999
AUTH_URL = "http://www.mini-clouds.com:8081/yuellyBoard/user/haLogin"


PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
]
