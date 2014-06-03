import pickle, json

def save(data):
    f = open('savedRois', 'wb')
    pickle.dump(data, f)
    f.close()
    print("data saved")


def load():
    f= open('savedRois', 'rb')
    data = pickle.load(f)
    return data
    
def writeMask(data):

    ROIS = [] #List of tuples ((x,y),(x,y1),(x1,y),(x1,y1))
    referencePoints= "none" #list of pints [[[x,y,r]]] Ask Giorgio, what they mean.
    pointsToTrack = [] #list of numbers [1, 1, 1]
    serial = "NO_SERIAL"
    #from data create ROIS, referencePoints and pointsToTrack
    scalex = int(1280/500)
    scaley = int(720/300)
    for key,roi in data.items():
        if key == 'roi':
            for element in roi['rois']:
                p = element['ROI']
                ROIS.append(((p[0]*scalex,p[1]*scaley),
                             (p[0]*scalex,p[3]*scaley),
                             (p[2]*scalex,p[3]*scaley), 
                             (p[2]*scalex,p[1]*scaley)))
                #referencePoints.append(element['referencePoints'])
                pointsToTrack.append(element['pointsToTrack'])

            print (ROIS)
            print(pointsToTrack)
    data = {'ROIS':ROIS,'referencePoints':referencePoints,
            'pointsToTrack':pointsToTrack,'serial':str(serial)}
    f = open('mask.msk', 'w')
    json.dump(data,f)
    #pickle.dump(str(ROIS), f)
    #pickle.dump(str(referencePoints),f)
    #pickle.dump(str(pointsToTrack),f)
    f.close()

#ROIS [((221, 55), (1066, 55), (1066, 149), (221, 149)), ((161, 169), (1092, 169), (1092, 295), (161, 295)), ((185, 385), (1186, 385), (1186, 517), (185, 517))]
#[((221, 55), (1066, 55), (1066, 149), (221, 149)), ((161, 169), (1092, 169), (1092, 295), (161, 295)), ((185, 385), (1186, 385), (1186, 517), (185, 517))]
#poins to track: [1, 1, 1]
#Reference points [[[866 374  12]]]
#Serial: 04D40D60
