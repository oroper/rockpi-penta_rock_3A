#!/usr/bin/env python3
"""
misc.py - miscellaneous helpers used by the ROCKPi SATA HAT scripts.

This module provides small system helpers (shell command runners),
configuration loading, key/button handling, slider/page utilities and
fan-related helpers consumed by other modules (`fan.py`, `oled.py`,
`main.py`).
"""

import re
import os
import time
import subprocess
import multiprocessing as mp
import traceback

import gpiod
from configparser import ConfigParser
from collections import defaultdict, OrderedDict

# Common shell commands used to collect system info for the OLED/UI
cmds = {
    'blk': "lsblk | awk '{print $1}'",
    'up': "echo Uptime: `uptime | sed 's/.*up \\\([^,]*\\\), .*/\\1/'`",
    'temp': "cat /sys/class/thermal/thermal_zone0/temp",
    'ip': "hostname -I | awk '{printf \"IP %s\", $1}'",
    'cpu': "uptime | awk '{printf \"CPU Load: %.2f\", $(NF-2)}'",
    'men': "free -m | awk 'NR==2{printf \"Mem: %s/%sMB\", $3,$2}'",
    'disk': "df -h | awk '$NF==\"/\"{printf \"Disk: %d/%dGB %s\", $3,$2,$5}'"
}

# Map fan temperature levels to duty-cycle fractions (ordered high->low)
lv2dc = OrderedDict({'lv3': 0, 'lv2': 0.25, 'lv1': 0.5, 'lv0': 0.75})


def check_output(cmd):
    """Run a shell command and return trimmed stdout as text."""
    #!/usr/bin/env python3
    """
    misc.py - small system utilities for the ROCKPi SATA HAT.

    This module provides helpers used by the UI and fan controller to:
    - run shell commands and format their output
    - read configuration from /etc/rockpi-penta.conf (with sensible defaults)
    - read and interpret a single-button input via gpiod
    - format pages for the OLED slider UI
    - compute fan duty from temperature
    """

    import re
    import os
    import time
    import subprocess
    import multiprocessing as mp
    import traceback

    import gpiod
    from configparser import ConfigParser
    from collections import defaultdict, OrderedDict

    # Shell commands used by utilities (wrapped by check_output/get_info)
    cmds = {
        'blk': "lsblk | awk '{print $1}'",
        'up': "echo Uptime: `uptime | sed 's/.*up \\([^,]*\\), .*/\\1/'`",
        'temp': "cat /sys/class/thermal/thermal_zone0/temp",
        'ip': "hostname -I | awk '{printf \"IP %s\", $1}'",
        'cpu': "uptime | awk '{printf \"CPU Load: %.2f\", $(NF-2)}'",
        'men': "free -m | awk 'NR==2{printf \"Mem: %s/%sMB\", $3,$2}'",
        'disk': "df -h | awk '$NF==\"/\"{printf \"Disk: %d/%dGB %s\", $3,$2,$5}'"
    }

    # Mapping of fan level names to duty-cycle fractions (ordered by priority)
    lv2dc = OrderedDict({'lv3': 0, 'lv2': 0.25, 'lv1': 0.5, 'lv0': 0.75})


    def check_output(cmd):
        """Run a shell command and return decoded stdout stripped of whitespace."""
        return subprocess.check_output(cmd, shell=True).decode().strip()


    def check_call(cmd):
        """Run a shell command and return its exit code (raises on failure)."""
        return subprocess.check_call(cmd, shell=True)


    def get_blk():
        """Populate `conf['disk']` with block device names starting with 'sd'."""
        conf['disk'] = [x for x in check_output(cmds['blk']).strip().split('\n') if x.startswith('sd')]


    def get_info(s):
        """Return the output of a predefined shell command keyed by `s`."""
        return check_output(cmds[s])


    def get_cpu_temp():
        """Return a human-readable CPU temperature string respecting config."""
        t = float(get_info('temp')) / 1000
        if conf['oled']['f-temp']:
            temp = "CPU Temp: {:.0f}°F".format(t * 1.8 + 32)
        else:
            temp = "CPU Temp: {:.1f}°C".format(t)
        return temp


    def read_conf():
        """Read configuration from /etc/rockpi-penta.conf with defaults.

        Returns a nested dict-like `defaultdict(dict)` holding values for
        fan thresholds, key mappings, timing and slider/oled options.
        """
        conf = defaultdict(dict)

        try:
            cfg = ConfigParser()
            cfg.read('/etc/rockpi-penta.conf')
            # fan thresholds (degrees C)
            conf['fan']['lv0'] = cfg.getfloat('fan', 'lv0')
            conf['fan']['lv1'] = cfg.getfloat('fan', 'lv1')
            conf['fan']['lv2'] = cfg.getfloat('fan', 'lv2')
            conf['fan']['lv3'] = cfg.getfloat('fan', 'lv3')
            # key mappings (strings like 'slider', 'switch', ...)
            conf['key']['click'] = cfg.get('key', 'click')
            conf['key']['twice'] = cfg.get('key', 'twice')
            conf['key']['press'] = cfg.get('key', 'press')
            # timing thresholds (seconds)
            conf['time']['twice'] = cfg.getfloat('time', 'twice')
            conf['time']['press'] = cfg.getfloat('time', 'press')
            # slider and oled options
            conf['slider']['auto'] = cfg.getboolean('slider', 'auto')
            conf['slider']['time'] = cfg.getfloat('slider', 'time')
            conf['oled']['rotate'] = cfg.getboolean('oled', 'rotate')
            conf['oled']['f-temp'] = cfg.getboolean('oled', 'f-temp')
        except Exception:
            traceback.print_exc()
            # Fallback defaults if config read fails
            conf['fan']['lv0'] = 35
            conf['fan']['lv1'] = 40
            conf['fan']['lv2'] = 45
            conf['fan']['lv3'] = 50
            conf['key']['click'] = 'slider'
            conf['key']['twice'] = 'switch'
            conf['key']['press'] = 'none'
            conf['time']['twice'] = 0.7  # second
            conf['time']['press'] = 1.8
            conf['slider']['auto'] = True
            conf['slider']['time'] = 10  # second
            conf['oled']['rotate'] = False
            conf['oled']['f-temp'] = False

        return conf


    def read_key(pattern, size):
        """Read the single button line and match press patterns.

        The function samples a gpiod input line repeatedly and builds a
        short history string of '1'/'0' values. It checks this history
        against supplied regular expression patterns and returns the
        matching event key (e.g. 'click', 'press').
        """
        CHIP_NAME = os.environ['BUTTON_CHIP']
        LINE_NUMBER = os.environ['BUTTON_LINE']

        s = ''
        chip = gpiod.Chip(str(CHIP_NAME))
        line = chip.get_line(int(LINE_NUMBER))
        line.request(consumer='hat_button', type=gpiod.LINE_REQ_DIR_OUT)
        line.set_value(1)

        while True:
            s = s[-size:] + str(line.get_value())
            for t, p in pattern.items():
                if p.match(s):
                    return t
            time.sleep(0.1)


    def watch_key(q=None):
        """Background loop that pushes detected key events into queue `q`.

        Builds regex patterns based on configuration times to detect single
        clicks, double clicks and long presses.
        """
        size = int(conf['time']['press'] * 10)
        wait = int(conf['time']['twice'] * 10)
        pattern = {
            'click': re.compile(r'1+0+1{%d,}' % wait),
            'twice': re.compile(r'1+0+1+0+1{3,}'),
            'press': re.compile(r'1+0{%d,}' % size),
        }

        while True:
            q.put(read_key(pattern, size))


    def get_disk_info(cache={}):
        """Return cached disk usage info for root and known block devices.

        Results are cached for 30s to avoid frequent shell calls.
        """
        if not cache.get('time') or time.time() - cache['time'] > 30:
            info = {}
            cmd = "df -h | awk '$NF==\"/\"{printf \"%s\", $5}'"
            info['root'] = check_output(cmd)
            for x in conf['disk']:
                cmd = "df -Bg | awk '$1==\"/dev/{}\" {{printf \"%s\", $5}}'".format(x)
                info[x] = check_output(cmd)
            cache['info'] = list(zip(*info.items()))
            cache['time'] = time.time()

        return cache['info']


    def slider_next(pages):
        """Advance an index and return the next page from `pages`."""
        conf['idx'].value += 1
        return pages[conf['idx'].value % len(pages)]


    def slider_sleep():
        """Sleep for the configured slider interval."""
        time.sleep(conf['slider']['time'])


    def fan_temp2dc(t):
        """Convert temperature `t` (°C) to a duty-cycle fraction.

        Iterates the ordered `lv2dc` mapping and returns the first matching
        duty-cycle where the temperature is above the configured threshold.
        """
        for lv, dc in lv2dc.items():
            if t >= conf['fan'][lv]:
                return dc
        return 0.999


    def fan_switch():
        """Toggle the `conf['run']` flag used to enable/disable fan control."""
        conf['run'].value = not conf['run'].value


    def get_func(key):
        """Map a raw key string to a configured action name (default 'none')."""
        return conf['key'].get(key, 'none')


    # Global configuration container. `idx` and `run` are multiprocessing
    # Values so they can be shared between processes/threads safely.
    conf = {'disk': [], 'idx': mp.Value('d', -1), 'run': mp.Value('d', 1)}
    conf.update(read_conf())
    """Toggle the fan run flag (`conf['run']`)."""
    conf['run'].value = not conf['run'].value


def get_func(key):
    """Lookup a key mapping (click/twice/press) to an action name."""
    return conf['key'].get(key, 'none')


# Global runtime configuration shared across modules. `conf` contains
# some pre-initialized multiprocessing values (`idx` and `run`) and a
# `disk` list that will be filled by `get_blk()`.
conf = {'disk': [], 'idx': mp.Value('d', -1), 'run': mp.Value('d', 1)}
conf.update(read_conf())
