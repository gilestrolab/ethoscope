import bottle
import json
import logging
import os
import datetime
import optparse

FILESVERSION = "1.6"
FILESDATE = "2020-02-15"

app = bottle.Bottle()

links_file = "./contents/links.json"
assert os.path.exists(links_file), f"File not found: {links_file}"

news_file = "./contents/news.txt"
assert os.path.exists(news_file), f"File not found: {news_file}"

# Open and read the JSON file containing all the links
with open(links_file, 'r') as file:
    links = json.load(file)

sd_image = links['sd_image']
gcodes = links['gcodes']
onshape = links['onshape']
gcodes_zip = links['gcodes_zip']           

# Open and read the txt file with news
news = []
with open(news_file, "r") as nf:
    for line in nf.readlines():
        if not line.startswith("#") and ";" in line:
            news.append ( {"content" : line.split(";")[1], "date": line.split(";")[0]} )

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


@app.get('/')
def index():
    return bottle.template('index_template', sd_image=sd_image, gcodes=gcodes, onshape=onshape, gcodes_zip=gcodes_zip, news=news)

@app.get('/latest_sd_image')
def forward_to_sd_image():
    return bottle.redirect(sd_image['url'], code=302)


@app.get('/resources')
def resources():
    client = bottle.request.environ.get('HTTP_X_FORWARDED_FOR') or bottle.request.environ.get('REMOTE_ADDR')

    try:
        with os.popen("host %s" % client) as p:
            output = p.read()
            if "pointer" in output:
                resolve = output.split("pointer ")[1].strip()
            else:
                resolve = "DNS resolution failed"
    except Exception as e:
        resolve = f"Error during DNS resolution: {str(e)}"

    logging.info("%s - Receiving request from %s - %s" % (datetime.datetime.now(), client, resolve))
    
    bottle.response.content_type = 'application/json'
    return json.dumps({"sd_image": sd_image, "gcodes": gcodes, "onshape": onshape, 'gcodes_zip': gcodes_zip, 'date': FILESDATE, 'version': FILESVERSION})


@app.get('/news')
def announcements():
    bottle.response.content_type = 'application/json'
    return json.dumps( {"news" : news} )


if __name__ == '__main__':

    logging.getLogger().setLevel(logging.INFO)
    parser = optparse.OptionParser()
    parser.add_option("-p", "--port", dest="port", default=8080, help="port")
    parser.add_option("-l", "--log", dest="logfile", default="/opt/ethoscope_resources/", help="Path to the log file")


    parser.add_option("--key", dest="key", default="", help="Full path to the key.pem file")
    parser.add_option("--cert", dest="cert", default="", help="Full path to the cert.pem file")
    parser.add_option("--static", dest="static_path", default="/opt/ethoscope_resources", help="Path to the root of the static folder")
    parser.add_option("-D", "--debug", dest="debug", default=False, help="Set DEBUG mode ON", action="store_true")


    (options, args) = parser.parse_args()

    option_dict = vars(options)
    KEY = option_dict["key"]
    CERT = option_dict["cert"]
    STATIC_DIR = os.path.join(option_dict["static_path"], "./static")
    LOGFILE = os.path.join ( option_dict["logfile"], "ethoscope_pa_server.log")

    PORT = option_dict["port"]
    DEBUG = option_dict["debug"]

    if DEBUG:
        logging.basicConfig(filename=LOGFILE, level=logging.INFO)    

    if KEY and CERT:
        bottle.run(app, host='0.0.0.0', port=PORT, debug=DEBUG, server='gunicorn', reloader=1, keyfile='key.pem', certfile='cert.pem')
    else:
        bottle.run(app, host='0.0.0.0', port=PORT, debug=DEBUG)
    
