import os

with open("/sys/class/i2c-adapter/i2c-1/new_device", "w") as f:
    f.write("ds1307 0x68\n")
os.system('hwclock -s')
