__author__ = 'quentin'


import numpy as np
import matplotlib.pyplot as plt
from sklearn.cluster import MeanShift, estimate_bandwidth


np.random.seed(seed=5)
arr = np.random.uniform(size=(100,100))
arr = arr > 0.5

#arr[ 10:90,5:70] = 0
xy = np.where(arr)


pts = np.column_stack(xy)

X= pts




bandwidth = estimate_bandwidth(X, quantile=0.2, n_samples=100)


bandwidth = 30

ms = MeanShift(bandwidth=bandwidth, bin_seeding=True)
ms.fit(X)



labels = ms.labels_
cluster_centers = ms.cluster_centers_

labels_unique = np.unique(labels)
n_clusters_ = len(labels_unique)

print(("number of estimated clusters : %d" % n_clusters_))

###############################################################################
# Plot result
import matplotlib.pyplot as plt
from itertools import cycle

plt.figure(1)
plt.clf()

colors = cycle('bgrcmykbgrcmykbgrcmykbgrcmyk')
for k, col in zip(list(range(n_clusters_)), colors):
    my_members = labels == k
    cluster_center = cluster_centers[k]
    plt.plot(X[my_members, 0], X[my_members, 1], col + '.')
    plt.plot(cluster_center[0], cluster_center[1], 'o', markerfacecolor=col,
             markeredgecolor='k', markersize=14)
plt.title('Estimated number of clusters: %d' % n_clusters_)
plt.show()
#
