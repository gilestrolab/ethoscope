

from ethoscope.hardware.interfaces.odour_delivery_device import OdourDelivererInterface


o = OdourDelivererInterface("/dev/ttyUSB1")

import time
i = 1
while True:
    time.sleep(1)
    print(i)
    i += 1
    if i == 15:
        o.interact(channel=1, pos=1)
    elif i == 17:
        o.interact(channel=1, pos=2)

