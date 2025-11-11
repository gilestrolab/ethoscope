import time


class MockSerial:
    def write(self, str):
        t = time.time()
        print(f"{t} : MockSerial > {str}")

    def close(self):
        t = time.time()
        print(f"{t} : MockSerial closed")
