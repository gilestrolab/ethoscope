__author__ = 'quentin'

from ethoscope.tracking.cameras import MovieVirtualCamera

# Build ROIs from greyscale image
from ethoscope.tracking.roi_builders import SleepMonitorWithTargetROIBuilder
from ethoscope.tracking.trackers import AdaptiveBGModel
from ethoscope.tracking.monitor import Monitor



import optparse
import os
import cv2


class MyMonitor(Monitor):


    _every_ms = 60*1000 *10  #10m
    _duration = 10*1000  #10m

    def run(self,out_dir, result_writer = None):
        vw_ls = []
        self._is_running = True
        t0=0

        for i,(t, frame) in enumerate(self._camera):

            if t % self._every_ms == 0:
                print("making video at", t)

                if vw_ls:
                    for v in vw_ls:
                        v.release()
                vw_ls = []

                for j,track_u in enumerate(self._unit_trackers):


                    out_file_basename = "%02d_%i.avi" %(track_u.roi.idx, t/1000)

                    out_file_path = os.path.join(out_dir,out_file_basename)
                    w, h = track_u.roi.get_feature_dict()["w"], track_u.roi.get_feature_dict()["h"]


                # cv.CV_FOURCC('I', 'Y', 'U', 'V'),
                    vw = cv2.VideoWriter(out_file_path, cv2.cv.CV_FOURCC(*'DIVX'), 20, (w,h))
                    vw_ls.append(vw)
                    t0 = t

            if t- t0 > self._duration :
                if i % 1000 == 0:
                    print(t/(36000*21), t, 21*1000*3600)
                continue

            for j,track_u in enumerate(self._unit_trackers):
                if not vw_ls:
                    break
                x,y,w,h = track_u.roi.rectangle

                out = frame[y : y + h, x : x +w,:]

                vw_ls[j].write(out)





CHUNK_LENGTH = 10 #s
if __name__ == "__main__":

    parser = optparse.OptionParser()
    parser.add_option("-o", "--output", dest="out", help="the output dir", type="str")
    parser.add_option("-i", "--input", dest="input", help="the output video file", type="str")

    (options, args) = parser.parse_args()

    option_dict = vars(options)

    cam = MovieVirtualCamera(option_dict ["input"], use_wall_clock=False)


    roi_builder = SleepMonitorWithTargetROIBuilder()
    rois = roi_builder(cam)
    cam.restart()
    mon = MyMonitor(cam,AdaptiveBGModel,rois)
    mon.run(option_dict["out"])


    #
    # for t in range(60 * 10 ,20 *60, 5*60):
    #
    #     for r in rois:
    #
    #         d = r.get_feature_dict()
    #         out_file_basename = "%02d_%i.mp4" %(d["idx"], t)
    #         out_file_path = os.path.join(option_dict["out"],out_file_basename)
    #         print "Generating %s" % out_file_path
    #         command ='ffmpeg  -n -ss %i -i %s   -t %i -vf "crop=%i:%i:%i:%i"  %s' %(
    #             t,
    #             option_dict["input"],
    #             CHUNK_LENGTH,
    #             d["w"],
    #             d["h"],
    #             d["x"],
    #             d["y"],
    #             out_file_path
    #         )
    #
    #         os.system(command)
    #
