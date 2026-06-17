#!/usr/bin/python3
"""
oled.py - OLED display helpers for the ROCKPi SATA HAT.

Provides initialization of the SSD1306 display, rendering helpers and a
small pager/slider UI that pulls data from `misc` and renders text
pages onto the OLED.
"""

import os
import time

import adafruit_ssd1306
import board
import digitalio
import busio
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
import multiprocessing as mp

import misc

# Preload fonts used by the UI (sizes 10,11,12,14)
font = {
    '10': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 10),
    '11': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 11),
    '12': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 12),
    '14': ImageFont.truetype('fonts/DejaVuSansMono-Bold.ttf', 14),
}


def disp_init():
    """Initialize the SSD1306 display using board pins from env vars.

    Reads `OLED_RESET`, `SCL` and `SDA` from the environment and
    configures the I2C-based display. Clears the framebuffer and
    returns the display object.
    """
    RESET = getattr(board.pin, os.environ['OLED_RESET'])
    i2c = busio.I2C(getattr(board.pin, os.environ['SCL']), getattr(board.pin, os.environ['SDA']))
    disp = adafruit_ssd1306.SSD1306_I2C(128, 32, i2c, reset=digitalio.DigitalInOut(RESET))
    disp.fill(0)
    disp.show()
    return disp


disp = disp_init()

# Image canvas and drawing context used for all rendering operations
image = Image.new('1', (disp.width, disp.height))
draw = ImageDraw.Draw(image)


def disp_show():
    """Push the current image to the OLED and clear the draw area.

    Honors the `misc.conf['oled']['rotate']` flag by rotating the image
    before writing if configured.
    """
    im = image.rotate(180) if misc.conf['oled']['rotate'] else image
    disp.image(im)
    disp.write_framebuf()
    draw.rectangle((0, 0, disp.width, disp.height), outline=0, fill=0)


def welcome():
    """Display a startup message on the OLED."""
    draw.text((0, 0), 'ROCKPi SATA HAT', font=font['14'], fill=255)
    draw.text((32, 16), 'Loading...', font=font['12'], fill=255)
    disp_show()


def goodbye():
    """Display a goodbye message and clear the screen after a pause."""
    draw.text((32, 8), 'Good Bye ~', font=font['14'], fill=255)
    disp_show()
    time.sleep(2)
    disp_show()  # clear


def put_disk_info():
    """Format disk information returned by `misc.get_disk_info()` into
    a list of drawable items (x,y,text,font,fill) suitable for the slider.
    """
    k, v = misc.get_disk_info()
    text1 = 'Disk: {} {}'.format(k[0], v[0])

    if len(k) == 5:
        # Multi-row layout for five entries
        text2 = '{} {}  {} {}'.format(k[1], v[1], k[2], v[2])
        text3 = '{} {}  {} {}'.format(k[3], v[3], k[4], v[4])
        page = [
            {'xy': (0, -2), 'text': text1, 'fill': 255, 'font': font['11']},
            {'xy': (0, 10), 'text': text2, 'fill': 255, 'font': font['11']},
            {'xy': (0, 21), 'text': text3, 'fill': 255, 'font': font['11']},
        ]
    elif len(k) == 3:
        # Two-line layout
        text2 = '{} {}  {} {}'.format(k[1], v[1], k[2], v[2])
        page = [
            {'xy': (0, 2), 'text': text1, 'fill': 255, 'font': font['12']},
            {'xy': (0, 18), 'text': text2, 'fill': 255, 'font': font['12']},
        ]
    else:
        # Single-line layout
        page = [{'xy': (0, 2), 'text': text1, 'fill': 255, 'font': font['14']}]

    return page


def gen_pages():
    """Generate a dictionary of pages for the slider UI.

    Each page is a list of drawable item dicts compatible with
    `PIL.ImageDraw.text(**item)` and matches what `misc.slider_next`
    expects.
    """
    pages = {
        0: [
            {'xy': (0, -2), 'text': misc.get_info('up'), 'fill': 255, 'font': font['11']},
            {'xy': (0, 10), 'text': misc.get_cpu_temp(), 'fill': 255, 'font': font['11']},
            {'xy': (0, 21), 'text': misc.get_info('ip'), 'fill': 255, 'font': font['11']},
        ],
        1: [
            {'xy': (0, 2), 'text': misc.get_info('cpu'), 'fill': 255, 'font': font['12']},
            {'xy': (0, 18), 'text': misc.get_info('men'), 'fill': 255, 'font': font['12']},
        ],
        2: put_disk_info()
    }

    return pages


def slider(lock):
    """Render the next slider page set while holding `lock`.

    Uses `misc.slider_next(gen_pages())` to iterate drawable items and
    then pushes the rendered image to the display.
    """
    with lock:
        for item in misc.slider_next(gen_pages()):
            draw.text(**item)
        disp_show()


def auto_slider(lock):
    """Automatically cycle slider pages while `misc.conf['slider']['auto']`.

    Sleeps between pages using `misc.slider_sleep()`; when auto is
    disabled, renders a single slider page.
    """
    while misc.conf['slider']['auto']:
        slider(lock)
        misc.slider_sleep()
    else:
        slider(lock)


if __name__ == '__main__':
    # For quick local testing: create a multiprocessing lock and run
    # the auto slider loop.
    lock = mp.Lock()
    auto_slider(lock)
