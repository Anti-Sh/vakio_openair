"""123"""
from __future__ import annotations
import decimal
from typing import Any, Optional
import logging
import voluptuous as vol
from datetime import datetime, timedelta, timezone

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from .vakio import Coordinator
from .const import (
    DOMAIN,
    OPENAIR_STATE_ON,
    OPENAIR_STATE_OFF,
    OPENAIR_WORKMODE_MANUAL,
    OPENAIR_WORKMODE_SUPERAUTO,
    OPENAIR_SPEED_LIST,
    OPENAIR_SPEED_01,
    OPENAIR_GATE_LIST,
)

percentage = ordered_list_item_to_percentage(OPENAIR_SPEED_LIST, OPENAIR_SPEED_01)
named_speed = percentage_to_ordered_list_item(OPENAIR_SPEED_LIST, 20)

FULL_SUPPORT = (
    FanEntityFeature.SET_SPEED
    | FanEntityFeature.DIRECTION
    | FanEntityFeature.OSCILLATE
    | FanEntityFeature.PRESET_MODE
)
LIMITED_SUPPORT = FanEntityFeature.SET_SPEED | FanEntityFeature.PRESET_MODE
PRESET_MODS = ["Off", "Gate 1", "Gate 2", "Gate 3", "Gate 4", "Super Auto"]


async def async_setup_entry(
    hass: HomeAssistant, conf: ConfigEntry, entities: AddEntitiesCallback
) -> bool:
    """Register settings of device."""
    return await async_setup_platform(hass, conf, entities)


async def async_setup_platform(
    hass: HomeAssistant,
    conf: ConfigType,
    entities: AddEntitiesCallback,
    info: DiscoveryInfoType | None = None,
) -> bool:
    openair = VakioOpenAirFan(
        hass, "openair1", "OpenAir", conf.entry_id, LIMITED_SUPPORT, PRESET_MODS
    )
    entities([openair])
    coordinator: Coordinator = hass.data[DOMAIN][conf.entry_id]
    async_track_time_interval(hass, coordinator._async_update, timedelta(seconds=5))
    return True


class VakioOpenAirFanBase(FanEntity):
    "Base class for VakioOperAirFan"
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        unique_id: str,
        name: str,
        entry_id: str,
        supported_features: FanEntityFeature,
        preset_modes: list[str] | None,
        translation_key: str | None = None,
    ) -> None:
        """Конструктор."""
        self.hass = hass
        self._unique_id = unique_id
        self._attr_supported_features = supported_features
        self._percentage: int | None = None
        self._preset_modes = preset_modes
        self._preset_mode: str | None = None
        self._oscillating: bool | None = None
        self._direction: str | None = None
        self._attr_name = name
        self._entity_id = entry_id
        if supported_features & FanEntityFeature.OSCILLATE:
            self._oscillating = False
        if supported_features & FanEntityFeature.DIRECTION:
            self._direction = None
        self._attr_translation_key = translation_key
        self.coordinator: Coordinator = hass.data[DOMAIN][entry_id]

    @property
    def unique_id(self) -> str:
        """Return unique id"""
        return self._unique_id

    @property
    def current_direction(self) -> str | None:
        """Currnt direction of fan"""
        return self._direction

    @property
    def oscillating(self) -> bool | None:
        """Current oscillating"""
        return self._oscillating


class VakioOpenAirFan(VakioOpenAirFanBase, FanEntity):
    "Status of device in Home Assistant"

    @property
    def percentage(self) -> int | None:
        """Возвращает текущую скорость в процентах."""
        return self._percentage

    @property
    def speed_count(self) -> int:
        """Возвращает количество поддерживаемых скоростей."""
        return len(OPENAIR_SPEED_LIST)

    @property
    def preset_mode(self) -> str | None:
        """Возвращает текущий пресет режима работы."""
        return self._preset_mode

    @property
    def preset_modes(self) -> list[str] | None:
        """Возвращает все пресеты режимов работы."""
        return self._preset_modes

    async def async_set_percentage(self, percentage: int) -> None:
        """Установка скорости работы вентиляции в процентах."""
        self._percentage = percentage
        if percentage == 0:
            self.coordinator.turn_off()
            self.update_all_options()
            return
        self.coordinator.turn_on()
        # Получение именованой скорости.
        speed: decimal.Decimal = percentage_to_ordered_list_item(
            OPENAIR_SPEED_LIST, percentage
        )
        # Выполнение метода API установки скорости.
        self.coordinator.speed(speed)
        if self.update_speed():
            self.update_all_options()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Переключение режима работы на основе пресета."""
        if self.preset_modes and preset_mode in self.preset_modes:
            self._preset_mode = preset_mode
        else:
            raise ValueError(f"Неизвестный режим: {preset_mode}")
        if self._preset_mode == OPENAIR_STATE_OFF:
            # self.coordinator.SetTurnOff()
            # self.update_all_options()
            return
        # Поиск именованого предустановленного серверного режима.
        # for key, mode in SERVER_WORK_TO_FAN_MODE.items():
        #     if mode == preset_mode:
        #         # Выполнение метода API установки режима.
        #         self.coordinator.SetWorkMode(key)
        # if self._percentage is None or self._percentage == 0:
        #     self.coordinator.SetSpeed(OPENAIR_SPEED_01)
        self.update_all_options()

    async def async_turn_on(
        self,
        speed: Optional[str] = None,
        percentage: Optional[int] = None,
        preset_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Включение вентиляционной системы."""
        self.coordinator.turn_on()
        # Получение именованой скорости.
        new_speed: decimal.Decimal = 0
        if percentage is not None:
            new_speed = percentage_to_ordered_list_item(OPENAIR_SPEED_LIST, percentage)
        else:
            new_speed = OPENAIR_SPEED_01

        self.coordinator.speed(new_speed)
        self.update_all_options()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Выключение вентиляционной системы."""
        self.coordinator.turn_off()
        await self._async_update(datetime.now(timezone.utc))

    async def _async_update(self, now: datetime) -> None:
        """
        Функция вызывается по таймеру.
        Выполняется сравнение параметров состояния вентиляционной системы с параметрами записанными в классе.
        Если выявляется разница, тогда параметры класса обновляются.
        """
        is_update: bool = False
        if self.update_speed():
            is_update = True
        if self.update_preset_mode():
            is_update = True
        if self.update_on_off():
            is_update = True
        if is_update:
            self.update_all_options()

    def update_speed(self) -> bool:
        """
        Обновление текущей скорости работы вентиляционной системы.
        Возвращается "истина" если было выполнено обновление.
        """
        speed: int | None = self.coordinator.speed()
        if (
            speed is None or speed > len(OPENAIR_SPEED_LIST) or speed == 0
        ) and self._percentage is not None:
            self._percentage = None
            return True
        if speed is None or speed is False:
            return False

        speed -= 1
        named_speed = OPENAIR_SPEED_LIST[speed]
        new_speed_percentage = ordered_list_item_to_percentage(
            OPENAIR_SPEED_LIST, named_speed
        )

        if self._percentage != new_speed_percentage:
            self._percentage = new_speed_percentage
            return True

        return False

    def update_preset_mode(self) -> bool:
        """
        Обновление текущего предопределённого режима работы вентиляционной системы.
        Возвращается "истина" если было выполнено обновление.
        """
        # mode: str | None = self.coordinator.FanMode()
        # if self._preset_mode == mode:
        #     return False
        # self._preset_mode = mode
        # self._oscillating = (
        #     mode == FAN_MODE_RECUPERATOR
        #     or mode == FAN_MODE_WINTER
        #     or mode == FAN_MODE_NIGHT
        # )
        # # Переключение значка прямая вентиляция для приточных режимов.
        # if mode == FAN_MODE_INFLOW or mode == FAN_MODE_INFLOW_MAX:
        #     self._direction = DIRECTION_FORWARD
        # # Переключение значка обратная вентиляция для режимов вытяжки.
        # if mode == FAN_MODE_OUTFLOW or mode == FAN_MODE_OUTFLOW_MAX:
        #     self._direction = DIRECTION_REVERSE
        # # Отключение значка направления для режимов с рекуперацией.
        # if (
        #     mode == FAN_MODE_RECUPERATOR
        #     or mode == FAN_MODE_WINTER
        #     or mode == FAN_MODE_NIGHT
        #     or mode == OPENAIR_STATE_OFF
        # ):
        #     self._direction = None

        return True

    def update_on_off(self) -> bool:
        """
        Обновление текущего состояния включённости вентиляционной системы.
        Возвращается "истина" если было выполнено обновление.
        """
        is_on: bool | None = self.coordinator.is_on()
        if not bool(is_on):
            # Вентиляция выключена.
            if not self._percentage is None and self._percentage > 0:
                self._percentage = int(0)
                return True
        else:
            # Вентиляция включена.
            if self._percentage is None or self._percentage == 0:
                if self._percentage is None:
                    self._percentage = ordered_list_item_to_percentage(
                        OPENAIR_SPEED_LIST, OPENAIR_SPEED_01
                    )
                if self._preset_mode == OPENAIR_STATE_OFF:
                    self._preset_mode = None
                return True

        return False

    def update_all_options(self) -> None:
        """
        Обновление состояния всех индикаторов интеграции в соответствии
        с переключённым режимом работы вентиляционной системы.
        """
        # Выбор режима рекуперация при включении "колебания".
        # if (
        #     self._oscillating
        #     and self._preset_mode != FAN_MODE_RECUPERATOR
        #     and self._preset_mode != FAN_MODE_WINTER
        #     and self._preset_mode != FAN_MODE_NIGHT
        # ):
        #     self._preset_mode = FAN_MODE_RECUPERATOR
        #     for key, mode in SERVER_WORK_TO_FAN_MODE.items():
        #         if mode == self._preset_mode:
        #             self.coordinator.SetWorkMode(key)
        # if self._oscillating and self._direction is not None:
        #     self._direction = None
        # if not self._oscillating and self._direction is None:
        #     self._direction = DIRECTION_FORWARD
        # if self._direction == DIRECTION_REVERSE and (
        #     self._preset_mode == FAN_MODE_INFLOW
        #     or self._preset_mode == FAN_MODE_INFLOW_MAX
        # ):
        #     self._direction = DIRECTION_FORWARD
        # if self._direction == DIRECTION_FORWARD and (
        #     self._preset_mode == FAN_MODE_OUTFLOW
        #     or self._preset_mode == FAN_MODE_OUTFLOW_MAX
        # ):
        #     self._direction = DIRECTION_REVERSE
        # if not self._oscillating and (
        #     self._preset_mode == FAN_MODE_RECUPERATOR
        #     or self._preset_mode == FAN_MODE_WINTER
        #     or self._preset_mode == FAN_MODE_NIGHT
        # ):
        #     self._preset_mode = FAN_MODE_INFLOW
        #     for key, mode in SERVER_WORK_TO_FAN_MODE.items():
        #         if mode == self._preset_mode:
        #             self.coordinator.SetWorkMode(key)
        # if (
        #     not self._percentage is None
        #     and self._percentage > 0
        #     and (self._preset_mode is None or self._preset_mode == OPENAIR_STATE_OFF)
        # ):
        #     self._direction = DIRECTION_FORWARD
        #     self._preset_mode = FAN_MODE_INFLOW
        #     for key, mode in SERVER_WORK_TO_FAN_MODE.items():
        #         if mode == self._preset_mode:
        #             self.coordinator.SetWorkMode(key)
        self.schedule_update_ha_state()