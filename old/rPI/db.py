import pickle, json
from os import path
basedir=path.dirname(__file__)

def save(data):
    try:
        roiList = load()
        roiList.append(data)
    except:
        """file does not exits yet, create firs entry"""
        #roiList = [{"1":{data}}]
        roiList=[]
        roiList.append(data)
    f = open(path.join(basedir,'savedRois'), 'wb')
    pickle.dump(roiList, f)
    f.close()
    print("data saved")


def load():
    f= open(path.join(basedir,'savedRois'), 'rb')
    data = pickle.load(f)
    print(data)
    f.close()
    #except:
    return data
    
def writeMask(data):
    ROIS = [] #List of tuples ((x,y),(x,y1),(x1,y),(x1,y1))
    referencePoints= "none" #list of pints [[[x,y,r]]] Ask Giorgio, what they mean.
    pointsToTrack = [] #list of numbers [1, 1, 1]
    serial = "NO_SERIAL"
    #from data create ROIS, referencePoints and pointsToTrack CHECK THIS!
    scalex = 800/500 #int(1280/500)
    scaley = 600/375 #int(720/300)
    for key,roi in data.items():
        if key == 'roi':
            for element in roi['rois']:
                p = element['ROI']
                ROIS.append(((int(p[0]*scalex),int(p[1]*scaley)),
                             (int(p[0]*scalex),int(p[3]*scaley)),
                             (int(p[2]*scalex),int(p[3]*scaley)), 
                             (int(p[2]*scalex),int(p[1]*scaley))))
                #referencePoints.append(element['referencePoints'])
                pointsToTrack.append(element['pointsToTrack'])

            print (ROIS)
            print(pointsToTrack)
    data = {'ROIS':ROIS,'referencePoints':referencePoints,
            'pointsToTrack':pointsToTrack,'serial':str(serial)}
    f = open(path.join(basedir,'mask.msk'), 'w')
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
