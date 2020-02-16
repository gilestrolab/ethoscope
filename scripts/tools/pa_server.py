import bottle
import json
import logging
import os

FILESVERSION = "1.6"
FILESDATE = "2020-02-15"

app = bottle.Bottle()
STATIC_DIR = "../static"
PORT = 8001
 
sd_image = {'filename' : '20200216_ethoscope_000.img.zip',
            'url' : 'https://imperialcollegelondon.box.com/shared/static/ku704ys0p96n4oijwtk4sspsp0mmywf9.zip',
            'date' : '16 Feb 2020',
            'md5sum' : 'f6160a80d3acc63e1d5c91f92710e00a'
            }
                
gcodes = [
          {'filename' : '1_etho_1.6_LIGHT_BOX.2x'         , 'url' : 'https://www.dropbox.com/s/u4598hoxt2ueg5v/1_etho_1.6_LIGHT_BOX.2x.gcode?dl=0', 'prints': 'Light box only', 'material' : 'PLA White'},
          {'filename' :  '2_etho_v1.6_CASE_AND_CAMERA.2x' , 'url' : 'https://www.dropbox.com/s/ymri52uw8wc3jwc/2_etho_v1.6_CASE_AND_CAMERA.2x.gcode?dl=0', 'prints': 'Upper case and camera case', 'material' : 'PLA Gray'},
          {'filename' : '2.1_etho_v1.6_CASE_ONLY.1x'      , 'url' : 'https://www.dropbox.com/s/zexducfe7789yh8/2.1_etho_v1.6_CASE_ONLY.1x.gcode?dl=0', 'prints': 'Upper case only', 'material' : 'PLA Gray'},
          {'filename' : '2.2_etho_v1.6_CASE_ONLY.2x'      , 'url' : 'https://www.dropbox.com/s/6ui47b2mw2t2p8x/2.2_etho_v1.6_CASE_ONLY.2x.gcode?dl=0', 'prints': 'Upper case only', 'material' : 'PLA Gray'},
          {'filename' : '3_etho_v1.6_LID_AND_STRIP.2x'    , 'url' : 'https://www.dropbox.com/s/a5p543hqup6li22/3_etho_v1.6_LID_AND_STRIP.2x.gcode?dl=0', 'prints': 'Case lid and camera strip', 'material' : 'PLA White'},
          {'filename' : '3.1_etho_v1.6_LID_ONLY.2x'       , 'url' : 'https://www.dropbox.com/s/97inb00c9vj2k0d/3.1_etho_v1.6_LID_ONLY.2x.gcode?dl=0', 'prints': 'Lid only', 'material' : 'PLA White'},
          {'filename' : '3.2_etho_v1.6_light_strip.7x'    , 'url' : 'https://www.dropbox.com/s/b3tmhg097f23she/3.2_etho_v1.6_light_strip.7x.gcode?dl=0', 'prints': 'Light strip only', 'material' : 'PLA Clear or White'}
              ]
                
onshape = [
            {'name': 'Upper case', 'url' : 'https://cad.onshape.com/documents/1166d5bbca939d2544d087f1/w/d50990341370df72c14403d2/e/d228e2116a5933cf39312517'},
            {'name': 'Light box'  , 'url' : 'https://cad.onshape.com/documents/1166d5bbca939d2544d087f1/w/d50990341370df72c14403d2/e/d5e7d416ecf9f99624a6734c'},
            {'name': 'Walls'      , 'url' : 'https://cad.onshape.com/documents/1166d5bbca939d2544d087f1/w/d50990341370df72c14403d2/e/72167f0b1de0d32cd5d66968'},
            {'name': 'Stabiliser' , 'url' : 'https://cad.onshape.com/documents/1166d5bbca939d2544d087f1/w/d50990341370df72c14403d2/e/51c11b1cb511015be15336e4'}
           ]

gcodes_zip = {'filename' : 'ethoscope_gcodes_v1.6.zip', 'url' : 'https://www.dropbox.com/s/i5vb7bkbfsiff9o/ethoscope_gcodes_v1.6.zip?dl=0', 'date': '2020-02-15'}              


news = [
        {"content" : "Latest news here", "date" : "2020-02-15"}
       ]


@app.hook('after_request')
def enable_cors():
    """
    You need to add some headers to each request.
    Don't use the wildcard '*' for Access-Control-Allow-Origin in production.
    """
    #bottle.response.headers['Access-Control-Allow-Origin'] = 'http://localhost:8888'
    bottle.response.headers['Access-Control-Allow-Origin'] = '*' # Allowing CORS in development
    bottle.response.headers['Access-Control-Allow-Methods'] = 'PUT, GET, POST, DELETE, OPTIONS'
    bottle.response.headers['Access-Control-Allow-Headers'] = 'Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token'


@app.get('/latest_sd_image')
def forward_to_sd_image():
    return bottle.redirect(sd_image['url'], code=302)


@app.get('/resources')
def resources():
    client = bottle.request.environ.get('HTTP_X_FORWARDED_FOR') or bottle.request.environ.get('REMOTE_ADDR')
    with os.popen("host %s" % client) as p:
        resolve = p.read().split("pointer ")[1].strip()

    logging.info("Receiving request from %s - %s" % (client, resolve))

    bottle.response.content_type = 'application/json'
    return json.dumps( {"sd_image" : sd_image, "gcodes" : gcodes, "onshape" : onshape, 'gcodes_zip' : gcodes_zip, 'date' : FILESDATE, 'version' : FILESVERSION} )

@app.get('/news')
def announcements():
    bottle.response.content_type = 'application/json'
    return json.dumps( {"news" : news} )


if __name__ == '__main__':

    logging.basicConfig(filename='ethoscope_pa_server.log',level=logging.INFO)    
    bottle.run(app, host='0.0.0.0', port=PORT, debug=True)
    
