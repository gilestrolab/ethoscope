__author__ = 'quentin'

import json
import sys
if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise Exception("Wrong number of args, JSON_FILE, field, value")
    file = sys.argv[1]
    field = str(sys.argv[2])


    with open(file) as f:
        data = json.load(f)
        if len(sys.argv) ==3:
            assert(field in data)
            exit()
        value = str(sys.argv[3])
        if data[field] != value:
            raise Exception("%s != %s" % (data[field],value))





