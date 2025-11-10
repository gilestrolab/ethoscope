__author__ = "quentin"

import logging

import cv2

try:
    from cv2.cv import CV_AA as LINE_AA
    from cv2.cv import CV_FOURCC as VideoWriter_fourcc
except ImportError:
    from cv2 import LINE_AA
    from cv2 import VideoWriter_fourcc

import os


class BaseDrawer:
    def __init__(
        self,
        video_out=None,
        draw_frames=True,
        video_out_fourcc="DIVX",
        video_out_fps=25,
    ):
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
        self._draw_frames = draw_frames
        self._video_writer = None
        self._live_window_name = "ethoscope_" + str(os.getpid())
        self._video_out_fourcc = video_out_fourcc
        self._video_out_fps = video_out_fps

        if draw_frames:
            cv2.namedWindow(self._live_window_name, cv2.WINDOW_AUTOSIZE)

        self._last_drawn_frame = None

    def _annotate_frame(self, img, positions, tracking_units):
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

    def draw(self, img, positions, tracking_units, reference_points=None):
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

        # self._last_drawn_frame = img.copy()
        self._last_drawn_frame = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        self._annotate_frame(
            self._last_drawn_frame, positions, tracking_units, reference_points
        )

        if self._draw_frames:
            cv2.imshow(self._live_window_name, self._last_drawn_frame)
            cv2.waitKey(1)

        if self._video_out is None:
            return

        if self._video_writer is None:
            self._video_writer = cv2.VideoWriter(
                self._video_out,
                VideoWriter_fourcc(*self._video_out_fourcc),
                self._video_out_fps,
                (img.shape[1], img.shape[0]),
            )

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
        super(NullDrawer, self).__init__(draw_frames=False)

    def _annotate_frame(self, img, positions, tracking_units):
        pass


class DefaultDrawer(BaseDrawer):
    def __init__(self, video_out=None, draw_frames=False, **kwargs):
        """
        The default drawer. It draws ellipses on the detected objects and polygons around ROIs. When an "interaction"
        see :class:`~ethoscope.stimulators.stimulators.BaseInteractor` happens within a ROI,
        the ellipse is red, blue otherwise.

        :param video_out: The path to the output file (.avi)
        :type video_out: str
        :param draw_frames: Whether frames should be displayed on the screen (a new window will be created).
        :type draw_frames: bool
        """
        super(DefaultDrawer, self).__init__(
            video_out=video_out, draw_frames=draw_frames, **kwargs
        )

    def _draw_stimulator_indicator(self, img, roi, stimulator_state):
        """
        Draw stimulator state indicator in ROI corner with enhanced visibility.

        :param img: the frame to draw on
        :param roi: the ROI object
        :param stimulator_state: "inactive", "scheduled", or "stimulating"
        """

        try:
            # Position indicator in top-right corner of ROI
            x, y = roi.offset
            roi_points = roi.polygon

            # More robust ROI width calculation with safety checks
            if len(roi_points) > 0:
                try:
                    x_coords = [p[0] for p in roi_points]
                    y_coords = [p[1] for p in roi_points]
                    roi_width = max(x_coords) - min(x_coords)
                    roi_height = max(y_coords) - min(y_coords)

                    # Ensure minimum size
                    roi_width = max(roi_width, 50)
                    roi_height = max(roi_height, 50)
                except (TypeError, IndexError, ValueError):
                    roi_width = 100  # Fallback
                    roi_height = 100
            else:
                roi_width = 100  # Fallback
                roi_height = 100

            # Align indicator vertically with the ROI number label (which is at y + 40), but 6 pixels higher
            label_y = int(y + 40) - 6  # 6 pixels above the ROI label position
            center_x = max(15, min(img.shape[1] - 15, int(x + roi_width - 20)))
            center_y = max(15, min(img.shape[0] - 15, label_y))
            center = (center_x, center_y)

            # Make indicator larger and more prominent
            outer_radius = 15
            inner_radius = 12

            # Visual indicators according to user specifications
            if stimulator_state == "inactive":
                # Programmed but not started -> empty circles with black border
                cv2.circle(img, center, inner_radius, (0, 0, 0), 2)  # Black border only

            elif stimulator_state == "scheduled":
                # During stimulation time window -> circles filled in white
                cv2.circle(img, center, inner_radius, (255, 255, 255), -1)  # White fill
                cv2.circle(img, center, inner_radius, (0, 0, 0), 1)  # Thin black border

            elif stimulator_state == "stimulating":
                # During actual stimulation -> circle filled in blue
                cv2.circle(
                    img, center, inner_radius, (255, 0, 0), -1
                )  # Blue fill (BGR format)
                cv2.circle(img, center, inner_radius, (0, 0, 0), 1)  # Thin black border

            else:
                # Unknown state - draw red warning indicator
                cv2.circle(
                    img, center, inner_radius, (0, 0, 255), -1
                )  # Red fill for error
                cv2.circle(img, center, inner_radius, (0, 0, 0), 1)  # Black border
                logging.warning(
                    f"Drew UNKNOWN state indicator ({stimulator_state}) at {center}"
                )

        except Exception as e:
            logging.error(f"Error drawing stimulator indicator: {e}")
            # Draw a prominent red error indicator that's easy to spot
            try:
                # Use fallback position if center calculation failed
                fallback_x = max(15, min(img.shape[1] - 15, int(x + 30)))
                fallback_y = max(15, min(img.shape[0] - 15, int(y + 30)))
                error_center = (fallback_x, fallback_y)

                cv2.circle(
                    img, error_center, 10, (0, 0, 255), -1
                )  # Red circle for error
                cv2.putText(
                    img,
                    "E",
                    (fallback_x - 3, fallback_y + 3),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.3,
                    (255, 255, 255),
                    1,
                )
                logging.error(f"Drew ERROR indicator at {error_center}")
            except Exception as e2:
                logging.error(f"Failed to draw error indicator: {e2}")
                pass

    def _annotate_frame(self, img, positions, tracking_units, reference_points=None):
        """
        Annotate frames with information about ROIs and moving objects
        """
        if img is None:
            return

        # Debug logging to confirm drawer is being called (log once)
        if not hasattr(self, "_drawer_logged"):
            logging.info(
                f"DefaultDrawer._annotate_frame first call with {len(tracking_units)} tracking units"
            )
            self._drawer_logged = True

        try:
            for p in reference_points:
                cv2.drawMarker(
                    img,
                    (int(p[0]), int(p[1])),
                    color=(0, 255, 0),
                    markerType=cv2.MARKER_CROSS,
                    thickness=2,
                )
        except:
            # noreferencepoints
            pass

        for track_u in tracking_units:

            # Debug logging for each tracking unit (log once per stimulator type)
            stimulator_type = type(track_u.stimulator).__name__
            log_key = f"stimulator_type_{track_u.roi.idx}"
            if not hasattr(self, "_stimulator_types_logged"):
                self._stimulator_types_logged = set()
            if log_key not in self._stimulator_types_logged:
                logging.info(
                    f"ROI {track_u.roi.idx}: Using stimulator type = {stimulator_type}"
                )
                self._stimulator_types_logged.add(log_key)

            x, y = track_u.roi.offset
            # Position text at top-left corner of ROI instead of middle
            text_x = int(x + 10)  # Small offset from edge
            text_y = int(y + 40)  # Position further down from top of ROI

            roi_text = str(track_u.roi.idx)

            # Draw text with black outline for better visibility
            cv2.putText(
                img,
                roi_text,
                (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2,
                (0, 0, 0),
                4,
            )  # Black outline
            # label ROI with its number - larger, white text
            cv2.putText(
                img,
                roi_text,
                (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2,
                (255, 255, 255),
                2,
            )

            # draw the shape of the ROI
            black_colour = (0, 0, 0)
            roi_colour = (0, 255, 0)
            sub_roi_colour = (255, 0, 0)
            cv2.drawContours(img, [track_u.roi.polygon], -1, black_colour, 3, LINE_AA)
            cv2.drawContours(img, [track_u.roi.polygon], -1, roi_colour, 1, LINE_AA)

            # Add stimulator state indicator with enhanced error handling
            try:
                # First check if we have a stimulator
                if track_u.stimulator is None:
                    logging.debug(f"ROI {track_u.roi.idx}: No stimulator assigned")
                    continue

                # Check if stimulator supports state tracking
                stimulator_type = type(track_u.stimulator).__name__
                has_method = hasattr(track_u.stimulator, "get_stimulator_state")

                # Log method availability once per stimulator type
                method_log_key = f"method_check_{stimulator_type}"
                if not hasattr(self, "_method_checks_logged"):
                    self._method_checks_logged = set()
                if method_log_key not in self._method_checks_logged:
                    logging.info(
                        f"Stimulator {stimulator_type} has get_stimulator_state(): {has_method}"
                    )
                    self._method_checks_logged.add(method_log_key)

                if has_method:
                    try:
                        stimulator_state = track_u.stimulator.get_stimulator_state()

                        # Log state changes for debugging
                        state_key = f"roi_{track_u.roi.idx}_state"
                        if not hasattr(self, "_last_stimulator_states"):
                            self._last_stimulator_states = {}

                        if (
                            self._last_stimulator_states.get(state_key)
                            != stimulator_state
                        ):
                            logging.info(
                                f"ROI {track_u.roi.idx}: {stimulator_type} state = {stimulator_state}"
                            )
                            self._last_stimulator_states[state_key] = stimulator_state

                        # Always draw the indicator
                        self._draw_stimulator_indicator(
                            img, track_u.roi, stimulator_state
                        )

                    except Exception as state_error:
                        logging.error(
                            f"ROI {track_u.roi.idx}: Error calling get_stimulator_state(): {state_error}"
                        )
                        # Draw error indicator using our enhanced method
                        self._draw_stimulator_indicator(img, track_u.roi, "error")

                elif type(track_u.stimulator).__name__ != "DefaultStimulator":
                    # Only warn for non-default stimulators that don't support state tracking
                    stimulator_type = type(track_u.stimulator).__name__
                    logging.warning(
                        f"ROI {track_u.roi.idx}: {stimulator_type} doesn't support get_stimulator_state() - consider updating"
                    )

                    # Draw a yellow indicator for unsupported stimulators
                    try:
                        x, y = track_u.roi.offset
                        center_x = max(15, min(img.shape[1] - 15, int(x + 30)))
                        center_y = max(15, min(img.shape[0] - 15, int(y + 25)))
                        cv2.circle(
                            img, (center_x, center_y), 10, (0, 255, 255), -1
                        )  # Yellow circle
                        cv2.putText(
                            img,
                            "?",
                            (center_x - 3, center_y + 3),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.3,
                            (0, 0, 0),
                            1,
                        )
                    except Exception as draw_error:
                        logging.error(
                            f"ROI {track_u.roi.idx}: Error drawing unsupported indicator: {draw_error}"
                        )

            except Exception as e:
                logging.error(
                    f"ROI {track_u.roi.idx}: Unexpected error in stimulator state handling: {e}"
                )
                # Use our enhanced error drawing method
                try:
                    self._draw_stimulator_indicator(img, track_u.roi, "error")
                except:
                    # Last resort - simple red dot
                    try:
                        x, y = track_u.roi.offset
                        cv2.circle(img, (int(x + 25), int(y + 25)), 5, (0, 0, 255), -1)
                    except:
                        pass
            # cv2.drawContours(img,track_u.roi.regions, -1, sub_roi_colour, 1, LINE_AA)
            try:
                pos_list = positions[track_u.roi.idx]
            except KeyError:
                continue

            for pos in pos_list:
                colour = (0, 0, 255)
                try:
                    if pos["has_interacted"]:
                        colour = (255, 0, 0)
                except KeyError:
                    pass

                # Draw the ellipse around the fly
                # cv2.ellipse(img,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]), black_colour, 3, LINE_AA)
                cv2.ellipse(
                    img,
                    ((pos["x"], pos["y"]), (pos["w"], pos["h"]), pos["phi"]),
                    colour,
                    1,
                    LINE_AA,
                )
