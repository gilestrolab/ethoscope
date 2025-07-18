__author__ = 'quentin'
#import futures
import concurrent.futures as futures
import concurrent
import urllib.request, urllib.error, urllib.parse
import time
import logging
import json

start = time.time()



def scan_one_device(ip, timeout=2.5, port=9000, page="id"):
    """


    :param url: the url to parse
    :param timeout: the timeout of the url request
    :param port: the port to request
    :return: The message, parsed as dictionary. the "ip" field is also added to the result.
    If the url could not be reached/parsed, (None,None) is returned
    """


    url="%s:%i/%s" % (ip, port, page)
    logging.info("Scanning: %s" % url)
    try:
        req = urllib.request.Request(url)
        f = urllib.request.urlopen(req, timeout=timeout)
        message = f.read()

        if not message:
            logging.error("URL error whist scanning url: %s. No message back." % url )
            raise urllib.error.URLError("No message back")
        try:
            resp = json.loads(message)
            return (resp['id'],ip)
        except ValueError:
            logging.error("Could not parse response from %s as JSON object" % url )

    except urllib.error.URLError:
        logging.error("URL error whist scanning url: %s. Server down?" % url )

    except Exception as e:
        logging.error("Unexpected error whilst scanning url: %s" % url )
        raise e

    return None, ip




subnet = "192.169.123" #"129.31.135"
subnet = "129.31.135"
ip_range = (2,253)
to_scan = "%s.%i-%i" % (subnet, ip_range[0], ip_range[1])
#scanned = nm.scan(to_scan, arguments="-sn")

scanned = [ "%s.%i" % (subnet, i) for i in range(1,255) ]
urls= ["http://%s" % str(s) for s in scanned]



# We can use a with statement to ensure threads are cleaned up promptly
with futures.ThreadPoolExecutor(max_workers=len(scanned)) as executor:
    # Start the load operations and mark each future with its URL
    future_to_url = {executor.submit(scan_one_device, url): url for url in urls}
    for future in concurrent.futures.as_completed(future_to_url):
        url = future_to_url[future]
        try:
            data = future.result()
            if data[0] is None:
                continue
            print((url,data))
        except Exception as exc:
            print('%r generated an exception: %s' % (url, exc))


print("Elapsed Time: %ss" % (time.time() - start))


