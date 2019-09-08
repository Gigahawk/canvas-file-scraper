import os
import requests
import logging
import json
from tempfile import TemporaryFile
import urllib
from bs4 import BeautifulSoup
from markdownify import markdownify as md


class CanvasScraper:
    def __init__(
            self, base_url, api_key, path, overwrite,
            videos, markdown, logger=None):
        self.api_key = api_key
        self.base_url = self._create_base_url(base_url)
        self.headers = {'Authorization': f'Bearer {self.api_key}'}
        self._path = path
        self.overwrite = overwrite
        self.videos = videos
        self.markdown = markdown
        self._logger = logger

        if not self._logger:
            self._logger = logging

        self._loggers = [self._logger]
        self._names = []
        self._ids = []

    def scrape(self):
        courses = self.get_all_objects(self._courses_url())
        for c in courses:
            self.recurse_course(c)

    def recurse_course(self, course):
        try:
            self.push(course, "course")
        except KeyError:
            return
        fp_url = self._course_frontpage_url(self.id)
        fp_path = os.path.join(self.path, "front_page.html")
        fp_md_path = os.path.join(self.path, "front_page.md")
        if self.markdown and self._dl_page(fp_url, fp_path):
            self._markdownify(fp_path, fp_md_path)

        modules = self.get_all_objects(self._modules_url(self.id))
        for m in modules:
            self.recurse_module(m)
        self.pop()

    def recurse_module(self, module):
        self.push(module, "module")
        items = self.get_all_objects(module["items_url"])
        for i in items:
            self.recurse_item(i)
        self.pop()

    def recurse_item(self, item):
        self.push(item, "item", name_key="title")
        if item["type"] == "File":
            self.handle_file(item)
        elif item["type"] == "Page":
            self.handle_page(item)
        elif item["type"] == "Assignment":
            self.handle_assignment(item)
        else:
            self.logger.warning(f"Unsupported type {item['type']}")
        self.pop()

    def handle_file(self, item):
        file_info_url = item["url"]
        r = self._get(file_info_url)
        file_info = r.json()

        file_name = urllib.parse.unquote(file_info["filename"])
        file_url = file_info["url"]
        file_path = os.path.join(self.path, file_name)
        self._dl(file_url, file_path)

    def handle_page(self, item):
        page_url = item["url"]

        page_path = os.path.join(self.path, "page.html")
        page_md_path = os.path.join(self.path, "page.md")

        if self.markdown and self._dl_page(page_url, page_path):
            self._markdownify(page_path, page_md_path)
            self._dl_page_data(page_path)

    def handle_assignment(self, item):
        pass

    def push(self, obj, type, name_key="name"):
        name = obj[name_key]
        id = obj["id"]

        self._push_logger(f"{type}_{id}")
        self._push_name(name)
        self._push_id(id)

        self.logger.info(name)

    def pop(self):
        self._pop_logger()
        self._pop_name()
        self._pop_id()

    def get_all_objects(self, url):
        self.logger.debug(f"Grabbing all pages for {url}")
        objects = []
        page = 1
        while True:
            r = self._get(url, params={"page": page})
            if not r.json():
                break
            objects.extend(r.json())
            self.logger.debug(f"Grabbed page {page}")
            page += 1
        return objects

    @property
    def logger(self):
        return self._loggers[-1]

    @property
    def path(self):
        return os.path.join(self._path, *self._names)

    @property
    def name(self):
        return self._names[-1]

    @property
    def id(self):
        return self._ids[-1]

    @staticmethod
    def _create_base_url(base_url):
        if "https" not in base_url:
            base_url = f"https://{base_url}"
        if "api/v1" not in base_url:
            base_url = os.path.join(base_url, "api/v1")
        return base_url

    def _courses_url(self):
        return f"{self.base_url}/courses"

    def _course_url(self, course_id):
        return f"{self._courses_url()}/{course_id}"

    def _course_frontpage_url(self, course_id):
        return f"{self._course_url(course_id)}/front_page"

    def _modules_url(self, course_id):
        return f"{self._course_url(course_id)}/modules"

    def _kaltura_manifest_url(self, base_url, entry_id, flavor_id):
        base_url = base_url[:base_url.index("embedIframeJs")]
        return os.path.join(
            base_url,
            "playManifest/entryId",
            str(entry_id),
            "flavorIds",
            str(flavor_id),
            "format/applehttp/protocol/https/a.m3u8")

    def _get(self, url, params=None):
        return requests.get(url, params=params, headers=self.headers)

    def _mkd(self, path):
        return os.makedirs(path, exist_ok=True)

    def _dl(self, url, path):
        if self._should_write(path):
            r = self._get(url)
            with open(path, "wb") as f:
                f.write(r.content)
                self.logger.info(f"{path} downloaded")
                return True

    def _dl_page(self, url, path, key="body"):
        r = self._get(url)
        page = r.json()
        if "body" in page.keys() and self._should_write(path):
            with open(path, "w") as f:
                f.writelines(page["body"])
                self.logger.info(f"{path} downloaded")
                return True

    def _dl_page_data(self, src_path):
        with open(src_path, "r") as f:
            src = f.read()

        soup = BeautifulSoup(src, "html.parser")
        links = soup.find_all('a', **{'data-api-returntype': 'File'})
        for link in links:
            dl_path = os.path.join(self.path, "files", link["title"])
            self._dl(link["href"], dl_path)

        if self.videos:
            # Download Kaltura videos
            videos = soup.find_all('iframe', **{'id': 'kaltura_player'})
            for idx, video in enumerate(videos):
                video_path = os.path.join(self.path, "videos", f"{idx}.mp4")
                self._dl_video(video["src"], video_path)

    def _dl_video(self, base_url, path):
        if not self._should_write(path):
            return
        # Get data from Kaltura iframe
        lines = requests.get(base_url).text.splitlines()
        iframe_data = next(
            (l for l in lines if "kalturaIframePackageData" in l), None)
        if not iframe_data:
            self.logger.warning(f"iframe data not found for {base_url}")
            return
        # Ignore js syntax, pull json text out of line
        iframe_data = iframe_data[iframe_data.index("{"):-1]
        iframe_data = json.loads(iframe_data)
        try:
            flavor_assets = (iframe_data["entryResult"]
                                        ["contextData"]
                                        ["flavorAssets"])
        except KeyError:
            self.logger.warning(f"flavorAssets not found in {base_url}")
            return

        flavor_asset = next(
            (f for f in flavor_assets if f.get("flavorParamsId") == 5),
            None)
        if not flavor_asset:
            self.logger.warning(
                f"Could not find correct flavorAsset for {base_url}")
            return
        try:
            entry_id = flavor_asset["entryId"]
            flavor_id = flavor_asset["id"]
        except KeyError:
            self.logger.warning(
                f"Could not find keys inside flavorAsset for {base_url}")
            return
        manifest_url = self._kaltura_manifest_url(
            base_url, entry_id, flavor_id)
        lines = requests.get(manifest_url).text.splitlines()
        index_url = next((l for l in lines if "index" in l), None)
        if not index_url:
            self.logger.warning(
                f"Could not find index urlfor {base_url}")
            return
        index = filter(
            lambda l: not l.startswith("#"),
            requests.get(index_url).text.splitlines())
        streaming_url = index_url.replace("index.m3u8", "")
        with TemporaryFile() as tf:
            for i in index:
                self.logger.info(f"Downloading video segment {i}")
                segment_url = os.path.join(streaming_url, i)
                tf.write(requests.get(segment_url).content)
            with open(path, "wb") as f:
                tf.seek(0)
                f.write(tf.read())
            self.logger.info(f"Downloaded {path} successfully")

    def _markdownify(self, src_path, dest_path):
        if self._should_write(dest_path):
            self.logger.info(f"Converting {src_path} to markdown")
            with open(src_path, "r") as f:
                src = f.read()
            with open(dest_path, "w") as f:
                f.writelines(md(src))

    def _should_write(self, path):
        if os.path.isfile(path) and self.overwrite is "no":
            self.logger.debug(f"Skipping file {path}")
            return False
        elif (self.overwrite is "ask" and
                input(f"{path} already exists, overwrite? (y/n)") != "y"):
            return False
        # Ensure folder exists before writing
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return True

    def _push_logger(self, name):
        self._loggers.append(self.logger.getChild(name))

    def _pop_logger(self):
        self._loggers.pop(-1)

    def _push_name(self, name):
        self._names.append(name)
        self._mkd(self.path)

    def _pop_name(self):
        self._names.pop(-1)

    def _push_id(self, id):
        self._ids.append(id)

    def _pop_id(self):
        self._ids.pop(-1)




