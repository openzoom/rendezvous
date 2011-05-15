#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
#   OpenZoom Zoom.it Flickr Rendezvous
#
#   Copyright (c) 2010, Daniel Gasienica <daniel@gasienica.ch>
#
#   OpenZoom is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   OpenZoom is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with OpenZoom. If not, see <http://www.gnu.org/licenses/>.
#

import settings
import flickrapi
import logging
import logging.handlers
import math
import os
import os.path
import shutil
import time
import urllib

from zoomit import ZoomItService

# Flickr iterators
def photo_iter(flickr, user_id):
    response = flickr.people_getInfo(user_id=user_id)
    photo_count = int(response.find("person").find("photos").find("count").text)
    page_size = 500
    num_pages = int(math.ceil(float(photo_count) / page_size))
    for page in xrange(1, num_pages + 1):
        response = flickr.people_getPublicPhotos(user_id=user_id, per_page=page_size, page=page)
        photos = response.getiterator("photo")
        for photo in photos:
            yield photo

def photo_size_iter(flickr, photo_id):
    response = flickr.photos_getSizes(photo_id=photo_id)
    sizes = response.getiterator("size")
    for size in sizes:
        yield size

def tag_iter(flickr, photo_id):
    response = flickr.photos_getInfo(photo_id=photo_id)
    tags = response.getiterator("tag")
    for tag in tags:
        yield tag

def machine_tag_iter(flickr, photo_id):
    for tag in tag_iter(flickr, photo_id):
        if tag.attrib["machine_tag"] != "" and int(tag.attrib["machine_tag"]) == 1:
            yield tag

def get_largest_photo_url(flickr, photo_id):
    max_size = 0
    photo_url = None
    for size in photo_size_iter(flickr, photo_id):
        w, h = int(size.attrib["width"]), int(size.attrib["height"])
        if w * h > max_size:
            max_size = w * h
            photo_url = size.attrib["source"]
    return photo_url

# Setup
def reset_dir(path):
    if os.path.exists(path):
        shutil.rmtree(path)
    os.mkdir(path)

def connect_flickr(key, secret):
    flickr = flickrapi.FlickrAPI(key, secret)
    (token, frob) = flickr.get_token_part_one(perms="write")
    if not token:
        raw_input("Press ENTER after you authorized this program")
    flickr.get_token_part_two((token, frob))
    return flickr


LOG_FILENAME = "zoomit-flickr-rendezvous.log"
PRODUCTION = False

ZOOMIT_ID_TAG = u"zoomit:id=%s"

def main():
    # Logging
    logger = logging.getLogger("zoomit-flickr-rendezvous")
    logger.setLevel(logging.DEBUG)

    handler = logging.handlers.RotatingFileHandler(settings.LOG_FILE,
                                                   maxBytes=1024*1024, backupCount=100)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Iterate through all Flickr photos
    zoomit = ZoomItService()
    flickr = connect_flickr(settings.FLICKR_API_KEY, settings.FLICKR_API_SECRET)
    user_id = settings.FLICKR_USER

    for photo in photo_iter(flickr, user_id):
        photo_id = photo.attrib["id"]
        photo_title = photo.attrib["title"]

        print "--------------------------------------------"

        # Skip photo if we found openzoom tags
        logger.info("Checking machine tags >>> %s"%photo_id)
        obsolete_tag_ids = []
        found_zoom_it_id = False
        zoomit_id = None

        for tag in machine_tag_iter(flickr, photo_id):
            tag_id = tag.attrib["id"]
            raw_tag = tag.attrib["raw"]
            namespace, _, predicate = raw_tag.partition("=")[0].partition(":")
            value = raw_tag.partition("=")[2]
            if namespace in ["seadragon", "openzoom"] and predicate in ["source", "base16source"]:
                obsolete_tag_ids.append(tag_id)
            if namespace == "seadragon" and predicate == "id":
                zoomit_id = value
                obsolete_tag_ids.append(tag_id)
            if namespace == "zoomit" and predicate == "id":
                found_zoom_it_id = True

        # Remove obsolete tags
        for obsolete_tag_id in obsolete_tag_ids:
            attempt = 1
            for attempt in xrange(1, settings.MACHINE_TAG_RETRIES + 1):
                try:
                    flickr.photos_removeTag(tag_id=obsolete_tag_id)
                    logger.info("Removing machine tag (%s) >>> %s"%(obsolete_tag_id, photo_id))
                    break
                except:
                    timeout = 2**attempt # Wait for 2, 4, 8, 16 seconds...
                    logger.warning("Removing machine tag attempt %s (%d) >>> %s"%(attempt, timeout, photo_id))
                    time.sleep(timeout)
                    continue
            if attempt == settings.MACHINE_TAG_RETRIES:
                logger.error("Failed to remove machine tags >>> %s"%photo_id)

        if found_zoom_it_id:
            logger.info("Skipping >>> %s"%photo_id)
            continue

        if zoomit_id is None:
            # Get largest Flickr photo URL
            photo_url = get_largest_photo_url(flickr, photo_id)
            msg = "Found largest Flickr photo URL >>> %s (%s)"%(photo_id, photo_url)
            if photo_url is None:
                logger.warning(msg)
                continue
            logger.info(msg)

            logger.info("Processing image with Zoom.it API >>> %s"%photo_id)
            content = zoomit.get_content_by_url(photo_url)

        try:
            zoomit_id = content['id']
        except:
            logger.warning("Failed to get Zoom.it ID")
            continue

        # Setting machine tags
        attempt = 1
        for attempt in xrange(1, settings.MACHINE_TAG_RETRIES + 1):
            try:
                zoomit_tag = ZOOMIT_ID_TAG%zoomit_id
                flickr.photos_addTags(photo_id=photo_id, tags=zoomit_tag)
                logger.info("Setting machine tag >>> %s"%photo_id)
                found_zoom_it_id = True
                break
            except:
                timeout = 2**attempt # Wait for 2, 4, 8, 16 seconds...
                logger.warning("Setting machine tag attempt %s (%d) >>> %s"%(attempt, timeout, photo_id))
                time.sleep(timeout)
                continue
        if attempt == settings.MACHINE_TAG_RETRIES:
            logger.error("Failed to set machine tag >>> %s"%photo_id)

    print logger.info("Done.")

# Main
if __name__ == "__main__":
    main()
