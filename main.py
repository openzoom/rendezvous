import deepzoom
import flickrapi
import logging
import logging.handlers
import math
import os
import os.path
import settings
import time
import urllib

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

# Iterators
def photo_iter(flickr, user_id):
    page_size = 500
    response = flickr.people_getPublicPhotos(user_id=user_id, per_page=page_size, page=1)
    num_pages = int(response.find('photos').attrib['pages'])
    for page in range(1, num_pages + 1):
        response = flickr.people_getPublicPhotos(user_id=user_id, per_page=page_size, page=page)
        photos = response.getiterator('photo')
        for photo in photos:
            yield photo

def photo_size_iter(flickr, photo_id):
    response = flickr.photos_getSizes(photo_id=photo_id)
    sizes = response.getiterator('size')
    for size in sizes:
        yield size

def tag_iter(flickr, photo_id):
    response = flickr.photos_getInfo(photo_id=photo_id)
    tags = response.getiterator('tag')
    for tag in tags:
        yield tag

def machine_tag_iter(flickr, photo_id):
    for tag in tag_iter(flickr, photo_id):
        try:
            value = int(tag.attrib['machine_tag'])
        except:
            value = 0
        if value == 1:
            yield tag

def machine_tag_namespace_iter(flickr, user_id, namespace):
    for photo in photo_iter(flickr, user_id):
        photo_id = photo.attrib['id']
        for tag in machine_tag_iter(flickr, photo_id):
            tag_namespace = tag.text.partition(':')[0]
            if tag_namespace == namespace:
                yield tag

def largest_photo_url(flickr, photo_id):
    max_size = 0
    photo_url = None
    for size in photo_size_iter(flickr, photo_id):
        w, h = int(size.attrib['width']), int(size.attrib['height'])
        if w * h > max_size:
            max_size = w * h
            photo_url = size.attrib['source']
    return photo_url

# Setup
def connect_flickr(key, secret):
    flickr = flickrapi.FlickrAPI(key, secret)
    (token, frob) = flickr.get_token_part_one(perms='write')
    if not token:
        raw_input('Press ENTER after you authorized this program')
    flickr.get_token_part_two((token, frob))
    return flickr

def _get_or_create_path(path):
    if not os.path.exists(path):
        os.makedirs(path)
    return path

# Constants
ZOOMIT_TAG = u'zoomit:id='
IMAGE_PATH = 'images'
COLLECTION_LEVEL = 7

def main():
    _get_or_create_path(IMAGE_PATH)

    # Connect to Flickr
    flickr = connect_flickr(settings.FLICKR_API_KEY, settings.FLICKR_API_SECRET)

    # Logging
    logger = logging.getLogger('zoomit-flickr')
    logger.setLevel(logging.DEBUG)

    handler = logging.handlers.RotatingFileHandler(settings.LOG_FILE,
                                                   maxBytes=1024*1024, backupCount=100)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    # Process
    user_id = settings.FLICKR_USER_ID

    for photo in photo_iter(flickr, user_id):
        photo_id = photo.attrib['id']
        photo_title = photo.attrib['title']

        print '--------------------------------------------'
        logger.info('Start: %s'%photo_id)

        # Skip photo if we find zoomit tag
        logger.info('Check machine tags: %s'%photo_id)
        zoomit_tag_found = False

        for tag in machine_tag_iter(flickr, photo_id):
            raw_tag = tag.attrib['raw']
            prelude, _, value = raw_tag.partition('=')
            namespace, _, predicate = prelude.partition(':')
            if namespace == 'zoomit' and predicate == 'id':
                zoomit_tag_found = True

        zoomit_id = value

        # Download DZI + tile
        if zoomit_tag_found:
            logger.info('Download: %s'%photo_id)
            attempt = 1
            for attempt in xrange(1, settings.DOWNLOAD_RETRIES + 1):
                try:
                    metadata = {'id': zoomit_id}
                    dzi_url = 'http://cache.zoom.it/content/%(id)s.dzi'%metadata
                    dzi_path = IMAGE_PATH + '/' + zoomit_id + '.dzi'
                    if not os.path.exists(dzi_path):
                        _get_or_create_path(os.path.dirname(dzi_path))
                        urllib.urlretrieve(dzi_url, dzi_path)
                        logger.info('DZI downloaded: %s'%photo_id)
                    else:
                        logger.info('Skipped DZI download: %s'%photo_id)
                    dzi = deepzoom.DeepZoomImageDescriptor()
                    dzi.open(dzi_path)
                    metadata['tile_format'] = dzi.tile_format
                    metadata['level'] = min(dzi.num_levels, COLLECTION_LEVEL)
                    tile_url = 'http://cache.zoom.it/content/%(id)s_files/%(level)s/0_0.%(tile_format)s'%metadata
                    tile_path = IMAGE_PATH + '/' + zoomit_id + '_files/%(level)s/0_0.%(tile_format)s'%metadata
                    if not os.path.exists(tile_path):
                        _get_or_create_path(os.path.dirname(tile_path))
                        urllib.urlretrieve(tile_url, tile_path)
                        logger.info('Tile downloaded: %s'%photo_id)
                    else:
                        logger.info('Skipped tile download: %s'%photo_id)
                    break
                except:
                    logger.warning('Download attempt: %s (%s)'%(attempt, photo_id))
                    time.sleep(2**(attempt - 1)) # Wait for 1, 2, 4, 16, etc. seconds
                    continue
            logger.info('Skipped: %s'%photo_id)
            continue

        # Find largest photo URL
        photo_url = largest_photo_url(flickr, photo_id)
        msg = 'Flickr photo URL: %s'%photo_id
        if photo_url is None:
            logger.warning(msg)
            continue
        logger.info(msg)

        # Set machine tags
        content_info_response = urllib.urlopen('http://api.zoom.it/v1/content/?' + urllib.urlencode({'url':photo_url}))
        content_info = _parse_json(content_info_response.read())
        logger.info(str(content_info))
        zoomit_id = content_info['id']

        attempt = 1
        for attempt in xrange(1, settings.MACHINE_TAG_RETRIES + 1):
            try:
                tag = ZOOMIT_TAG + zoomit_id
                flickr.photos_addTags(photo_id=photo_id, tags=tag)
                logger.info('Machine tag: %s'%photo_id)
                break
            except:
                logger.warning('Machine tag attempt: %s (%s)'%(attempt, photo_id))
                time.sleep(2**(attempt - 1)) # Wait for 1, 2, 4, 16, etc. seconds
                continue

        if attempt == settings.MACHINE_TAG_RETRIES:
            logger.error('Machine tag: %s'%photo_id)

    print logger.info('Done.')


if __name__ == '__main__':
    main()
