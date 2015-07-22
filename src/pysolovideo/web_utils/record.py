import picamera

class RecordVideo(Thread):

    def __init__(self, resolution=(640,480), framerate=24, name):
        self.camera = picamera.Picamera()
        self.camera.resolution = resolution
        self.camera.framerate = framerate
        self.name =

    def start(self):
        try:
            self.camera.start_recording(self.name+'.h264')
        except exception as e:
            print (e)

    def stop(self):
        self.camera.stop_recording()

