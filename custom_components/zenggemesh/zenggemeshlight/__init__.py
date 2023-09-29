#!!!The majority of this code was reused from the home-assistant-awox project developed by fsaris. Huge shoutout to him for all his hard work on this!!!

from __future__ import unicode_literals

from bleak import BleakClient
from homeassistant.components import bluetooth

from . import packetutils as pckt
from . import dimond_utils as dimond

from os import urandom
import asyncio
import logging
import struct
import threading
import math

# Commands :

#: Set mesh groups.
#: Data : 3 bytes
C_MESH_GROUP = 0xd7

#: Set the mesh id. The light will still answer to the 0 mesh id. Calling the
#: command again replaces the previous mesh id.
#: Data : the new mesh id, 2 bytes in little endian order
C_MESH_ADDRESS = 0xe0
C_MESH_RESET = 0xe3

#: On/Off command. Data : [0x01] and one byte 0, 1
#: Brightness command. Data : [0x02], one byte 0x1 to 0x64, and one byte for dimming target
#:   Dimming targets:
#     0x01 Set RGB and keep WC
#     0x02 Set WC, keep RGB
#     0x03 Set RGB and WC brightness
#     0x04 Set RGB and turn off WC
#     0x05 Set WC, turn off RGB
#     0x06 According to the current situation, the lights are set
#: Increasing brightness command. Data: [0x03] and one byte for brightness percentage 0x1 to 0x64 (0 or > 100, default increase by 10%)
#: Decreasing brightness command. Data: [0x04] and one byte for brightness percentage 0x1 to 0x64 (0 or > 100, default decrease by 10%)
C_POWER = 0xd0

#SN - Data: 4 bytes : [Change Mode] [Value1] [Value2] [Value3]
#  Change mode of light (RGB, Warm, CCT/Lum, AuxLight, ColorTemp/Lum/AuxLight)
#    0x60 is the mode for static RGB (Value1,Value2,Value3 stand for RGB values 0-255)
#    0x61 stands for static warm white (Value1 represents warm white value 0-255)
#    0x62 stands for color temp/luminance (Value1 represents CCT scale value 0-100, Value2 represents luminance value 0-100)
#    0x63 stands for auxiliary light (Value1 represents aux light brightness)
#    0x64 stands for color temp value + aux light (Value1 represents CCT ratio value 1-100, Value 2 represents luminance value 0-100, Value 3 represents aux luminance value 0-100)
C_COLOR = 0xe2
C_COLOR_RGB = 0x60
C_COLOR_WARMWHITE = 0x61
C_COLOR_CCTLUM = 0x62
C_COLOR_AUX = 0x63
C_COLOR_CCTLUMAUX = 0x64

#: 7 bytes [Year-Low][Year-High][Month][Day][Hours][Minutes][Seconds]
C_TIME = 0xe4

#: 7 bytes [Year-Low][Year-High][Month][Day][Hours][Minutes][Seconds]
#: Data to Retrieve [0x10]
C_GET_TIME = 0xe8

OPCODE_SETCOLOR = 0xe2
OPCODE_SETCCT = 0xf4
OPCODE_SETSTATE = 0xd0
OPCODE_SETBRIGHTNESS = 0xd0
OPCODE_SETFLASH = 0xd2

OPCODE_GET_STATUS = 0xda        #Request current light/device status
OPCODE_STATUS_RECEIVED = 0xdb    #Response of light/device status request
OPCODE_NOTIFICATION_RECEIVED = 0xdc  #State notification
OPCODE_RESPONSE = 0xdc

STATEACTION_POWER = 0x01
STATEACTION_BRIGHTNESS = 0x02
STATEACTION_INCREASEBRIGHTNESS = 0x03
STATEACTION_DECREASEBRIGHTNESS = 0x04

COLORMODE_RGB = 0x60
COLORMODE_WARMWHITE = 0x61
COLORMODE_CCT = 0x62
COLORMODE_AUX = 0x63
COLORMODE_CCTAUX = 0x64

DIMMINGTARGET_RGBKWC = 0x01 #Set RGB, Keep WC
DIMMINGTARGET_WCKRGB = 0x02 #Set WC, Keep RGB
DIMMINGTARGET_RGBWC = 0x03  #Set RGB & WC
DIMMINGTARGET_RGBOWC = 0x04 #Set RGB, WC Off
DIMMINGTARGET_WCORGB = 0x05 #Set WC, RGB Off
DIMMINGTARGET_AUTO = 0x06   #Set lights according to situation

PAIR_CHAR_UUID = '00010203-0405-0607-0809-0a0b0c0d1914'
COMMAND_CHAR_UUID = '00010203-0405-0607-0809-0a0b0c0d1912'
STATUS_CHAR_UUID = '00010203-0405-0607-0809-0a0b0c0d1911'
OTA_CHAR_UUID = '00010203-0405-0607-0809-0a0b0c0d1913'

MANUFACTURER_UUID = "0000{0:x}-0000-1000-8000-00805f9b34fb".format(0x2A29)
FIRMWARE_REV_UUID = "0000{0:x}-0000-1000-8000-00805f9b34fb".format(0x2A26)
HARDWARE_REV_UUID = "0000{0:x}-0000-1000-8000-00805f9b34fb".format(0x2A27)
MODEL_NBR_UUID = "0000{0:x}-0000-1000-8000-00805f9b34fb".format(0x2A24)

logger = logging.getLogger(__name__)

class ZenggeColor:
    def __new__():
        raise TypeError("This is a static class and cannot be initialized.")
    
    @staticmethod
    def _normal_round(n):
        if n - math.floor(n) < 0.5:
            return math.floor(n)
        return math.ceil(n)
    
    @staticmethod
    def _clamp(value, min_value, max_value):
        return max(min_value, min(max_value, value))
    
    @staticmethod
    def _saturate(value):
        return ZenggeColor._clamp(value, 0.0, 1.0)
    
    @staticmethod
    def _hue_to_rgb(h):
        r = abs(h * 6.0 - 3.0) - 1.0
        g = 2.0 - abs(h * 6.0 - 2.0)
        b = 2.0 - abs(h * 6.0 - 4.0)
        return ZenggeColor._saturate(r), ZenggeColor._saturate(g), ZenggeColor._saturate(b)
    
    @staticmethod
    def _hsl_to_rgb(h, s=1, l=.5):
        h = (h/360)
        r, g, b = ZenggeColor._hue_to_rgb(h)
        c = (1.0 - abs(2.0 * l - 1.0)) * s
        r = round((r - 0.5) * c + l,4) * 255
        g = round((g - 0.5) * c + l,4) * 255
        b = round((b - 0.5) * c + l,4) * 255
        if (r >= 250):
            r = 255
        if (g >= 250):
            g = 255
        if (b >= 250):
            b = 255
        return round(r), round(g), round(b)
    
    @staticmethod
    def _h360_to_h255(h360):
        if h360 <= 180:
            return ZenggeColor._normal_round((h360*254)/360)
        else:
            return ZenggeColor._normal_round((h360*255)/360)
    
    @staticmethod
    def _h255_to_h360(h255):
        if h255 <= 128:
            return ZenggeColor._normal_round((h255*360)/254)
        else:
            return ZenggeColor._normal_round((h255*360)/255)
    
    @staticmethod
    def decode(color):
        return ZenggeColor._hsl_to_rgb(ZenggeColor._h255_to_h360(color))

class ZenggeMeshLight:
    def __init__(self, mac, ble_device=None, mesh_name="ZenggeMesh", mesh_password="ZenggeTechnology", mesh_id=0x0211, hass=None, disconnect_callback=None):
        """
        Args :
            mac: The light's MAC address as a string in the form AA:BB:CC:DD:EE:FF
            mesh_name: The mesh name as a string.
            mesh_password: The mesh password as a string.
            mesh_id: The mesh id (address)
        """
        self.mac = mac
        self.mesh_id = mesh_id
        self.hass = hass
        self._disconnect_callback = disconnect_callback
        self.ble_device = ble_device
        self.client = None
        self.session_key = None
        self.status_callback = None

        self._reconnecting = False
        self._notify_enabled = False
        self.reconnect_counter = 0
        self.processing_command = False #Prevent multiple commands being sent at same time

        self.mesh_name = mesh_name
        self.mesh_password = mesh_password

        # Light status
        #self.white_brightness = 1
        #self.white_temperature = 1
        #self.color_brightness = 1
        #self.red = 0
        #self.green = 0
        #self.blue = 0
        #self.color_mode = False
        #self.state = False
        #self.status_callback = None

    async def enable_notify(self): #Huge thanks to '@cocoto' for helping me figure out this issue with Zengge!
        #await self.send_packet(0x00,bytes([]),self.mesh_id,uuid=STATUS_CHAR_UUID)
        #await asyncio.sleep(.3)
        #await self.send_packet(0x01,bytes([]),self.mesh_id,uuid=STATUS_CHAR_UUID)
        await self.send_packet(0x01,bytes([]),self.mesh_id,uuid=STATUS_CHAR_UUID)
        await asyncio.sleep(.3)
        reply = await self.client.start_notify(STATUS_CHAR_UUID, self._handleNotification)
        logger.info(f'[{self.mesh_name}][{self.mac}] Notify enabled successfully')
        return reply

    async def mesh_login(self):
        if self.client == None:
            return
        session_random = urandom(8)
        message = pckt.make_pair_packet(self.mesh_name.encode(), self.mesh_password.encode(), session_random)
        logger.info(f'[{self.mesh_name}][{self.mac}] Send pair message {message}')
        self.processing_command = True
        pairReply = await self.client.write_gatt_char(PAIR_CHAR_UUID, bytes(message), True)
        await asyncio.sleep(0.3)
        reply = await self.client.read_gatt_char(PAIR_CHAR_UUID)
        self.processing_command = False
        logger.debug(f"[{self.mesh_name}][{self.mac}] Read {reply} from characteristic {PAIR_CHAR_UUID}")

        self.session_key = pckt.make_session_key(self.mesh_name.encode(), self.mesh_password.encode(), session_random, reply[1:9])
        if reply[0] == 0xd:
            self.session_key = pckt.make_session_key(self.mesh_name.encode(), self.mesh_password.encode(), session_random, reply[1:9])
        else:
            if reply[0] == 0xe:
                logger.info(f'[{self.mesh_name}][{self.mac}] Device authentication error: known mesh credentials are not excepted by the device. Did you re-pair them to your Hao Deng app with a different account?')
            else:
                logger.info(f'[{self.mesh_name}][{self.mac}] Unexpected pair value : {repr(reply)}')
            self.disconnect()
            return False

    async def send_packet(self, command, data, dest=None, withResponse=True, attempt=0, uuid=COMMAND_CHAR_UUID):
        """
        Args:
            command: The command, as a number.
            data: The parameters for the command, as bytes.
            dest: The destination mesh id, as a number. If None, this lightbulb's
                mesh id will be used.
        """
        while self.processing_command == True:
            await asyncio.sleep(.1)
        self.processing_command = True
        assert (self.session_key)
        if dest == None: dest = self.mesh_id
        # packet = pckt.make_command_packet(self.session_key, self.mac, dest, command, data)
        packet = dimond.send_packet(self.sk, self.mac, dest, command, data)
        try:
            print(f'[{self.mesh_name}][{self.mac}] Writing command {command} data {repr(data)}')
            reply = await self.client.write_gatt_char(uuid, packet, withResponse)
            self.processing_command = False
            return reply
        except Exception as err:
            self.processing_command = False
            print(f'[{self.mesh_name}][{self.mac}] Command failed, attempt: {attempt} - [{type(err).__name__}] {err}')
            if attempt < 2:
                await self.connect()
                return self.send_packet(command, data, dest, withResponse, attempt+1)
            else:
                self.session_key = None
                raise err

    async def connect(self, mesh_name=None, mesh_password=None) -> bool:
        """
        Args :
            mesh_name: The mesh name as a string.
            mesh_password: The mesh password as a string.
        """
        if mesh_name: self.mesh_name = mesh_name
        if mesh_password: self.mesh_password = mesh_password

        assert len(self.mesh_name) <= 16, "mesh_name can hold max 16 bytes"
        assert len(self.mesh_password) <= 16, "mesh_password can hold max 16 bytes"

        logger.info("[%s][%s] attemping connection...", self.mesh_name, self.mac)
        self.ble_device = bluetooth.async_ble_device_from_address(self.hass, self.mac)
        if self.ble_device:
            self.client = BleakClient(self.ble_device, timeout=15, disconnected_callback=self._disconnectCallback)
            logger.info("**Connecting with BLEDevice**")
        else:
            self.client = BleakClient(self.mac, timeout=15, disconnected_callback=self._disconnectCallback)
        
        await self.client.connect()
        
        logger.info("[%s][%s] connected! Logging into mesh...", self.mesh_name, self.mac)
        await self.mesh_login()

        logger.info(f'[{self.mesh_name}][{self.mac}] Enabling notifications on device')
        await self.enable_notify()

        logger.info(f'[{self.mesh_name}][{self.mac}] Send status message')
        await self.requestStatus()
        self._reconnecting = False
        self._notify_enabled = True
        return True

    def _disconnectCallback(self, event):
        logger.info(f'[{self.mesh_name}][{self.mac}] Disconnected by backend...Will reconnect within 30 secs')
        self._disconnect_callback()
        #self.hass.async_create_task(self._auto_reconnect())
        #if self.session_key:
            #logger.info(f'[{self.mesh_name}][{self.mac}] Try to reconnect...')
            #return asyncio.run_coroutine_threadsafe(self._auto_reconnect(), self.hass.loop).result()
            #await self._auto_reconnect()
            #reconnect_thread = threading.Thread(target=self._auto_reconnect, name='Reconnect-' + self.mac)
            #reconnect_thread.start()

    async def _auto_reconnect(self):
        self.session_key = None
        self.reconnect_counter = 0
        self._reconnecting = True
        while self.session_key is None and self.reconnect_counter < 3 and self._reconnecting:
            try:
                if await self.reconnect():
                    break
            except Exception as err:
                self.reconnect_counter += 1
                logger.info(f'[{self.mesh_name}][{self.mac}] Failed to reconnect attempt {self.reconnect_counter} [{type(err).__name__}] {err}')
                await asyncio.sleep(1)

        self._reconnecting = False

        logger.info(f'[{self.mesh_name}][{self.mac}] Reconnect done after attempt {self.reconnect_counter}, success: {self.is_connected}')

        if not self.is_connected:
            await self.stop()

    async def setMesh(self, new_mesh_name, new_mesh_password, new_mesh_long_term_key):
        """
        Sets or changes the mesh network settings.

        Args :
            new_mesh_name: The new mesh name as a string, 16 bytes max.
            new_mesh_password: The new mesh password as a string, 16 bytes max.
            new_mesh_long_term_key: The new long term key as a string, 16 bytes max.

        Returns :
            True on success.
        """
        assert (self.session_key), "Not connected"
        assert len(new_mesh_name.encode()) <= 16, "new_mesh_name can hold max 16 bytes"
        assert len(new_mesh_password.encode()) <= 16, "new_mesh_password can hold max 16 bytes"
        assert len(new_mesh_long_term_key.encode()) <= 16, "new_mesh_long_term_key can hold max 16 bytes"
        if self.session_key is None:
            print("BLE device is not connected!")
            self.mac = input('Please enter MAC of device:')
            self.connect()
        message = pckt.encrypt(self.session_key, new_mesh_name.encode())
        message.insert(0, 0x4)
        await self.client.write_gatt_char(PAIR_CHAR_UUID, message)
        message = pckt.encrypt(self.session_key, new_mesh_password.encode())
        message.insert(0, 0x5)
        await self.client.write_gatt_char(PAIR_CHAR_UUID, message)
        message = pckt.encrypt(self.session_key, new_mesh_long_term_key.encode())
        message.insert(0, 0x6)
        await self.client.write_gatt_char(PAIR_CHAR_UUID, message)
        await asyncio.sleep(1)
        reply = bytearray(await self.client.read_gatt_char(PAIR_CHAR_UUID))
        if reply[0] == 0x7:
            self.mesh_name = new_mesh_name
            self.mesh_password = new_mesh_password
            print(f'[{self.mesh_name}]-[{self.mesh_password}]-[{self.mac}] Mesh network settings accepted.')
            return True
        else:
            print(f'[{self.mesh_name}][{self.mac}] Mesh network settings change failed : {repr(reply)}')
            return False

    def setMeshId(self, mesh_id):
        """
        Sets the mesh id.

        Args :
            mesh_id: as a number.

        """
        data = struct.pack("<H", mesh_id)
        self.send_packet(C_MESH_ADDRESS, data)
        self.mesh_id = mesh_id

    async def resetMesh(self):
        """
        Restores the default name and password. Will disconnect the device.
        """
        return await self.send_packet(C_MESH_RESET, b'\x00')

    def _handleNotification(self, cHandle, data):

        if self.session_key is None:
            logger.info(f'[{self.mesh_name}][{self.mac}] Device is disconnected, ignoring received notification [unable to decrypt without active session]')
            return

        message = dimond.decrypt_packet(self.session_key, self.mac, data)
        logger.info(f'[{self.mesh_name}][{self.mac}] Recevied Notification: {repr(list(message))}')
        if message is None:
            logger.info(f'[{self.mesh_name}][{self.mac}] Failed to decrypt package [key: {self.session_key}, data: {data}]')
            return

        self._parseStatusResult(message)

    def _parseStatusResult(self, data):
        command = struct.unpack('B', data[7:8])[0]
        status = {}
        if command == OPCODE_STATUS_RECEIVED: #This does not return any useful status info, only that the device is online
            mesh_address = struct.unpack('B', data[3:4])[0]
            print("[%s] OPCODE_STATUS_RECEIVED", mesh_address)
        elif command == OPCODE_NOTIFICATION_RECEIVED:  #Each notification can include info for 2 devices
            device_1_data = struct.unpack('BBBBB', data[10:15])
            device_2_data = struct.unpack('BBBBB', data[15:20])
            if (device_1_data[0] != 0):
                mesh_address = device_1_data[0]
                connected = device_1_data[1]
                if mesh_address == 255: #Mesh Address of Wi-Fi Bridge
                    status = {
                        'type': 'status',
                        'mesh_id': mesh_address,
                        'state': connected != 0,
                    }
                else:
                    brightness = device_1_data[2]
                    mode = device_1_data[3]
                    cct = color = device_1_data[4]
                    if(mode == 63 or mode == 42):
                        color_mode = 'rgb'
                        rgb = ZenggeColor.decode(color) #Converts from 1 value(hue) to RGB
                    else:
                        color_mode = 'white'
                        rgb = [0,0,0]
                    status = {
                        'type': 'status',
                        'mesh_id': mesh_address,
                        'state': brightness != 0 if connected != 0 else None,
                        'color_mode': color_mode,
                        'red': rgb[0],
                        'green': rgb[1],
                        'blue': rgb[2],
                        'white_temperature': cct,
                        'brightness': brightness,
                    }
                logger.info(f'[{self.mesh_name}][{self.mac}] Parsed response - status: {status}\n')
                if status and self.status_callback:
                    self.status_callback(status)

            if (device_2_data[0] != 0):
                mesh_address = device_2_data[0]
                connected = device_2_data[1]
                if mesh_address == 255: #Mesh Address of Wi-Fi Bridge
                    status = {
                        'type': 'status',
                        'mesh_id': mesh_address,
                        'state': connected != 0,
                    }
                else:
                    brightness = device_2_data[2]
                    mode = device_2_data[3]
                    cct = color = device_2_data[4]
                    if(mode == 63 or mode == 42):
                        color_mode = 'rgb'
                        rgb = ZenggeColor.decode(color) #Converts from 1 value(hue) to RGB
                    else:
                        color_mode = 'white'
                        rgb = [0,0,0]
                    status = {
                        'type': 'notification',
                        'mesh_id': mesh_address,
                        'state': brightness != 0 if connected != 0 else None,
                        'color_mode': color_mode,
                        'red': rgb[0],
                        'green': rgb[1],
                        'blue': rgb[2],
                        'white_temperature': cct,
                        'brightness': brightness,
                    }
                logger.info(f'[{self.mesh_name}][{self.mac}] Parsed response - status: {status}\n')
                if status and self.status_callback:
                    self.status_callback(status)
        else:
            print(f'[{self.mesh_name}][{self.mac}] Unknown command [{command}]')

    async def requestStatus(self):
        while self.processing_command == True:
            await asyncio.sleep(.1)
        self.processing_command = True
        logger.debug(f'[{self.mesh_name}][{self.mac}] requestStatus')
        reply = await self.client.write_gatt_char(STATUS_CHAR_UUID, b'\x01', True) #Zengge can't use Status request to receive device details, need notification requests
        self.processing_command = False
        return reply

    async def setColor(self, red, green, blue, dest=None):
        """
        Args :
            red, green, blue: between 0 and 0xff
        """
        return await self.send_packet(OPCODE_SETCOLOR, bytes([0xFF,COLORMODE_RGB,red,green,blue]), dest)

    async def setColorBrightness(self, brightness, dest=None):
        """
        Args :
            brightness: a value between 0xa and 0x64 ...
        """
        return await self.send_packet(OPCODE_SETSTATE, bytes([0xFF,STATEACTION_BRIGHTNESS,brightness,DIMMINGTARGET_AUTO]), dest)

    def setSequenceColorDuration(self, duration, dest=None): ###NOT IMPLEMENTED###
        """
        Args :
            duration: in milliseconds.
        """
        data = struct.pack("<I", duration)
        return False #return self.send_packet(C_SEQUENCE_COLOR_DURATION, data, dest)

    def setSequenceFadeDuration(self, duration, dest=None): ###NOT IMPLEMENTED###
        """
        Args:
            duration: in milliseconds.
        """
        data = struct.pack("<I", duration)
        return False #return self.send_packet(C_SEQUENCE_FADE_DURATION, data, dest)

    async def setWhiteBrightness(self, brightness, dest=None):
        """
        Args :
            brightness: between 1 and 0x7f
        """
        return await self.send_packet(OPCODE_SETSTATE, bytes([0xFF,STATEACTION_BRIGHTNESS,brightness,DIMMINGTARGET_AUTO]), dest)

    async def setWhiteTemperature(self, temp, dest=None):
        """
        Args :
            temp: between 0 and 0x64
        """
        #OPCODE_SETCOLOR  COLORMODE_CCT
        return await self.send_packet(OPCODE_SETCOLOR, bytes([0xFF,COLORMODE_CCT,temp,self.white_brightness]), dest)

    async def setWhite(self, temp, brightness, dest=None):
        """
        Args :
            temp: between 0 and 0x7f
            brightness: between 1 and 0x7f
        """
        return await self.send_packet(OPCODE_SETCOLOR, bytes([0xFF,COLORMODE_CCT,255,self.white_brightness]), dest)

    async def on(self, dest=None):
        """ Turns the light on.
        """
        return await self.send_packet(OPCODE_SETSTATE, bytes([0xFF,STATEACTION_POWER,1]), dest)

    async def off(self, dest=None):
        """ Turns the light off.
        """
        return await self.send_packet(OPCODE_SETSTATE, bytes([0xFF,STATEACTION_POWER,0]), dest)

    async def reconnect(self) -> bool:
        logger.debug(f'[{self.mesh_name}][{self.mac}] Reconnecting')
        self.session_key = None
        return await self.connect()

    async def disconnect(self):
        logger.debug(f'[{self.mesh_name}][{self.mac}] Disconnecting')
        self.session_key = None
        self._reconnecting = False

        try:
            await self.client.disconnect()
        except Exception as err:
            logger.warning(f'[{self.mesh_name}][{self.mac}] Disconnect failed: [{type(err).__name__}] {err}')
            await self.stop()

    async def stop(self):
        logger.debug(f'[{self.mesh_name}][{self.mac}] Force stopping ble adapter')

        self._reconnecting = False
        self.session_key = None

        try:
            await self.client.disconnect()
        except Exception as err:
            logger.warning(f'[{self.mesh_name}][{self.mac}] Stop failed: [{type(err).__name__}] {err}')

    async def getFirmwareRevision(self):
        """
        Returns :
            The firmware version as a null terminated utf-8 string.
        """
        return await self.client.read_gatt_char(FIRMWARE_REV_UUID)

    async def getHardwareRevision(self):
        """
        Returns :
            The hardware version as a null terminated utf-8 string.
        """
        return await self.client.read_gatt_char(HARDWARE_REV_UUID)

    async def getModelNumber(self):
        """
        Returns :
            The model as a null terminated utf-8 string.
        """
        return await self.client.read_gatt_char(MODEL_NBR_UUID)

    @property
    def is_connected(self) -> bool:
        return self.session_key is not None and self.client and self.client.is_connected and self._notify_enabled

    @property
    def reconnecting(self) -> bool:
        return self._reconnecting