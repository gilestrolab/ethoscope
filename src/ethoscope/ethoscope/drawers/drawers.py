__author__ = 'quentin'

import cv2
try:
    from cv2.cv import CV_FOURCC as VideoWriter_fourcc
    from cv2.cv import CV_AA as LINE_AA
except ImportError:
    from cv2 import VideoWriter_fourcc
    from cv2 import LINE_AA

from ethoscope.utils.description import DescribedObject
import os

class BaseDrawer(object):
    def __init__(self, video_out=None, draw_frames=True, video_out_fourcc="DIVX", video_out_fps=25):
        """
        A template class to annotate and save the processed frames. It can also save the annotated frames in a video
        file and/or display them in a new window. The :meth:`~ethoscope.drawers.drawers.BaseDrawer._annotate_frame`
        abstract method defines how frames are annotated.

        :param video_out: The path to the output file (.avi)
        :type video_out: str
        :param draw_frames: Whether frames should be displayed on the screen (a new window will be created).
        :type draw_frames: bool
        :param video_out_fourcc: When setting ``video_out``, this defines the codec used to save the output video (see `fourcc <http://www.fourcc.org/codecs.php>`_)
        :type video_out_fourcc: str
        :param video_out_fps: When setting ``video_out``, this defines the output fps. typically, the same as the input fps.
        :type video_out_fps: float
        """
        self._video_out = video_out
        self._draw_frames= draw_frames
        self._video_writer = None
        self._live_window_name = "ethoscope_" + str(os.getpid())
        self._video_out_fourcc = video_out_fourcc
        self._video_out_fps = video_out_fps

        if draw_frames:
            cv2.namedWindow(self._live_window_name, cv2.WINDOW_AUTOSIZE)
            
        self._last_drawn_frame = None

    def _annotate_frame(self,img, positions, tracking_units):
        """
        Abstract method defining how frames should be annotated.
        The `img` array, which is passed by reference, is meant to be modified by this method.

        :param img: the frame that was just processed
        :type img: :class:`~numpy.ndarray`
        :param positions: a list of positions resulting from analysis of the frame
        :type positions: list(:class:`~ethoscope.core.data_point.DataPoint`)
        :param tracking_units: the tracking units corresponding to the positions
        :type tracking_units: list(:class:`~ethoscope.core.tracking_unit.TrackingUnit`)
        :return:
        """
        raise NotImplementedError

    @property
    def last_drawn_frame(self):
        return self._last_drawn_frame

    def draw(self,img, positions, tracking_units, reference_points=None):
        """
        Draw results on a frame.

        :param img: the frame that was just processed
        :type img: :class:`~numpy.ndarray`
        :param positions: a list of positions resulting from analysis of the frame by a tracker
        :type positions: list(:class:`~ethoscope.core.data_point.DataPoint`)
        :param tracking_units: the tracking units corresponding to the positions
        :type tracking_units: list(:class:`~ethoscope.core.tracking_unit.TrackingUnit`)
        :return:
        """

        #self._last_drawn_frame = img.copy()
        self._last_drawn_frame = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        self._annotate_frame(self._last_drawn_frame, positions, tracking_units, reference_points)

        if self._draw_frames:
            cv2.imshow(self._live_window_name, self._last_drawn_frame )
            cv2.waitKey(1)

        if self._video_out is None:
            return

        if self._video_writer is None:
            self._video_writer = cv2.VideoWriter(self._video_out, VideoWriter_fourcc(*self._video_out_fourcc),
                                                 self._video_out_fps, (img.shape[1], img.shape[0]))

        self._video_writer.write(self._last_drawn_frame)

    def __del__(self):
        if self._draw_frames:
            cv2.waitKey(1)
            cv2.destroyAllWindows()
            cv2.waitKey(1)
        if self._video_writer is not None:
            self._video_writer.release()


class NullDrawer(BaseDrawer):
    def __init__(self):
        """
        A drawer that does nothing (no video writing, no annotation, no display on the screen).

        :return:
        """
        super(NullDrawer,self).__init__( draw_frames=False)
    def _annotate_frame(self,img, positions, tracking_units):
        pass


class DefaultDrawer(BaseDrawer):
    def __init__(self, video_out= None, draw_frames=False, **kwargs):
        """
        The default drawer. It draws ellipses on the detected objects and polygons around ROIs. When an "interaction"
        see :class:`~ethoscope.stimulators.stimulators.BaseInteractor` happens within a ROI,
        the ellipse is red, blue otherwise.

        :param video_out: The path to the output file (.avi)
        :type video_out: str
        :param draw_frames: Whether frames should be displayed on the screen (a new window will be created).
        :type draw_frames: bool
        """
        super(DefaultDrawer,self).__init__(video_out=video_out, draw_frames=draw_frames, **kwargs)

    def _draw_stimulator_indicator(self, img, roi, stimulator_state):
        """
        Draw stimulator state indicator in ROI corner.
        
        :param img: the frame to draw on
        :param roi: the ROI object
        :param stimulator_state: "inactive", "scheduled", or "stimulating"
        """
        # Position indicator in top-right corner of ROI  
        x, y = roi.offset
        roi_points = roi.polygon
        # Calculate approximate ROI width from polygon points
        roi_width = max([p[0] for p in roi_points]) - min([p[0] for p in roi_points])
        
        center = (int(x + roi_width - 20), int(y + 20))
        radius = 8
        
        if stimulator_state == "inactive":
            # Empty white circle (planned but not scheduled)
            cv2.circle(img, center, radius, (255,255,255), 1)
        elif stimulator_state == "scheduled":
            # Lightly filled gray circle (scheduled but not stimulating)  
            cv2.circle(img, center, radius, (128,128,128), -1)
            cv2.circle(img, center, radius, (255,255,255), 1)
        elif stimulator_state == "stimulating":
            # Full white circle (actively stimulating)
            cv2.circle(img, center, radius, (255,255,255), -1)

    def _annotate_frame(self, img, positions, tracking_units, reference_points=None):
        '''
        Annotate frames with information about ROIs and moving objects
        '''
        if img is None:
            return
        
        try:
            for p in reference_points:
                cv2.drawMarker(img, (int(p[0]), int(p[1])), color=(0,255,0), markerType=cv2.MARKER_CROSS, thickness=2)
        except:
            #noreferencepoints
            pass
        
        for track_u in tracking_units:

            x,y = track_u.roi.offset
            # Position text at top-left corner of ROI instead of middle
            text_x = int(x + 10)  # Small offset from edge
            text_y = int(y + 40)  # Position further down from top of ROI
            
            roi_text = str(track_u.roi.idx)
            
            # Draw text with black outline for better visibility
            cv2.putText(img, roi_text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,0), 4)  # Black outline
            # label ROI with its number - larger, white text
            cv2.putText(img, roi_text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255,255,255), 2)
            
            # draw the shape of the ROI
            black_colour = (0, 0, 0)
            roi_colour = (0, 255, 0)
            sub_roi_colour = (255, 0, 0)
            cv2.drawContours(img,[track_u.roi.polygon],-1, black_colour, 3, LINE_AA)
            cv2.drawContours(img,[track_u.roi.polygon],-1, roi_colour, 1, LINE_AA)
            
            # Add stimulator state indicator
            try:
                stimulator_state = track_u.stimulator.get_stimulator_state()
                self._draw_stimulator_indicator(img, track_u.roi, stimulator_state)
            except (AttributeError, Exception):
                # Handle cases where stimulator doesn't support state tracking
                pass
            #cv2.drawContours(img,track_u.roi.regions, -1, sub_roi_colour, 1, LINE_AA)
            try:
                pos_list = positions[track_u.roi.idx]
            except KeyError:
                continue

            for pos in pos_list:
                colour = (0 ,0, 255)
                try:
                    if pos["has_interacted"]:
                        colour = (255, 0,0)
                except KeyError:
                    pass
                
                # Draw the ellipse around the fly
                #cv2.ellipse(img,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]), black_colour, 3, LINE_AA)
                cv2.ellipse(img,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]), colour, 1, LINE_AA)
