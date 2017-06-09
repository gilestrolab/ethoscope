"""
A small script to demonstrate the optomotor in public outreach and talks...

"""

import curses
import time
from ethoscope.hardware.interfaces.optomotor import OptoMotor
from picamera import PiCamera




om = OptoMotor(do_warm_up=False)




stdscr = curses.initscr()
curses.cbreak()
curses.noecho()
stdscr.keypad(1)


try:

    camera = PiCamera()
    camera.resolution = (1280, 960)
    camera.start_preview()

    height,width = stdscr.getmaxyx()
    num = min(height,width)

    key = 32
    mode = ord('o')

    mode_dic = {
        ord('o'): {'name': ' OPTO',
                   'colour': curses.COLOR_RED,
                   'key_to_channel': {0: 1, 1: 3, 2: 5, 3: 7, 4: 9,
                                      5: 23, 6: 21, 7: 19, 8: 17, 9: 15}
                   },
        ord('m'): {'name': 'MOTOR',
                   'colour': curses.COLOR_BLUE,
                   'key_to_channel': {0: 0, 1: 2, 2: 4, 3: 6, 4: 8,
                                      5: 22, 6: 20, 7: 18, 8: 16, 9: 14}
                    }

        }
    while True:
        stdscr.addstr(0, 0, mode_dic[mode]["name"] + " mode",mode_dic[mode]["colour"] | curses.A_BOLD)
        try:
            str = chr(key) + " "
            stdscr.addstr(1, 0, "Press digit [0-9]: " + str)
        except:
            stdscr.addstr(1 - 1, 0, "Press digit [0-9]:   ")

        stdscr.refresh()

        key = stdscr.getch()
        if ord('0') <= key <= ord('9'):
            n = int(chr(key))
            channel = mode_dic[mode]["key_to_channel"][n]
            om.send(channel, 1000,1000)
        elif key in mode_dic.keys():
            mode = key
        else:
            curses.beep()
            curses.flash()
            continue

        stdscr.refresh()
        time.sleep(0.05)


    #
finally:
    curses.nocbreak()
    stdscr.keypad(0)
    curses.echo()
    curses.endwin()
    camera.stop_preview()
