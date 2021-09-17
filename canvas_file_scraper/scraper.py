import types
import re
import os
import requests
from requests.exceptions import MissingSchema
import logging
import json
from tempfile import TemporaryFile
from pathvalidate import sanitize_filename
import urllib
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from canvasapi import Canvas
from canvasapi.exceptions import Unauthorized, ResourceDoesNotExist

from canvasapi.canvas_object import CanvasObject
from canvasapi.file import File
from canvasapi.paginated_list import PaginatedList
from canvasapi.util import combine_kwargs


class MediaObject(CanvasObject):
    pass


def get_media_objects(self, *args, **kwargs):
    return PaginatedList(
        MediaObject,
        self._requester,
        "GET",
        "courses/{}/media_objects".format(self.id),
        {"course_id": self.id},
        _kwargs=combine_kwargs(**kwargs),
    )



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
        self._canvas = Canvas(self.base_url, self.api_key)
        self.user = self._canvas.get_current_user()
        self.visited_page_links = []

        if not self._logger:
            self._logger = logging

        self._loggers = [self._logger]
        self._names = []
        self._ids = []

    def scrape(self):
        courses = self.user.get_courses()
        for c in courses:
            try:
                print(c)
            except AttributeError:
                print("Null course")
            #import pdb
            #pdb.set_trace()
            self.recurse_course(c)

    def recurse_course(self, course):
        try:
            try:
                self.push(course, "course")
            except KeyError:
                return

            try:
                external_tools = course.get_external_tools()
                external_tools = list(external_tools)
                self.logger.info(str(course.name))
                self.logger.info(external_tools)
                if external_tools:
                    import pdb
                    pdb.set_trace()
            except (Unauthorized, ResourceDoesNotExist) as e:
                self.logger.warning(e)
                self.logger.warning(f"External tools not accesible")

            self.push_raw(f"assignments_{course.id}", "assignments", 0)
            try:
                assignments = course.get_assignments()
                for a in assignments:
                    self.push_raw(f"assignment_{a.name}", "assignment", 0)
                    try:
                        self.handle_assignment(a)
                    finally:
                        self.pop()
            except (Unauthorized, ResourceDoesNotExist) as e:
                self.logger.warning(e)
                self.logger.warning(f"Assignments not accesible")
            finally:
                self.pop()

            self.push_raw(f"pages_{course.id}", "pages", 0)
            try:
                pages = course.get_pages()
                for p in pages:
                    self.push_raw(f"page_{p.title}", "page", 0)
                    try:
                        self.handle_page(p)
                    finally:
                        self.pop()
            except (Unauthorized, ResourceDoesNotExist) as e:
                self.logger.warning(e)
                self.logger.warning(f"Pages not accesible")
            finally:
                self.pop()

            try:
                fp_path = os.path.join(self.path, "front_page.html")
                fp_md_path = os.path.join(self.path, "front_page.md")
                fp = course.show_front_page().body

                if self._dl_page(fp, fp_path) and self.markdown:
                    self._dl_page_data(fp_path, course._requester)
                    self._markdownify(fp_path, fp_md_path)
            except (Unauthorized, ResourceDoesNotExist) as e:
                self.logger.warning(e)
                self.logger.warning(f"Front page not accesible")

            try:
                modules = course.get_modules()
                for m in modules:
                    self.recurse_module(m)
            except (Unauthorized, ResourceDoesNotExist) as e:
                self.logger.warning(e)
                self.logger.warning(f"Modules not accesible")

            try:
                groups = course.get_groups()
                for g in groups:
                    self.recurse_group(g)
            except (Unauthorized, ResourceDoesNotExist) as e:
                self.logger.warning(e)
                self.logger.warning(f"Groups not accesible")


            self.scrape_files(course)

            self.scrape_media(course)
        finally:
            self.pop()

    def recurse_group(self, group):
        try:
            try:
                self.push(group, "group")
            except KeyError:
                return
            json_path = os.path.join(self.path, "group.json")
            self._dl_obj(group, json_path)
            self.scrape_files(group)
        finally:
            self.pop()

    def scrape_files(self, obj):
        try:
            # Hack to put files under a separate subfolder from modules
            self.push_raw(f"files_{obj.id}", "files", 0)
            try:
                # get_folders() returns a flat list of all folders
                folders = obj.get_folders()
                for f in folders:
                    self.recurse_folder(f)
            except Unauthorized:
                self.logger.warning(f"Files not accesible")
        finally:
            self.pop()

    def scrape_media(self, obj):
        try:
            # Hack to put media under a separate subfolder from modules
            self.push_raw(f"media_{obj.id}", "media", 0)
            try:
                obj.__class__.get_media_objects = get_media_objects
                media_objs = obj.get_media_objects()
                for m in media_objs:
                    if "video" in m.media_type:
                        self.handle_media_video(m)
                    else:
                        self.logger.warning(
                            f"Media '{m.title}' type {m.media_type} is unsupported")
                        import pdb
                        pdb.set_trace()
            except (Unauthorized, ResourceDoesNotExist) as e:
                self.logger.warning(e)
                self.logger.warning(f"Media objects not accesible")
        finally:
            self.pop()

    def recurse_folder(self, folder):
        self.push(folder, "folder", name_key="full_name")
        try:
            files = folder.get_files()
            try:
                for f in files:
                    try:
                        f_name = f.title
                    except AttributeError:
                        try:
                            f_name = f.display_name
                        except Exception as e:
                            import pdb
                            pdb.set_trace()

                    f_path = os.path.join(self.path, f_name)

                    if self._should_write(f_path):
                        self.logger.info(f"Downloading {f_path}")
                        try:
                            f.download(f_path)
                            self.logger.info(f"{f_path} downloaded")
                        except (Unauthorized, ResourceDoesNotExist) as e:
                            self.logger.warning(f"file not accesible")
                            self.logger.warning(str(e))
            except (Unauthorized, ResourceDoesNotExist) as e:
                self.logger.warning(f"folder not accesible")
                self.logger.warning(str(e))
        finally:
            self.pop()

    def recurse_module(self, module):
        self.push(module, "module")
        try:
            items = module.get_module_items()
            for i in items:
                self.recurse_item(i)
        finally:
            self.pop()

    def recurse_item(self, item):
        self.push(item, "item", name_key="title")
        try:
            if item.type == "File":
                self.logger.info("Handling file")
                self.handle_file(item)
            elif item.type == "Page":
                self.logger.info("Handling page")
                self.handle_page(item)
            elif item.type == "Assignment":
                self.logger.info("Handling assignment")
                self.handle_assignment(item)
            elif item.type == "Quiz":
                self.logger.info("Handling quiz")
                self.handle_quiz(item)
            elif item.type == "SubHeader":
                # TODO: Assuming you can't nest subheaders, it's probably enough
                # to just pop the stack if the top contains a subheader, and then 
                # push a new folder for each subheader.
                self.logger.warning(
                    "SubHeader's are not supported for now, skipping")
                #self.handle_subheader(item)
            elif item.type == "ExternalUrl":
                self.logger.info("Handling external URL")
                self.handle_external_url(item)
            else:
                self.logger.warning(f"Unsupported type {item.type}")
                import pdb
                pdb.set_trace()
        finally:
            self.pop()

    def handle_external_url(self, item):
        file_path = os.path.join(self.path, f"{item.title}.txt")
        url = item.external_url
        if self._should_write(file_path):
            with open(file_path, "w") as f:
                f.write(url)
                self.logger.info(f"{file_path} downloaded")

    def handle_file(self, item):
        file_name = item.title
        file_url = item.url
        file_path = os.path.join(self.path, file_name)
        requester = item._requester
        self.logger.info(f"Downloading {file_name}")
        self._dl_canvas_file(
            file_url, file_path, requester)

    def handle_media_video(self, item):
        media_name = item.title
        media_path = os.path.join(self.path, media_name)
        sources = item.media_sources
        sources.sort(key=lambda s: int(s['size']), reverse=True)
        media_url = sources[0]['url']
        self._dl(media_url, media_path)

    def handle_page(self, item):
        if getattr(item, "page_url", None):
            url = item.page_url
        elif getattr(item, "url", None):
            url = item.url
        else:
            self.logger.error("Could not get url for page item")
            import pdb;pdb.set_trace()
        page = self._canvas.get_course(
            item.course_id).get_page(url)
        try:
            page_body = page.body
        except AttributeError:
            if page.locked_for_user:
                self.logger.info("Page locked, reason:")
                self.logger.info(page.lock_explanation)
            self.logger.error("Page not accessible")
            return

        page_path = os.path.join(self.path, "page.html")
        page_md_path = os.path.join(self.path, "page.md")

        if self.markdown and self._dl_page(page_body, page_path):
            self._markdownify(page_path, page_md_path)
            self._dl_page_data(page_path, item._requester)

    def handle_assignment(self, item):
        if getattr(item, "content_id", None):
            asn_id = item.content_id
        elif getattr(item, "id", None):
            asn_id = item.id
        else:
            self.logger.error("Could not get url for assignment item")
            import pdb;pdb.set_trace()

        page_path = os.path.join(self.path, "assignment.html")
        page_md_path = os.path.join(self.path, "assignment.md")
        json_path = os.path.join(self.path, "assignment.json")
        assignment = self._canvas.get_course(
            item.course_id).get_assignment(asn_id)

        self._dl_obj(assignment, json_path)

        page = assignment.description
        if page:
            if self.markdown and self._dl_page(page, page_path):
                self._markdownify(page_path, page_md_path)
                self._dl_page_data(page_path, item._requester)

        submission = assignment.get_submission(self.user)
        self.handle_submission(submission)

    def handle_quiz(self, item):
        page_path = os.path.join(self.path, "quiz.html")
        page_md_path = os.path.join(self.path, "quiz.md")
        json_path = os.path.join(self.path, "quiz.json")
        quiz = self._canvas.get_course(
            item.course_id).get_quiz(item.content_id)
        page = quiz.description
        if page:
            if self.markdown and self._dl_page(page, page_path):
                self._markdownify(page_path, page_md_path)
                self._dl_page_data(page_path, item._requester)
        self._dl_obj(quiz, json_path)

    def handle_submission(self, submission):
        self.push(submission, "submission", name_key="id")
        try:
            json_path = os.path.join(self.path, f"submission_{submission.id}.json")

            try:
                attachments = submission.attachments
                for a in attachments:
                    f_path = os.path.join(self.path, a["filename"])
                    url = a["url"]
                    self._dl(url, f_path)
            except AttributeError:
                self.logger.warning("No attachments found")

            self._dl_obj(submission, json_path)
        finally:
            self.pop()

    def push(self, obj, type, name_key="name"):
        id = obj.id
        try:
            name = str(getattr(obj, name_key))
        except:
            name = str(id)

        self.push_raw(name, type, id)

    def push_raw(self, name, type, id):
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
        return os.path.join(
            self._path, *[sanitize_filename(n) for n in self._names])

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
            try:
                self.logger.info(f"Downloading {path}")
                r = self._get(url)
                with open(path, "wb") as f:
                    f.write(r.content)
                    self.logger.info(f"{path} downloaded")
                    return True
            except MissingSchema as e:
                self.logger.error(f"{url} is not a valid url")
                return False
            except Exception as e:
                self.logger.error("file download failed")
                import pdb
                pdb.set_trace()
                self.logger.error(e)

    def _dl_page(self, page, path):
        if self._should_write(path):
            with open(path, "w") as f:
                f.writelines(page)
                self.logger.info(f"{path} downloaded")
                return True

    def _dl_obj(self, obj, path):
        if self._should_write(path):
            with open(path, "w") as f:
                json.dump(obj.__dict__, f, indent=2, default=str)
                self.logger.info(f"{path} downloaded")

    def _dl_page_data(self, src_path, requester):
        self.logger.info(f"Downloading page data for {src_path}")
        with open(src_path, "r") as f:
            src = f.read()

        soup = BeautifulSoup(src, "html.parser")
        links = soup.find_all('a')

        if links:
            self._mkd(os.path.join(self.path, "files"))
        for link in links:
            href = link.get("href")
            title = link.get("title")
            if not title:
                title = link.text
            if not href:
                self.logger.warning(f"Link not found for title {title}")
                continue
            self.logger.info(f"Downloading link for: {title}")
            self.logger.info(href)
            if href in self.visited_page_links:
                self.logger.warning("Page has been visited before, skipping")
                continue
            self.visited_page_links.append(href)
            if link.get("class") and "instructure_file_link" in link["class"] and "canvas" in href:
                # This is necessary because files don't always show up
                # under the files section of a course for some reason
                self.logger.info(
                    "Canvas file detected, using Canvas API for download")
                try:
                    self._dl_canvas_file(
                        href, os.path.join(self.path, "files"), requester)
                except (Unauthorized, ResourceDoesNotExist) as e:
                    self.logger.error("Could not download file")
            elif href.startswith("mailto"):
                self.logger.info("mailto link detected, saving email")
                mail_path = os.path.join(self.path, "files", title)
                with open(mail_path, "w") as f:
                    f.write(href)
            elif self._is_page_url(href):
                self.logger.info("Canvas page detected, handling page")
                page_item = self._page_url_to_item(href, requester)
                self.push_raw(f"page_{page_item.page_url}", "page", 0)
                try:
                    self.handle_page(page_item)
                except:
                    self.logger.info("Could not handle page item")
                finally:
                    self.pop()
            elif self._is_assignment_url(href):
                self.logger.info("Canvas assignment detected, handling assignment")
                assignment_item  = self._assignment_url_to_item(href, requester)
                self.push_raw(f"assignment_{assignment_item.content_id}", "assignment", 0)
                try:
                    self.handle_assignment(assignment_item)
                except:
                    self.logger.info("Could not handle assignment item")
                finally:
                    self.pop()
            else:
                self.logger.warning(
                    "Non Canvas file link, attempting generic download")
                dl_path = os.path.join(self.path, "files", title)
                self._dl(link["href"], dl_path)

        if self.videos:
            # Download Kaltura videos
            videos = soup.find_all('iframe', **{'id': 'kaltura_player'})
            for idx, video in enumerate(videos):
                video_path = os.path.join(self.path, "videos", f"{idx}.mp4")
                self._dl_video(video["src"], video_path)

    def _dl_canvas_file(self, url, path, requester):
        canvas_path = urllib.parse.urlparse(url).path
        canvas_path = canvas_path.replace("/api/v1", "")
        resp = requester.request("GET", canvas_path)
        file = File(requester, resp.json())
        dl_path = os.path.join(path, file.filename)
        if not self._should_write(dl_path):
            return
        file.download(dl_path)
        self.logger.info(f"{dl_path} downloaded")
        return True

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

    def _is_page_url(self, url):
        page_regex = re.compile(r".+courses/\d+/pages/.+")
        matches = page_regex.match(url)
        return bool(matches)

    def _is_assignment_url(self, url):
        page_regex = re.compile(r".+courses/\d+/assignments/.+")
        matches = page_regex.match(url)
        return bool(matches)

    def _page_url_to_item(self, url, requester):
        return self._url_to_item(url, requester, "page_url")

    def _assignment_url_to_item(self, url, requester):
        return self._url_to_item(url, requester, "content_id")

    def _url_to_item(self, url, requester, attrname):
        segments = url.split("/")
        course_idx = segments.index("courses")
        course_id = segments[course_idx + 1]
        name = segments[-1]
        item = types.SimpleNamespace()
        item.course_id = course_id
        item._requester = requester
        setattr(item, attrname, name)
        return item


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




