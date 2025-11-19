"""Adds config flow for Yuelly integration, handling username/password authentication and token retrieval."""

from __future__ import annotations

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession


from .const import (
    DOMAIN,
    LOGGER,
    AUTH_URL,  # HTTP 认证地址
    DEFAULT_HOST,  # 默认连接主机
    DEFAULT_PORT,  # 默认连接端口
)

# --- 自定义常量 (用于存储配置的键名) ---
CONF_TOKEN = "token"
CONF_HOST = "host"
CONF_PORT = "port"


# --- 占位符/异常 ---
class AuthException(Exception):
    """认证失败异常，对应配置流程中的 'auth' 错误。"""


class ConnectionException(Exception):
    """连接通信失败异常，对应配置流程中的 'connection' 错误。"""


class YuellyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Yuelly."""

    VERSION = 1

    # 关键：如果 API 不返回 unique_id，我们使用一个固定的 ID，限制只能有一个配置条目。
    SINGLE_INSTANCE_UNIQUE_ID = f"{DOMAIN}_single_account"

    async def async_step_user(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """处理用户启动的配置流程."""
        _errors = {}
        if user_input is not None:
            try:
                # 尝试验证凭证并获取 Token 和连接信息
                info = await self._login_and_get_token(self.hass, user_input)

            except AuthException as e:
                # Log the specific error message returned by the API (中文日志)
                LOGGER.warning("认证失败: %s", e)
                _errors["base"] = "auth"
            except ConnectionException as e:
                LOGGER.error("连接失败: %s", e)
                _errors["base"] = "connection"
            except Exception as exception:
                LOGGER.exception("登录过程中发生意外错误: %s", exception)
                _errors["base"] = "unknown"
            else:
                # 认证成功，设置固定的唯一 ID，限制只能配置一次
                await self.async_set_unique_id(self.SINGLE_INSTANCE_UNIQUE_ID)
                self._abort_if_unique_id_configured()

                # 构造要存储在配置条目中的数据 (只存储 username, token, host, port)
                data_to_store = {
                    CONF_USERNAME: user_input[
                        CONF_USERNAME
                    ],  # 保留 username 用于显示标题
                    CONF_TOKEN: info[CONF_TOKEN],
                    CONF_HOST: info[CONF_HOST],
                    CONF_PORT: info[CONF_PORT],
                }

                # 配置条目的标题将使用用户输入的用户名
                title = f"Yuelly ({user_input[CONF_USERNAME]})"

                return self.async_create_entry(
                    title=title,
                    data=data_to_store,
                )

        # 构造用户输入表单
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=(user_input or {}).get(CONF_USERNAME, vol.UNDEFINED),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                        ),
                    ),
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                        ),
                    ),
                },
            ),
            errors=_errors,
        )

    async def _login_and_get_token(self, hass: HomeAssistant, user_input: dict) -> dict:
        """
        验证凭证，通过 HTTP 接口获取 Token 和连接信息。

        @return: Dict containing "token", "host", and "port".
        @raises AuthException: 认证失败。
        @raises ConnectionException: 网络或 API 格式错误。
        """
        username = user_input[CONF_USERNAME]
        password = user_input[CONF_PASSWORD]

        session = async_create_clientsession(hass)
        data = None

        try:
            # 1. 调用登录 API
            response = await session.post(
                AUTH_URL,
                json={"username": username, "password": password},
                timeout=10,  # 设置超时
            )

            # 2. 检查 HTTP 状态码
            response.raise_for_status()

            # 3. 解析 JSON 数据
            data = await response.json()

        except aiohttp.ClientConnectorError as err:
            raise ConnectionException("无法连接到认证服务器。") from err
        except aiohttp.ClientResponseError as err:
            raise ConnectionException(f"服务器返回 HTTP 错误: {err.status}。") from err
        except aiohttp.ClientError as err:
            raise ConnectionException("网络请求失败。") from err
        except Exception as err:
            raise ConnectionException("API 响应格式错误。") from err

        # --- 4. 解析业务逻辑状态 ---

        api_status = data.get("status")
        response_data = data.get("data", {})

        if api_status != 1:
            # 状态不为 1，则视为认证失败
            error_msg = response_data.get("errorMsg", "未知认证错误。")
            # 抛出包含具体错误信息的 AuthException
            raise AuthException(error_msg)

        # 状态为 1，检查核心数据字段
        token = response_data.get(CONF_TOKEN)

        # 必须确保 API 返回了 Token
        if not token:
            LOGGER.error("API 返回状态 1 但缺少 token 字段: %s", data)
            raise AuthException("API 响应缺少 'token' 字段。")

        # 5. 提取设备连接信息
        device_host = response_data.get(CONF_HOST, DEFAULT_HOST)
        device_port = response_data.get(CONF_PORT, DEFAULT_PORT)

        # 6. 返回所需的核心数据
        return {
            CONF_TOKEN: token,
            CONF_HOST: device_host,
            CONF_PORT: device_port,
        }
