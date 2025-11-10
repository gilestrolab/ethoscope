import time


class MockSerial:
    def write(self, str):
        t = time.time()
        print("%i : MockSerial > %s" % (t, str))

    def close(self):
        t = time.time()
        print("%i : MockSerial closed" % t)
