__author__ = 'quentin'
import cv2
import numpy as np
import itertools

def merge_blobs(contours, prop = .5):
    """
    Merge together contour according to their position and size.
    If the distance between two blobs is smaller than the longest axis of, at least, one of them,
    then they get merged.
    This algorithm is aimed at merging together part of the same physical object without morphological operations.


    :param contours: list of contours
    :return: the convex hulls of the merged contours, list of contourss
    """
    idx_pos_w = []
    for i, c in enumerate(contours):
        (x,y) ,(w,h), angle  = cv2.minAreaRect(c)
        w = max(w,h)
        h = min(w,h)
        idx_pos_w.append((i, x+1j*y,w + h))

    pairs_to_group = []
    for a,b in itertools.combinations(idx_pos_w,2):

        d = abs(a[1] - b[1])
        wm = max(a[2], b[2]) * prop
        if d < wm:
            pairs_to_group.append({a[0], b[0]})


    if len(pairs_to_group) == 0:
        return contours

    repeat = True
    out_sets = pairs_to_group

    while repeat:
        comps = out_sets
        out_sets = []
        repeat=False
        for s in comps:
            connected = False
            for i,o in enumerate(out_sets):
                if o & s:
                    out_sets[i] = s | out_sets[i]
                    connected = True
                    repeat=True
            if not connected:
                out_sets.append(s)

    out_hulls = []
    for c in comps:
        out_hulls.append(np.concatenate([contours[s] for s in c]))

    out_hulls= [cv2.convexHull(o) for o in out_hulls]

    return out_hulls
