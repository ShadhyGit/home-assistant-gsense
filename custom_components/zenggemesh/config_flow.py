"""Config flow for Zengge MESH lights"""

from typing import Mapping, Optional
import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components import bluetooth
from homeassistant import config_entries
from homeassistant.const import (
    CONF_USERNAME,
    CONF_PASSWORD
)
from .const import DOMAIN, CONF_MESH_NAME, CONF_MESH_PASSWORD, CONF_MESH_KEY
from .zengge_connect import ZenggeConnect

_LOGGER = logging.getLogger(__name__)


def create_zengge_connect_object(username, password) -> ZenggeConnect:
    return ZenggeConnect(username, password)


class ZenggeMeshFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Zengge config flow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    config: Optional[Mapping] = {}

    def __init__(self):
        """Initialize the UPnP/IGD config flow."""
        self._discoveries: Optional[Mapping] = None
        self._mesh_info: Optional[Mapping] = None

    async def async_step_user(self, user_input: Optional[Mapping] = None):
        return await self.async_step_zengge_connect()

        # todo: fix manual connect
        _LOGGER.debug("async_step_user: user_input: %s", user_input)
        if self._mesh_info is None:
            return await self.async_step_mesh_info()

        if user_input is not None and user_input.get('mac'):

            # Ensure wanted device is available
            test_ok = await DeviceScanner.connect_device(
                user_input.get('mac'),
                self._mesh_info.get(CONF_MESH_NAME),
                self._mesh_info.get(CONF_MESH_PASSWORD),
                self._mesh_info.get(CONF_MESH_KEY)
            )

            if not test_ok:
                return self.async_abort(reason="device_not_found")

            await self.async_set_unique_id(
                self._mesh_info.get(CONF_MESH_NAME), raise_on_progress=False
            )
            return await self._async_create_entry_from_discovery(
                user_input.get('mac'),
                user_input.get('name'),
                self._mesh_info.get(CONF_MESH_NAME),
                self._mesh_info.get(CONF_MESH_PASSWORD),
                self._mesh_info.get(CONF_MESH_KEY)
            )

        # Scan for devices
        scan_successful = False
        try:
            discoveries = await DeviceScanner.async_find_available_devices(
                self.hass,
                self._mesh_info.get(CONF_MESH_NAME),
                self._mesh_info.get(CONF_MESH_PASSWORD)
            )
            scan_successful = True
        except (RuntimeError, pygatt.exceptions.BLEError) as e:
            _LOGGER.exception("Failed while scanning for devices [%s]", str(e))

        if not scan_successful:
            return self.async_show_form(
                step_id="manual",
                data_schema=vol.Schema({
                    vol.Required('mac'): str,
                    vol.Required("name", description={"suggested_value": "Zengge light"}): str,
                }),
            )

        # Store discoveries which have not been configured, add name for each discovery.
        current_devices = {entry.unique_id for entry in self._async_current_entries()}
        self._discoveries = [
            {
                **discovery,
                'name': discovery['name'],
            }
            for discovery in discoveries
            if discovery['mac'] not in current_devices
        ]

        # Ensure anything to add.
        if not self._discoveries:
            return self.async_abort(reason="no_devices_found")

        data_schema = vol.Schema(
            {
                vol.Required("mac"): vol.In(
                    {
                        discovery['mac']: discovery['name']
                        for discovery in self._discoveries
                    }
                ),
                vol.Required("name", description={"suggested_value": "Zengge light"}): str,
            }
        )
        return self.async_show_form(
            step_id="select_device",
            data_schema=data_schema,
        )

    async def async_step_zengge_connect(self, user_input: Optional[Mapping] = None):
        devices = [
            {
                "mesh_id": 12,
                "name": "Dining Near_Window",
                "mac": "a4:c1:38:90:49:8a",
                "model": "unknown",
                "manufacturer": "unknown",
                "firmware": "unknown",
                "hardware": None,
                "type": "light"
            },
            {
                "mesh_id": 11,
                "name": "Dining Near_Living",
                "mac": "a4:c1:38:8a:72:97",
                "model": "unknown",
                "manufacturer": "unknown",
                "firmware": "unknown",
                "hardware": None,
                "type": "light"
            },
            {
                "mesh_id": 42,
                "name": "Dhyaan Bottom_Left",
                "mac": "a4:c1:38:90:9c:8a",
                "model": "unknown",
                "manufacturer": "unknown",
                "firmware": "unknown",
                "hardware": None,
                "type": "light"
            }
            # {
            #     "mesh_id": 45,
            #     "name": "Dhyaan Bottom_Right",
            #     "mac": "a4:c1:38:96:56:6e",
            #     "model": "unknown",
            #     "manufacturer": "unknown",
            #     "firmware": "unknown",
            #     "hardware": None,
            #     "type": "light"
            # },
            # {
            #     "mesh_id": 46,
            #     "name": "Dhyaan Center",
            #     "mac": "a4:c1:38:8a:4f:97",
            #     "model": "unknown",
            #     "manufacturer": "unknown",
            #     "firmware": "unknown",
            #     "hardware": None,
            #     "type": "light"
            # },
            # {
            #     "mesh_id": 43,
            #     "name": "Dhyaan Top_Left",
            #     "mac": "a4:c1:38:96:8e:6e",
            #     "model": "unknown",
            #     "manufacturer": "unknown",
            #     "firmware": "unknown",
            #     "hardware": None,
            #     "type": "light"
            # },
            # {
            #     "mesh_id": 44,
            #     "name": "Dhyaan Top_Right",
            #     "mac": "a4:c1:38:8a:5a:97",
            #     "model": "unknown",
            #     "manufacturer": "unknown",
            #     "firmware": "unknown",
            #     "hardware": None,
            #     "type": "light"
            # },
            # {
            #     "mesh_id": 53,
            #     "name": "Master Bathroom",
            #     "mac": "",
            #     "model": "unknown",
            #     "manufacturer": "unknown",
            #     "firmware": "unknown",
            #     "hardware": None,
            #     "type": "light"
            # },
            # {
            #     "mesh_id": 32774,
            #     "name": "Lounge",
            #     "mac": "",
            #     "model": "unknown",
            #     "manufacturer": "unknown",
            #     "firmware": "unknown",
            #     "hardware": None,
            #     "type": "light"
            # },
            # {
            #     "mesh_id": 32775,
            #     "name": "Kitchen",
            #     "mac": "",
            #     "model": "unknown",
            #     "manufacturer": "unknown",
            #     "firmware": "unknown",
            #     "hardware": None,
            #     "type": "light"
            # },
            # {
            #     "mesh_id": 32776,
            #     "name": "Sink",
            #     "mac": "",
            #     "model": "unknown",
            #     "manufacturer": "unknown",
            #     "firmware": "unknown",
            #     "hardware": None,
            #     "type": "light"
            # },
            # {
            #     "mesh_id": 32769,
            #     "name": "Living",
            #     "mac": "",
            #     "model": "unknown",
            #     "manufacturer": "unknown",
            #     "firmware": "unknown",
            #     "hardware": None,
            #     "type": "light"
            # },
            # {
            #     "mesh_id": 32782,
            #     "name": "Dhyaan Room",
            #     "mac": "",
            #     "model": "unknown",
            #     "manufacturer": "unknown",
            #     "firmware": "unknown",
            #     "hardware": None,
            #     "type": "light"
            # },
            # {
            #     "mesh_id": 32779,
            #     "name": "Neel Room",
            #     "mac": "",
            #     "model": "unknown",
            #     "manufacturer": "unknown",
            #     "firmware": "unknown",
            #     "hardware": None,
            #     "type": "light"
            # },
            # {
            #     "mesh_id": 32772,
            #     "name": "Master Bedroom",
            #     "mac": "",
            #     "model": "unknown",
            #     "manufacturer": "unknown",
            #     "firmware": "unknown",
            #     "hardware": None,
            #     "type": "light"
            # },
            # {
            #     "mesh_id": 32773,
            #     "name": "Entrance Hallway",
            #     "mac": "",
            #     "model": "unknown",
            #     "manufacturer": "unknown",
            #     "firmware": "unknown",
            #     "hardware": None,
            #     "type": "light"
            # },
            # {
            #     "mesh_id": 32781,
            #     "name": "Hallway",
            #     "mac": "",
            #     "model": "unknown",
            #     "manufacturer": "unknown",
            #     "firmware": "unknown",
            #     "hardware": None,
            #     "type": "light"
            # },
            # {
            #     "mesh_id": 32777,
            #     "name": "Dining Room",
            #     "mac": "",
            #     "model": "unknown",
            #     "manufacturer": "unknown",
            #     "firmware": "unknown",
            #     "hardware": None,
            #     "type": "light"
            # },
            # {
            #     "mesh_id": 32778,
            #     "name": "Alfresco",
            #     "mac": "",
            #     "model": "unknown",
            #     "manufacturer": "unknown",
            #     "firmware": "unknown",
            #     "hardware": None,
            #     "type": "light"
            # },
            # {
            #     "mesh_id": 32780,
            #     "name": "Guest Bedroom",
            #     "mac": "",
            #     "model": "unknown",
            #     "manufacturer": "unknown",
            #     "firmware": "unknown",
            #     "hardware": None,
            #     "type": "light"
            # },
            # {
            #     "mesh_id": 65535,
            #     "name": "House Lights",
            #     "mac": "",
            #     "model": "unknown",
            #     "manufacturer": "unknown",
            #     "firmware": "unknown",
            #     "hardware": None,
            #     "type": "light"
            # }
            ]

        data = {
            CONF_MESH_NAME: "Gsense_Mesh",
            CONF_MESH_PASSWORD: "321",
            CONF_MESH_KEY: "unknown",
            'devices': devices
        }

        return self.async_create_entry(title='Zengge Cloud', data=data)

    async def async_step_mesh_info(self, user_input: Optional[Mapping] = None):

        _LOGGER.debug("async_step_mesh_info: user_input: %s", user_input)

        errors = {}
        name: str = ''
        password: str = ''
        key: str = ''

        if user_input is not None:
            name = user_input.get(CONF_MESH_NAME)
            password = user_input.get(CONF_MESH_PASSWORD)
            key = user_input.get(CONF_MESH_KEY)

            if len(user_input.get(CONF_MESH_NAME)) > 16:
                errors[CONF_MESH_NAME] = 'max_length_16'
            if len(user_input.get(CONF_MESH_PASSWORD)) > 16:
                errors[CONF_MESH_PASSWORD] = 'max_length_16'
            if len(user_input.get(CONF_MESH_KEY)) > 16:
                errors[CONF_MESH_KEY] = 'max_length_16'

        if user_input is None or errors:
            return self.async_show_form(
                step_id="mesh_info",
                data_schema=vol.Schema({
                    vol.Required(CONF_MESH_NAME, default=name): str,
                    vol.Required(CONF_MESH_PASSWORD, default=password): str,
                    vol.Required(CONF_MESH_KEY, default=key): str
                }),
                errors=errors,
            )

        self._mesh_info = user_input
        return await self.async_step_user()

    async def async_step_manual(self, user_input: Optional[Mapping] = None):
        """Forward result of manual input form to step user"""
        return await self.async_step_user(user_input)

    async def async_step_select_device(self, user_input: Optional[Mapping] = None):
        """Forward result of device select form to step user"""
        return await self.async_step_user(user_input)

    # @staticmethod
    # @callback
    # def async_get_options_flow(config_entry):
    #     """Define the config flow to handle options."""
    #     return UpnpOptionsFlowHandler(config_entry)

    async def _async_create_entry_from_discovery(
            self,
            mac: str,
            name: str,
            mesh_name: str,
            mesh_pass: str,
            mesh_key: str
    ):
        """Create an entry from discovery."""
        _LOGGER.debug(
            "_async_create_entry_from_discovery: device: %s [%s]",
            name,
            mac
        )

        data = {
            CONF_MESH_NAME: mesh_name,
            CONF_MESH_PASSWORD: mesh_pass,
            CONF_MESH_KEY: mesh_key,
            'devices': [
                {
                    'mac': mac,
                    'name': name,
                }
            ]
        }

        return self.async_create_entry(title=name, data=data)
    #
    # async def _async_get_name_for_discovery(self, discovery: Mapping):
    #     """Get the name of the device from a discovery."""
    #     _LOGGER.debug("_async_get_name_for_discovery: discovery: %s", discovery)
    #     device = await Device.async_create_device(
    #         self.hass, discovery[DISCOVERY_LOCATION]
    #     )
    #     return device.name
    #
    #

    # async def _async_get_name_for_discovery(self, discovery: Mapping):
    #     """Get the name of the device from a discovery."""
    #     _LOGGER.debug("_async_get_name_for_discovery: discovery: %s", discovery)
    #     device = await Device.async_create_device(
    #         self.hass, discovery['name']
    #     )
    #     return device.name
#
# async def _async_has_devices(hass) -> bool:
#     """Return if there are devices that can be discovered."""
#     devices = await DeviceScanner.find_devices()
#     return len(devices) > 0
