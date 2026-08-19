import bottle
import glob
import json
import logging
import os
import re
import datetime
import optparse

app = bottle.Bottle()

# Defaults; overridden from the command line in __main__.
LINKS_FILE = "./contents/links.json"
NEWS_FILE = "./contents/news.txt"
# Directory of published SD images. Each <image>.img.zip has a sidecar
# <image>.img.zip.json manifest written by accessories/publish-image.sh.
IMAGES_DIR = "./images"

# path -> (mtime, size, parsed contents). Files are re-read only when they
# change on disk, so editing links.json no longer needs a container restart.
_cache = {}


def _read_cached(path, parser, default):
    """Parse a file, reusing the previous result while it is unchanged.

    Args:
        path (str): File to read.
        parser (callable): Takes an open file object, returns the parsed value.
        default: Returned if the file is missing or unparseable.

    Returns:
        The parsed contents, or default.
    """
    try:
        st = os.stat(path)
        stamp = (st.st_mtime, st.st_size)
    except OSError:
        _cache.pop(path, None)
        return default

    cached = _cache.get(path)
    if cached and cached[0] == stamp:
        return cached[1]

    try:
        with open(path, "r") as f:
            value = parser(f)
    except Exception as e:
        logging.warning("Could not parse %s: %s", path, e)
        return default

    _cache[path] = (stamp, value)
    return value


def _parse_news(fh):
    news = []
    for line in fh.readlines():
        if not line.startswith("#") and ";" in line:
            news.append({"content": line.split(";")[1], "date": line.split(";")[0]})
    return news


def load_links():
    """Return the hand-maintained links.json contents."""
    return _read_cached(LINKS_FILE, json.load, {})


def load_news():
    """Return the news entries as a list of {content, date} dicts."""
    return _read_cached(NEWS_FILE, _parse_news, [])


def models_from_filename(filename):
    """Extract the Pi models an image supports from its name.

    '20260819_ethoscope000_pi3_pi4.img.zip' -> ['pi3', 'pi4']

    Args:
        filename (str): Image file name.

    Returns:
        list[str]: Lowercased model tokens, possibly empty.
    """
    return [m.lower() for m in re.findall(r"_(pi\d+)", filename or "", re.I)]


def published_images():
    """Return the images published to IMAGES_DIR, newest first.

    Reads the sidecar manifests written by accessories/publish-image.sh. An
    image with no manifest is ignored: the manifest is uploaded only after the
    archive's checksum has been verified, so a half-uploaded image is never
    advertised.

    Returns:
        list[dict]: Manifest dicts, newest first.
    """
    images = []
    for path in glob.glob(os.path.join(IMAGES_DIR, "*.json")):
        entry = _read_cached(path, json.load, None)
        if isinstance(entry, dict) and entry.get("filename") and entry.get("url"):
            images.append(entry)

    images.sort(key=lambda i: (i.get("published", ""), i.get("filename", "")), reverse=True)
    return images


def all_images():
    """Published images first, then any links.json entries not superseded."""
    images = published_images()
    seen = {i.get("filename") for i in images}
    for entry in load_links().get("images", []):
        if entry.get("filename") not in seen:
            images.append(entry)
    return images


@app.hook('after_request')
def enable_cors():
    origin = bottle.request.headers.get('Origin')  # Dynamically get the Origin header
    if origin:
        bottle.response.headers['Access-Control-Allow-Origin'] = origin
    else:
        bottle.response.headers['Access-Control-Allow-Origin'] = '*'

    # Other CORS headers
    bottle.response.headers['Access-Control-Allow-Methods'] = 'PUT, GET, POST, DELETE, OPTIONS'
    bottle.response.headers['Access-Control-Allow-Headers'] = 'Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token'
    bottle.response.headers['Access-Control-Allow-Credentials'] = 'true'  # Required for credentials


@app.get('/')
def index():
    links = load_links()
    return bottle.template('index_template',
                           images=all_images(),
                           gcodes=links.get('gcodes', []),
                           onshape=links.get('onshape', []),
                           gcodes_zip=links.get('gcodes_zip', {}),
                           news=load_news())


@app.get('/latest_sd_image/<pi>')
def forward_to_sd_image(pi):
    """Redirect to the newest published image supporting the given Pi model.

    Args:
        pi (str): Model, e.g. 'pi4', 'PI4' or '4'.

    Returns:
        A 302 redirect to the image, or 404 if no image supports that model.
    """
    model = pi.strip().lower()
    if model.isdigit():
        model = "pi" + model

    for image in all_images():
        models = image.get("models") or models_from_filename(image.get("filename", ""))
        if model in [str(m).lower() for m in models]:
            return bottle.redirect(image["url"], code=302)

    raise bottle.HTTPError(404, "No published SD image for '%s'" % model)


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

    links = load_links()
    bottle.response.content_type = 'application/json'
    return json.dumps({"images": all_images(),
                       "gcodes": links.get('gcodes', []),
                       "onshape": links.get('onshape', []),
                       'gcodes_zip': links.get('gcodes_zip', {}),
                       'date': "",
                       'version': ""})


@app.get('/news')
def announcements():
    bottle.response.content_type = 'application/json'
    return json.dumps({"news": load_news()})


if __name__ == '__main__':

    logging.getLogger().setLevel(logging.INFO)
    parser = optparse.OptionParser()
    parser.add_option("-p", "--port", dest="port", default=8080, help="port")
    parser.add_option("-l", "--log", dest="logfile", default="/opt/ethoscope_resources/", help="Path to the log file")


    parser.add_option("--key", dest="key", default="", help="Full path to the key.pem file")
    parser.add_option("--cert", dest="cert", default="", help="Full path to the cert.pem file")
    parser.add_option("--static", dest="static_path", default="/opt/ethoscope_resources", help="Path to the root of the static folder")
    parser.add_option("--contents", dest="contents_path", default="./contents", help="Path to the folder holding links.json and news.txt")
    parser.add_option("--images", dest="images_path", default="/opt/ethoscope_resources/images", help="Path to the folder holding published SD images and their .json manifests")
    parser.add_option("-D", "--debug", dest="debug", default=False, help="Set DEBUG mode ON", action="store_true")


    (options, args) = parser.parse_args()

    option_dict = vars(options)
    KEY = option_dict["key"]
    CERT = option_dict["cert"]
    STATIC_DIR = os.path.join(option_dict["static_path"], "./static")
    LOGFILE = os.path.join ( option_dict["logfile"], "ethoscope_pa_server.log")

    LINKS_FILE = os.path.join(option_dict["contents_path"], "links.json")
    NEWS_FILE = os.path.join(option_dict["contents_path"], "news.txt")
    IMAGES_DIR = option_dict["images_path"]

    PORT = option_dict["port"]
    DEBUG = option_dict["debug"]

    if DEBUG:
        logging.basicConfig(filename=LOGFILE, level=logging.INFO)

    if not os.path.exists(LINKS_FILE):
        logging.warning("File not found: %s - only published images will be listed", LINKS_FILE)
    if not os.path.isdir(IMAGES_DIR):
        logging.warning("Images directory not found: %s - only links.json entries will be listed", IMAGES_DIR)

    if KEY and CERT:
        bottle.run(app, host='0.0.0.0', port=PORT, debug=DEBUG, server='gunicorn', reloader=1, keyfile='key.pem', certfile='cert.pem')
    else:
        bottle.run(app, host='0.0.0.0', port=PORT, debug=DEBUG)
