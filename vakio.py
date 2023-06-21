"""Service classes for interacting with Vakio devices"""
from __future__ import annotations
import asyncio
import logging
import random
from typing import Any
import async_timeout
import paho.mqtt.client as mqtt

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from homeassistant.loader import bind_hass

from .const import (
    DEFAULT_TIMEINTERVAL,
    DOMAIN,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_TOPIC,
    CONF_USERNAME,
    OPENAIR_STATE_OFF,
    OPENAIR_STATE_ON,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)

SPEED_ENDPOINT = "speed"
GATE_ENDPOINT = "gate"
STATE_ENDPOINT = "state"
WORKMODE_ENDPOINT = "workmode"
TEMP_ENDPOINT = "temp"
HUD_ENDPOINT = "hud"
ENDPOINTS = [
    SPEED_ENDPOINT,
    GATE_ENDPOINT,
    STATE_ENDPOINT,
    WORKMODE_ENDPOINT,
    TEMP_ENDPOINT,
    HUD_ENDPOINT,
]


class MqttClient:
    """MqttClient class for connecting to a broker."""

    def __init__(
        self,
        hass: HomeAssistant,
        data: dict(str, Any),
        coordinator: Coordinator | None = None,
    ) -> None:
        """Initialize."""
        self.hass = hass
        self.data = data

        self.client_id = f"python-mqtt-{random.randint(0, 1000)}"
        self._client = mqtt.Client(client_id=self.client_id)
        self._client.on_connect = self.on_connect
        self._client.on_message = self.on_message

        self._coordinator = coordinator
        self.is_run = False
        self.subscribes_count = 0
        if len(self.data.keys()) == 5:
            self._client.username_pw_set(
                self.data[CONF_USERNAME], self.data[CONF_PASSWORD]
            )

        self._paho_lock = asyncio.Lock()  # Prevents parallel calls to the MQTT client
        self.is_connected = False

    def on_message(self, client, userdata, message: mqtt.MQTTMessage):
        """Callback on message"""
        key = str.split(message.topic, "/")[-1]
        self._client.unsubscribe(topic=message.topic)
        value = message.payload.decode()
        if value is not None:
            try:
                value = int(value)
            except ValueError:
                pass

        self._coordinator.condition[key] = value
        # for k, val in self._coordinator.condition.items():
        #     _LOGGER.error("%s: %s", k, val)

    def on_connect(self, client, userdata, flags, rc):  # pylint: disable=invalid-name
        """Callback on connect"""
        self.is_connected = True

    async def connect(self) -> bool:
        """Connect with the broker."""
        try:
            await self.hass.async_add_executor_job(
                self._client.connect, self.data[CONF_HOST], self.data[CONF_PORT]
            )
            self._client.loop_start()
            return True
        except OSError as err:
            _LOGGER.error("Failed to connect to MQTT server due to exception: %s", err)

        return False

    async def disconnect(self) -> None:
        """Disconnect from the broker"""

        def stop() -> None:
            """Stop the MQTT client."""
            self._client.loop_stop()

        async with self._paho_lock:
            self.is_connected = False
            await self.hass.async_add_executor_job(stop)
            self._client.disconnect()

    async def try_connect(self) -> bool:
        """Try to create connection with the broker."""
        self._client.on_connect = None

        try:
            self._client.connect(self.data[CONF_HOST], self.data[CONF_PORT])
            return True
        except Exception:
            return False

    async def subscribe(self) -> None:
        self.subscribes_count += 1
        async with self._paho_lock:
            result, mid = await self.hass.async_add_executor_job(
                self._client.subscribe,
                [(f"{self.data[CONF_TOPIC]}/{endpoint}", 0) for endpoint in ENDPOINTS],
            )
        for endpoint in ENDPOINTS:
            _LOGGER.debug("Subscribe to %s, mid: %s, qos: %s", endpoint, mid, 0)

    async def get_condition(
        self,
    ) -> dict(str, Any):
        """Get condition of device"""
        await self.subscribe()
        return self._coordinator.condition

    async def publish(self, endpoint: str, msg: str) -> bool:
        """Publish commands to topic"""
        topic = self.data[CONF_TOPIC] + "/" + endpoint
        qos = 0
        retain = True
        async with self._paho_lock:
            msg_info = await self.hass.async_add_executor_job(
                self._client.publish, topic, msg, qos, retain
            )

        return True


class Coordinator(DataUpdateCoordinator):
    """Class for interact with Broker and HA"""

    def __init__(self, hass: HomeAssistant, data: dict(str, Any)) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=DEFAULT_TIMEINTERVAL
        )
        self._data = data
        self.mqttc = MqttClient(self.hass, data, self)
        self.last_update = None
        self.condition = {
            GATE_ENDPOINT: None,
            SPEED_ENDPOINT: None,
            WORKMODE_ENDPOINT: None,
            STATE_ENDPOINT: None,
            TEMP_ENDPOINT: None,
            HUD_ENDPOINT: None,
        }
        self.is_logged_in = False

    async def async_login(self) -> bool:
        if self.is_logged_in is True:
            return True

        status = await self.mqttc.connect()
        await self.mqttc.subscribe()
        if not status:
            _LOGGER.error("Auth error")
        self.is_logged_in = True
        return status

    async def _async_update_data(self) -> bool:
        """Get all data"""
        await self.mqttc.get_condition()
        return True

    async def _async_update(self, now) -> None:
        """
        Функция регистритуется в hass, во всех датчиках и устройствах и контролирует
        обновление данных через API не чаще чем раз в 2 секунды.
        """
        await self.mqttc.get_condition()

    async def speed(self, value: int | None = None) -> int | bool | None:
        """Speed of fan"""
        if value is None:
            return self.condition[SPEED_ENDPOINT]

        return await self.mqttc.publish(SPEED_ENDPOINT, value)

    async def gate(self, value: int | None = None) -> int | bool | None:
        """Gate of device"""
        if value is None:
            return self.condition[GATE_ENDPOINT]

        return await self.mqttc.publish(GATE_ENDPOINT, value)

    async def state(self, value: str | None = None) -> str | bool | None:
        """State of device"""
        if value is None:
            return self.condition[STATE_ENDPOINT]

        return await self.mqttc.publish(STATE_ENDPOINT, value)

    async def workmode(self, value: str | None = None) -> str | bool | None:
        """Workmode of device: manual or super_auto"""
        if value is None:
            return self.condition[WORKMODE_ENDPOINT]

        return await self.mqttc.publish(WORKMODE_ENDPOINT, value)

    def get_speed(self) -> int | bool | None:
        """Speed of fan"""
        return self.condition[SPEED_ENDPOINT]

    def get_gate(self) -> int | bool | None:
        """Gate of device"""
        return self.condition[GATE_ENDPOINT]

    def get_state(self, value: str | None = None) -> str | bool | None:
        """State of device"""
        return self.condition[STATE_ENDPOINT]

    def get_workmode(self, value: str | None = None) -> str | bool | None:
        """Workmode of device: manual or super_auto"""
        return self.condition[WORKMODE_ENDPOINT]

    def get_temp(self) -> int | bool | None:
        return self.condition[TEMP_ENDPOINT]

    def get_hud(self) -> int | bool | None:
        return self.condition[HUD_ENDPOINT]

    async def turn_on(self) -> bool:
        """Turn on the device"""
        return await self.state(OPENAIR_STATE_ON)

    async def turn_off(self) -> bool:
        """Turn off the device"""
        return await self.state(OPENAIR_STATE_OFF)

    def is_on(self) -> bool:
        """Check is device on"""
        current_state = self.get_state()
        return current_state == OPENAIR_STATE_ON
