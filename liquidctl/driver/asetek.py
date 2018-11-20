"""USB driver for fifth generation Asetek coolers.


Supported devices
-----------------

 - [⋯] NZXT Kraken X (X31, X41 or X61)
 - [ ] EVGA CLC (120 CL12, 240 or 280)


Driver features
---------------

 - [⋯] initialization
 - [⋯] connection and transaction life cycle
 - [⋯] reporting of firmware version
 - [⋯] monitoring of pump and fan speeds, and of liquid temperature
 - [⋯] control of pump and fan speeds
 - [✕] control of lighting modes and colors


Copyright (C) 2018  Jonas Malaco
Copyright (C) 2018  each contribution's author

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import itertools
import logging

import usb.util

from liquidctl.driver.usb import UsbDeviceDriver


LOGGER = logging.getLogger(__name__)

_SPEED_CHANNELS = {  # (message type, minimum duty, maximum duty)
    'fan':   (0x12, 0, 100),  # TODO adjust min duty
    'pump':  (0x13, 0, 100),  # TODO adjust min duty
}
_READ_ENDPOINT = 0x82
_READ_LENGTH = 32
_READ_TIMEOUT = 2000
_WRITE_ENDPOINT = 0x2
_WRITE_TIMEOUT = 2000


class AsetekDriver(UsbDeviceDriver):
    """USB driver for fifth generation Asetek coolers."""

    SUPPORTED_DEVICES = [
        (0x2433, 0xb200, None, 'NZXT Kraken X (X31, X41 or X61) (experimental)', {}),  # TODO also EVGA CLC (120 CL12, 240 or 280)
    ]

    def __init__(self, device, description, **kwargs):
        """Instantiate a driver with a device handle."""
        super().__init__(device, description)

    def connect(self, **kwargs):
        """Connect to the device.

        Attaches to the kernel driver (or, on Linux, replaces it) and, if no
        configuration has been set, configures the device to use the first
        available one.  Finally, opens the device.
        """
        super().connect()
        try:
            self._open()
        except Exception as err:
            LOGGER.debug('failed to open (will retry): %s', str(err), exc_info=True)
            self._close()
            self._open()

    def disconnect(self, **kwargs):
        """Disconnect from the device.

        Closes the device, cleans up and, on Linux, reattaches the
        previously used kernel driver.
        """
        self._close()
        super().disconnect()

    def get_status(self, **kwargs):
        """Get a status report.

        Returns a list of (key, value, unit) tuples.
        """
        self._begin_transaction()
        self._send_dummy_command()
        msg = self._end_transaction_and_read()
        firmware = '{}.{}.{}.{}'.format(*tuple(msg[0x17:0x1b]))
        return [
            ('Liquid temperature', msg[10] + msg[14]/10, '°C'),  # TODO sensible decimal?
            ('Fan speed', msg[0] << 8 | msg[1], 'rpm'),
            ('Pump speed', msg[8] << 8 | msg[9], 'rpm'),
            ('Firmware version', firmware, '')  # TODO sensible firmware version?
        ]

    def set_fixed_speed(self, channel, speed, **kwargs):
        """Set channel to a fixed speed."""
        mtype, smin, smax = _SPEED_CHANNELS[channel]
        if speed < smin:
            speed = smin
        elif speed > smax:
            speed = smax
        LOGGER.info('setting %s PWM duty to %i%%', channel, speed)
        self._begin_transaction()
        self._write([mtype, speed])
        self._end_transaction_and_read()

    def _open(self):
        """Open the USBXpress device."""
        LOGGER.debug('open device')
        try:
            self.device.ctrl_transfer(0x40, 0x0, 0xFFFF)
            self.device.clear_halt(_READ_ENDPOINT)
            self.device.clear_halt(_WRITE_ENDPOINT)
        except Exception as err:
            LOGGER.debug('ignoring early failure: %s', str(err), exc_info=True)
        self.device.ctrl_transfer(0x40, 0x2, 0x0002)

    def _close(self):
        """Close the USBXpress device."""
        LOGGER.debug('close device')
        self.device.ctrl_transfer(0x40, 0x2, 0x0004)

    def _begin_transaction(self):
        """Begin a new transaction before writing to the device."""
        # TODO try to remove
        LOGGER.debug('begin transaction')
        self.device.ctrl_transfer(0x40, 0x2, 0x0001)

    def _end_transaction_and_read(self):
        """End the transaction by reading from the device."""
        # TODO test if this is unnecessary (unless we actually want the status)
        msg = self.device.read(_READ_ENDPOINT, _READ_LENGTH, _READ_TIMEOUT)
        LOGGER.debug('received %s', ' '.join(format(i, '02x') for i in msg))
        self.device.release()
        return msg

    def _send_dummy_command(self):
        """Send a dummy command to allow get_status to succeed.

        Reading from the device appears to require writing to it first.  We are
        not aware of any command specifically for getting data.  Instead, this
        uses a color change command, turning it off.
        """
        self._write([
            0x10,  # cmd: color change
            0x00, 0x00, 0x00,  # main color: #000000
            0x00, 0x00, 0x00,  # alt. color: #000000
            0x00, 0x00, 0x00, 0x3c,  # constant
            0x00, 0x00,  # interval: 0
            0x01, 0x00, 0x00,  # mode: off
            0x01, 0x00, 0x01  # constant
            ])

    def _write(self, data):
        LOGGER.debug('write %s', ' '.join(format(i, '02x') for i in data))
        self.device.write(_WRITE_ENDPOINT, data, _WRITE_TIMEOUT)

