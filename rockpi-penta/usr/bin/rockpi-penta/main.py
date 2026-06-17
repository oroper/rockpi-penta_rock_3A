#!/usr/bin/env python3
"""
main.py - entrypoint to start services and UI threads for the board.

This script initializes optional OLED UI support, starts background
threads for key handling, the OLED UI, and the fan controller.
"""

import queue
import threading
import traceback

import fan
import misc

try:
    import oled

    top_board = True  # OLED/display present
except Exception as ex:
    traceback.print_exc()
    top_board = False  # headless or not the top board

# Shared queue and lock used by input/UI threads
q = queue.Queue()
lock = threading.Lock()

# Action dispatch table mapping input actions to callables.
# Keys correspond to values returned by misc.get_func().
action = {
    'none': lambda: 'nothing',
    'slider': lambda: oled.slider(lock),  # show slider on OLED
    'switch': lambda: misc.fan_switch(),  # toggle fan mode
    'reboot': lambda: misc.check_call('reboot'),
    'poweroff': lambda: misc.check_call('poweroff'),
}


def receive_key(q):
    """Thread target: consume keys from `q` and dispatch actions.

    Blocks on `q.get()` and looks up the corresponding action via
    `misc.get_func()` before invoking the callable from `action`.
    """
    while True:
        func = misc.get_func(q.get())
        action[func]()


if __name__ == '__main__':

    if top_board:
        # Initialize OLED UI and background threads when display present
        oled.welcome()
        p0 = threading.Thread(target=receive_key, args=(q,), daemon=True)
        p1 = threading.Thread(target=misc.watch_key, args=(q,), daemon=True)
        p2 = threading.Thread(target=oled.auto_slider, args=(lock,), daemon=True)
        p3 = threading.Thread(target=fan.running, daemon=True)

        p0.start()
        p1.start()
        p2.start()
        p3.start()
        try:
            # Keep main thread alive until fan.running() exits
            p3.join()
        except KeyboardInterrupt:
            print("GoodBye ~")
            oled.goodbye()

    else:
        # No OLED: run fan controller in foreground so process persists
        p3 = threading.Thread(target=fan.running, daemon=False)
        p3.start()
