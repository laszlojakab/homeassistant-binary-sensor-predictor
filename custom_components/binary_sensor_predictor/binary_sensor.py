"""
The binary sensor module for binary sensor predictor integration.
"""
import logging
from datetime import datetime
from typing import Final, List, Union, cast

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.sensor import RestoreSensor
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_UNIQUE_ID, STATE_OFF, STATE_ON
from homeassistant.core import CALLBACK_TYPE, Event, State
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.typing import HomeAssistantType

from .const import (
    ATTR_CURRENT_STATE,
    ATTR_CURRENT_TIME_BLOCK_STATE,
    ATTR_PROBABILITIES,
    ATTR_PROBABILITY,
    ATTR_TIME_BLOCK_ROTATION,
    CONF_BINARY_SENSOR,
    CONF_FADING,
    CONF_PERIOD,
    CONF_THRESHOLD,
    CONF_TIME_BLOCK_PERIOD,
)

_LOGGER = logging.getLogger(__name__)

# pylint: disable=too-many-instance-attributes
class BinarySensorPredictor(BinarySensorEntity, RestoreSensor):
    """
    Represents a binary sensor predictor binary sensor.
    """

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        unique_id: str,
        name: str,
        binary_sensor_entity_id: str,
        period: int,
        time_block_period: int,
        fading: float,
        threshold: float,
    ):
        """
        Initialize a new instance of `BinarySensorPredictor` class.
        """
        self._attr_unique_id = unique_id
        self._attr_name = name
        self._attr_state = False
        self._unsubscribe_state_change: Union[CALLBACK_TYPE, None] = None
        self._unsubscribe_time_change: Union[CALLBACK_TYPE, None] = None
        self._binary_sensor_entity_id: Final[str] = binary_sensor_entity_id
        self._fading: Final[float] = fading
        self._threshold: Final[float] = threshold
        self._period: Final[int] = period
        self._time_block_period: Final[int] = time_block_period
        self._attr_should_poll = False
        self._attr_state = False
        self._attr_extra_state_attributes = {
            ATTR_CURRENT_TIME_BLOCK_STATE: STATE_OFF,
            ATTR_PROBABILITIES: self._get_probabilities_attribute_default(),
            ATTR_TIME_BLOCK_ROTATION: 0,
            ATTR_PROBABILITY: 0,
        }

    async def async_added_to_hass(self) -> None:
        """Executed when the sensor is added to Home Assistant."""
        last_state = await self.async_get_last_state()
        if last_state:
            self._attr_extra_state_attributes[
                ATTR_PROBABILITIES
            ] = last_state.attributes.get(
                ATTR_PROBABILITIES, self._get_probabilities_attribute_default()
            )

            self._attr_extra_state_attributes[
                ATTR_TIME_BLOCK_ROTATION
            ] = last_state.attributes.get(ATTR_TIME_BLOCK_ROTATION, 0)

            self._rotate_time_blocks()

        self._update_state()

        self._unsubscribe_state_change = async_track_state_change_event(
            self.hass,
            self._binary_sensor_entity_id,
            self._predicted_entity_state_changed_listener,
        )

        self._schedule_update_for_next_time_block()

        return await super().async_added_to_hass()

    async def async_will_remove_from_hass(self) -> None:
        """Executed when the sensor will be removed from Home Assistant."""
        if self._unsubscribe_state_change is not None:
            self._unsubscribe_state_change()

        if self._unsubscribe_time_change is not None:
            self._unsubscribe_time_change()

        return await super().async_will_remove_from_hass()

    # pylint: disable=unused-argument,redefined-outer-name
    async def _time_block_changed_listener(self, datetime: datetime) -> None:
        """
        Handles the case when a time block ends.

        Args:
            datetime: The date time when the listener executed.
        """
        self._attr_extra_state_attributes[ATTR_PROBABILITIES][0] = round(
            int(
                self._attr_extra_state_attributes[ATTR_CURRENT_TIME_BLOCK_STATE]
                == STATE_ON
            )
            * (1 - self._fading)
            + self._attr_extra_state_attributes[ATTR_PROBABILITIES][0] * self._fading,
            6,
        )

        self._rotate_time_blocks()

        if self._attr_extra_state_attributes.get(ATTR_CURRENT_STATE) != STATE_ON:
            self._attr_extra_state_attributes[ATTR_CURRENT_TIME_BLOCK_STATE] = STATE_OFF

        self._update_state()

        self.async_schedule_update_ha_state()
        self._schedule_update_for_next_time_block()

    async def _predicted_entity_state_changed_listener(self, event: Event) -> None:
        """
        Handles the case when the predicted (observed) entity state changed.

        Args:
            event: The state change event.
        """
        new_state = cast(State, event.data.get("new_state")).state
        if (
            new_state == STATE_ON
            and self._attr_extra_state_attributes[ATTR_CURRENT_TIME_BLOCK_STATE]
            == STATE_OFF
        ):
            self._attr_extra_state_attributes[ATTR_CURRENT_TIME_BLOCK_STATE] = STATE_ON
            self._update_state()

        self._attr_extra_state_attributes[ATTR_CURRENT_STATE] = new_state

        self.async_schedule_update_ha_state()

    def _schedule_update_for_next_time_block(self) -> None:
        """
        Schedules tracking of the next time block start.
        """
        next_time_block = self._get_next_time_block()

        self._unsubscribe_time_change = async_track_time_change(
            self.hass,
            self._time_block_changed_listener,
            next_time_block.hour,
            next_time_block.minute,
            next_time_block.second,
        )

    def _get_next_time_block(self) -> datetime:
        """
        Gets the start of the next time block.

        Returns:
            The start of the next time block.
        """
        return datetime.fromtimestamp(
            ((datetime.now().timestamp() // 60) // self._time_block_period + 1)
            * self._time_block_period
            * 60
        )

    def _rotate_time_blocks(self) -> None:
        """
        Rotates the probabilities list in the attributes to organize
        the list in a way when the first element is the probability for
        the current time block, the second element is for the next time block
        and so on.
        """
        saved_time_block_index = self._attr_extra_state_attributes.get(
            ATTR_TIME_BLOCK_ROTATION, 0
        )
        current_time_block_index = self._get_current_time_block_index()
        rotate_by = current_time_block_index - saved_time_block_index

        self._attr_extra_state_attributes[ATTR_PROBABILITIES] = (
            self._attr_extra_state_attributes[ATTR_PROBABILITIES][rotate_by:]
            + self._attr_extra_state_attributes[ATTR_PROBABILITIES][:rotate_by]
        )

        self._attr_extra_state_attributes[
            ATTR_TIME_BLOCK_ROTATION
        ] = current_time_block_index

        self._update_probability()

    def _update_probability(self) -> None:
        """
        Updates the probability attribute.
        """
        self._attr_extra_state_attributes[
            ATTR_PROBABILITY
        ] = self._attr_extra_state_attributes[ATTR_PROBABILITIES][0]

    def _get_probabilities_attribute_default(self) -> List[float]:
        """
        Gets the default value of probabilities attribute.

        Returns:
            A list filled with `0` values with the proper length.
        """
        return self._period // self._time_block_period * [0]

    def _get_current_time_block_index(self) -> int:
        """
        Calculates the current time block's index.
        """
        return int(
            (datetime.now().timestamp() // 60 // self._time_block_period)
            % (24 * 60 // self._time_block_period)
        )

    def _update_state(self):
        """
        Updates the state based on the current probability attribute and the threshold parameter.
        """
        self._attr_is_on = (
            self._attr_extra_state_attributes[ATTR_PROBABILITY] >= self._threshold
        )


async def async_setup_entry(
    # pylint: disable=unused-argument
    hass: HomeAssistantType,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """
    Sets up of Binary Sensor Predictor binary sensor platform based on
    the specified config entry.

    Args:
        hass:
            The Home Assistant instance.
        config_entry:
            The config entry which is used to create sensors.
        async_add_entities:
            The callback which can be used to add new entities to Home Assistant.

    Returns:
        The value indicates whether the setup succeeded.
    """
    _LOGGER.info(f"Setting up Binary Sensor Predictor binary sensor for {config_entry.data[CONF_BINARY_SENSOR]}.")

    async_add_entities(
        [
            BinarySensorPredictor(
                config_entry.data[CONF_UNIQUE_ID],
                config_entry.data[CONF_NAME],
                config_entry.data[CONF_BINARY_SENSOR],
                config_entry.data[CONF_PERIOD],
                config_entry.data[CONF_TIME_BLOCK_PERIOD],
                config_entry.data[CONF_FADING],
                config_entry.data[CONF_THRESHOLD],
            )
        ]
    )

    _LOGGER.info(f"Setting up Binary Sensor Predictor binary sensor for {config_entry.data[CONF_BINARY_SENSOR]} completed.")
