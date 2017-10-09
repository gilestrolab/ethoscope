# Standard imports
import cv2
import numpy as np
import os
import matplotlib.pyplot as plt

TEST_FRAMES = "/data/Diana/data_node/random_frames_Nflies"
IMAGE_FORMAT =".jpg"

imfilelist = [os.path.join(TEST_FRAMES, f) for f in os.listdir(TEST_FRAMES) if f.endswith(IMAGE_FORMAT)]


for el in imfilelist:
    # Read image
    im = cv2.imread(el, cv2.IMREAD_GRAYSCALE)


    # Setup SimpleBlobDetector parameters.
    params = cv2.SimpleBlobDetector_Params()

    # Change thresholds
    params.minThreshold = 10;
    params.maxThreshold = 200;

    # Filter by Area.
    params.filterByArea = True
    params.minArea = 10
    params.maxArea = 300

    # Filter by Circularity
    params.filterByCircularity = True
    params.minCircularity = 0.2

    # Filter by Convexity
    params.filterByConvexity = True
    params.minConvexity = 0.3

    # Filter by Inertia
    params.filterByInertia = True
    params.minInertiaRatio = 0.01

    # Create a detector with the parameters
    ver = (cv2.__version__).split('.')
    if int(ver[0]) < 3 :
        detector = cv2.SimpleBlobDetector(params)
    else :
        detector = cv2.SimpleBlobDetector_create(params)


    # Detect blobs.
    keypoints = detector.detect(im)


    selected_keypoints = []
    for keypoint in keypoints:
        if (keypoint.size > 2.4) & (keypoint.size < 4) & (keypoint.pt[0] > 400):
            selected_keypoints.append(keypoint)

    sizes = []
    x_blobs = []
    y_blobs = []
    for keypoint in selected_keypoints:
        x_blobs.append(keypoint.pt[0])
        y_blobs.append(keypoint.pt[1])
        sizes.append(keypoint.size)


    plt.hist(x_blobs)
    plt.show()

   # print keypoints[0].pt[1]
   # print keypoints[0].size

    # Draw detected blobs as red circles.
    # cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS ensures the size of the circle corresponds to the size of blob

    selected_keypoints = []
    for keypoint in keypoints:
        if (keypoint.size > 2.4) & (keypoint.size < 4):
            selected_keypoints.append(keypoint)

    im_with_keypoints = cv2.drawKeypoints(im, keypoints, np.array([]), (0,0,255), cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)

    # Show keypoints
    cv2.imshow("Keypoints", im_with_keypoints)
    cv2.waitKey(0)