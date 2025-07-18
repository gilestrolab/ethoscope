from ethoscope.core.monitor import Monitor
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.roi_builders.target_roi_builder import SleepMonitorWithTargetROIBuilder
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.drawers.drawers import DefaultDrawer
from ethoscope.utils.io import SQLiteResultWriter
from optparse import OptionParser
import os

import datetime
import calendar

if __name__ == '__main__':

    parser = OptionParser()
    parser.add_option("-i", "--input", dest="input", help="The input .db file")
    parser.add_option("-p", "--prefix", dest="prefix", help="The prefix for result dir")



    (options, args) = parser.parse_args()
    option_dict = vars(options)
    INPUT =  option_dict["input"]
    OUTPUT =  os.path.splitext(INPUT)[0] + ".db"
    OUTPUT =  option_dict["prefix"] + "/" + OUTPUT
    try:
        os.makedirs(os.path.dirname(OUTPUT))
    except OSError:
        pass
    print(INPUT + " ===> " + OUTPUT)

    cam  = MovieVirtualCamera(INPUT)
    rois = SleepMonitorWithTargetROIBuilder().build(cam)
    drawer = DefaultDrawer(draw_frames=True)
    mon = Monitor(cam, AdaptiveBGModel, rois)

    #fixme
    date = datetime.datetime.strptime("2016-05-03_08-25-02", "%Y-%m-%d_%H-%M-%S")
    ts = int(calendar.timegm(date.timetuple()))
    #todo parse metadata from filename
    # metadata = {}

    with SQLiteResultWriter(OUTPUT, rois) as rw:
        mon.run(rw, drawer)
