__author__ = 'quentin'

import glob
import cv2
import optparse
import os
import random

CHUNK_LENGTH = 10 #s
INSTRUCTION_FILE = "instructions.png"

allowed_keys = ["n", "w", "r", "g", "i"]


pos = None

def position(event, x, y, flags, param):
    global pos
    if event == cv2.EVENT_LBUTTONUP or event == cv2.EVENT_RBUTTONUP:
        pos = (x, y)



if __name__ == "__main__":

    parser = optparse.OptionParser()
    parser.add_option("-i", "--input", dest="input", help="the input path", type="str")
    parser.add_option("-u", "--user", dest="user", help="who is annotating", type="str")


    (options, args) = parser.parse_args()

    allowed_keys.extend([k.upper() for k in allowed_keys])
    allowed_keys = set([ord(k) for k in allowed_keys])

    option_dict = vars(options)

    user = option_dict["user"]
    if not user:
        raise Exception("A user (-u) should be specified")

    lst = glob.glob(os.path.join(option_dict["input"],"*.avi"))
    random.seed(1)

    random.shuffle(lst)

    instruction_array = cv2.imread(os.path.join(option_dict["input"],INSTRUCTION_FILE))
    if instruction_array is None:
        raise Exception("The instruction image is not there")
    cv2.namedWindow("window")
    cv2.setMouseCallback("window", position)

    print(len(lst), "videos to annotate")

    while len(lst) > 0:
        f = lst[-1]
        out = os.path.splitext(f)[0] + "_%s.txt" % user
        cap = cv2.VideoCapture(f)
        r,c = cap.read()
        h0,w0,d = c.shape
        w,h = w0 *3, h0 * 3
        c = cv2.resize(c,dsize=(w,h), interpolation=cv2.cv.CV_INTER_CUBIC)
        global pos
        pos = None
        while pos is None:

            cv2.imshow("window",c)
            cv2.waitKey(1)



        rel_pos = pos[0]/float(w), pos[1]/float(w)
        while True:
            r,c = cap.read()

            if not r:
                break
            c = cv2.resize(c,dsize=(w,h),interpolation=cv2.cv.CV_INTER_CUBIC)

            cv2.imshow("window",c)
            cv2.waitKey(10)

        cv2.imshow("window",instruction_array)
        print("Saving " + out)
        k1 = cv2.waitKey(-1) & 0xFF

        if k1 not in allowed_keys:
            print(k1)
            print("replaying")
            continue



        cv2.imshow("window",instruction_array/3)
        print("You have pressed: " + chr(k1))
        print("CONFIRM using ENTER")

        k2 = cv2.waitKey(-1) & 0xFF
        if k2 != 10:
            print("NOT confirmed. REPLAYING")
            continue
        with open(out, "w") as o:
            tpl = (chr(k1),rel_pos[0], rel_pos[1])
            print(tpl)
            o.write("%s,%f,%f" % tpl)


        lst.pop()

    print("FINISHED!! BOOM!!!")


