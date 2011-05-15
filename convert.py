#!/usr/bin/env python

import deepzoom
import logging
import logging.handlers
import time


# JSON
try:
    import json
    _parse_json = lambda s: json.loads(s)
except ImportError:
    try:
        import simplejson
        _parse_json = lambda s: simplejson.loads(s)
    except ImportError:
        # For Google AppEngine
        from django.utils import simplejson
        _parse_json = lambda s: simplejson.loads(s)

def main():
    t = time.time()

    # Logging
    logger = logging.getLogger('zoomit-flickr-convert-%d'%t)
    logger.setLevel(logging.DEBUG)
    handler = logging.handlers.RotatingFileHandler('zoomit-flickr-convert-%d'%t,
                                                   maxBytes=1024*1024, backupCount=100)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Conversion
    logger.info('Begin %d: ' % t + str(t))

    f = open('photos.json')
    photos = json.load(f)
    images = [photo['dzi'] for photo in photos]
    images.reverse() # reverse chronological

    collection = deepzoom.DeepZoomCollectionDescriptor('collection-%d.xml' % t)
    for image in images:
        try:
            collection.append(image)
            collection.save()
        except:
            logger.error('Failed: %s'%image)
            continue

    end = time.time()
    logger.info('End %d: ' % t + str(end))
    logger.info('Duration %d: ' % t + str(end - t))

if __name__ == '__main__':
    main()
