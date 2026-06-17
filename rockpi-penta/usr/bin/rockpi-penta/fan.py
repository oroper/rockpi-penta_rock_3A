#!/usr/bin/env python3
"""
fan.py - control system fan speed using PWM or GPIO toggling.

Reads CPU temperature and adjusts the fan duty cycle accordingly.
This module supports hardware PWM via sysfs or a software PWM using
gpiod toggling in a background thread.
"""

import os.path
import time
import traceback
import threading

import gpiod

import misc

pin = None


class Pwm:
    """Simple wrapper for the sysfs PWM interface.

    The class writes to files under /sys/class/pwm/<chip>/pwm0/ to
    control period, duty cycle and enable state.
    """

    def __init__(self, chip):
        """Initialize a PWM channel.

        `chip` may be an integer index (e.g. '0') or an existing pwmchip
        name (e.g. 'pwmchip0'). If it's numeric, the code prefixes
        'pwmchip' to form the sysfs path.
        """
        self.period_value = None
        try:
            int(chip)
            chip = f'pwmchip{chip}'
        except ValueError:
            pass
        self.filepath = f"/sys/class/pwm/{chip}/pwm0/"
        try:
            with open(f"/sys/class/pwm/{chip}/export", 'w') as f:
                f.write('0')
        except OSError:
            print("Waring: init pwm error")
            traceback.print_exc()

    def period(self, ns: int):
        """Set PWM period in nanoseconds.

        Stores the value locally so `write()` can compute duty cycles.
        """
        self.period_value = ns
        with open(os.path.join(self.filepath, 'period'), 'w') as f:
            f.write(str(ns))

    def period_us(self, us: int):
        """Convenience: set period in microseconds."""
        self.period(us * 1000)

    def enable(self, t: bool):
        """Enable or disable the PWM output.

        Writes '1' to enable and '0' to disable.
        """
        with open(os.path.join(self.filepath, 'enable'), 'w') as f:
            f.write(f"{int(t)}")

    def write(self, duty: float):
        """Write duty cycle as a fraction (0.0-1.0) of the configured period."""
        assert self.period_value, "The Period is not set."
        with open(os.path.join(self.filepath, 'duty_cycle'), 'w') as f:
            f.write(f"{int(self.period_value * duty)}")


class Gpio:

    """Software PWM implementation using gpiod and a background thread.

    The thread repeatedly toggles the GPIO line with on/off durations
    taken from `self.value`.
    """

    def tr(self):
        """Thread target: toggle the GPIO line indefinitely."""
        while True:
            self.line.set_value(1)
            time.sleep(self.value[0])
            self.line.set_value(0)
            time.sleep(self.value[1])

    def __init__(self, period_s):
        """Open the gpio line and start the toggling thread.

        `period_s` is the total on+off period in seconds.
        """
        self.line = gpiod.Chip(os.environ['FAN_CHIP']).get_line(int(os.environ['FAN_LINE']))
        self.line.request(consumer='fan', type=gpiod.LINE_REQ_DIR_OUT)
        self.value = [period_s / 2, period_s / 2]  # on/off durations
        self.period_s = period_s
        self.thread = threading.Thread(target=self.tr, daemon=True)
        self.thread.start()

    def write(self, duty):
        """Set duty fraction (0.0-1.0). Adjust on/off timings accordingly."""
        self.value[1] = duty * self.period_s
        self.value[0] = self.period_s - self.value[1]


def read_temp():
    """Read CPU temperature in degrees Celsius from sysfs."""
    with open('/sys/class/thermal/thermal_zone0/temp') as f:
        t = int(f.read().strip()) / 1000.0
    return t


def get_dc(cache={}):
    """Return desired duty cycle, using a 60s cache to avoid frequent reads.

    If `misc.conf['run'].value` equals 0, return a near-full-on value.
    Otherwise compute duty from current temperature via `misc.fan_temp2dc`.
    """
    if misc.conf['run'].value == 0:
        return 0.999

    if time.time() - cache.get('time', 0) > 60:
        cache['time'] = time.time()
        cache['dc'] = misc.fan_temp2dc(read_temp())

    return cache['dc']


def change_dc(dc, cache={}):
    """Apply a new duty cycle to the currently configured pin if changed."""
    if dc != cache.get('dc'):
        cache['dc'] = dc
        pin.write(dc)


def running():
    """Main loop: select backend and update duty cycle every second."""
    global pin
    if os.environ['HARDWARE_PWM'] == '1':
        chip = os.environ['PWMCHIP']
        pin = Pwm(chip)
        pin.period_us(40)
        pin.enable(True)
    else:
        pin = Gpio(0.025)
    while True:
        change_dc(get_dc())
        time.sleep(1)


if __name__ == '__main__':
    running()
