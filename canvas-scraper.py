import argparse
import requests
import os
import urllib
import pprint
import json
from markdownify import markdownify as md
from bs4 import BeautifulSoup
import re
pp = pprint.PrettyPrinter(indent=4)

parser = argparse.ArgumentParser(
        description='Grabs all files for all courses on Canvas')
parser.add_argument('canvas_api_key', metavar='key', type=str,
                    help='Canvas API Key obtained from "settings"')
parser.add_argument('-u', '--canvas-url', type=str,
                    help='Canvas base URL (default: canvas.ubc.ca)')
parser.add_argument('-o', '--overwrite', type=str,
                    help='Can be one of "yes", "no", or "ask", (default: no)')
parser.add_argument('-d', '--directory', type=str,
                    help='Directory to store downloaded files in (default: ./files)')

args = parser.parse_args()

if not args.canvas_url:
    args.canvas_url = 'canvas.ubc.ca'

if not args.overwrite or args.overwrite in ['yes', 'no', 'ask']:
    args.overwrite = 'no'
if not args.directory:
    args.directory = './files'

HEADERS = {'Authorization': f'Bearer {args.canvas_api_key}'}

URL_BASE = f'https://{args.canvas_url}/api/v1'


url_courses = f'{URL_BASE}/courses'

courses = []
page = 1
while True:
    print(f'Grabbing page {page} of courses')
    response = requests.get(f'{url_courses}?page={page}', params=None, headers=HEADERS)
    if len(response.json()) == 0:
        print(f'Page empty, continuing')
        break
    courses.extend(response.json())
    page += 1

for course in courses:
    course_name = course['name']
    course_id = course['id']
    course_path = os.path.join('.', args.directory, course_name)
    print(f'COURSE: {course_name}')
    url_front_page = f'{url_courses}/{course_id}/front_page'
    print(f'Grabbing front page for {course_name}')
    response = requests.get(url_front_page, params=None, headers=HEADERS)
    front_page = response.json()

    os.makedirs(course_path, exist_ok=True)
    course_front_page_name = os.path.join(course_path, 'front_page.html')

    with open(course_front_page_name, 'w') as f:
        f.writelines(front_page['body'])

    url_modules = f'{url_courses}/{course_id}/modules'
    modules = []
    page = 1
    while True:
        print(f'Grabbing page {page} of modules')
        response = requests.get(f'{url_modules}?page={page}', params=None, headers=HEADERS)
        if len(response.json()) == 0:
            print(f'Page empty, continuing')
            break
        modules.extend(response.json())
        page += 1
    for module in modules:
        module_name = module['name']
        module_path = os.path.join(course_path, module_name)
        print(f'MODULE: {module_name}')
        url_items =module["items_url"]

        module_size = int(module['items_count'])
        items = []
        page = 1
        while True:
            print(f'Grabbing page {page} of items')
            response = requests.get(f'{url_items}?page={page}', params=None, headers=HEADERS)
            if len(response.json()) == 0:
                print(f'Page empty, continuing')
                break
            items.extend(response.json())
            page += 1
        os.makedirs(module_path, exist_ok=True)
        for item in items:
            print(f"ITEM: {item['title']}, TYPE: {item['type']}")
            if item['type'] == 'File':
                url_file_info = item['url']
                response = requests.get(url_file_info, params=None, headers=HEADERS)
                file_info = response.json()

                # Could use unquote_plus, but files downloaded from
                # the site leave the plusses in
                # file_name = urllib.parse.unquote_plus(file_info['filename'])
                file_name = urllib.parse.unquote(file_info['filename'])

                url_file = file_info['url']
                file_path = os.path.join(module_path, file_name)

                if os.path.isfile(file_path) and args.overwrite is not 'yes':
                    if args.overwrite is 'no':
                        print(f'File {file_name} exists')
                        print('Skipping')
                        continue
                    else:
                        overwrite = input(f'File {file_name} exists: overwrite? (y/n): ') == 'y'
                        if not overwrite:
                            print('Skipping')
                            continue

                print(f"Downloading {item['title']}")
                response = requests.get(url_file, params=None, headers=HEADERS)
                with open(file_path, 'wb') as f:
                    f.write(response.content)
            elif item['type'] == 'Page':
                url_page_info = item['url']
                print("Downloading page content")
                response = requests.get(url_page_info, params=None, headers=HEADERS)
                page_info = response.json()

                page_path = os.path.join(module_path, item['title'])
                os.makedirs(page_path, exist_ok=True)

                body_path = os.path.join(page_path, 'body.html')
                body_md_path = os.path.join(page_path, 'body.md')
                with open(body_path, 'w') as f:
                    f.writelines(page_info['body'])

                print("Converting to markdown")
                with open(body_md_path, 'w') as f:
                    f.writelines(md(page_info['body']))

                soup = BeautifulSoup(page_info['body'], 'html.parser')
                links = soup.find_all('a', **{'data-api-returntype': 'File'})

                if len(links) > 0:
                    print("Downloading page files")
                    page_file_dir_path = os.path.join(page_path, 'files')
                    os.makedirs(page_file_dir_path, exist_ok=True)
                    for link in links:
                        file_name = link['title']
                        print(f"Downloading {file_name}")
                        response = requests.get(link['href'], params=None, headers=HEADERS)
                        page_file_path = os.path.join(page_file_dir_path, file_name)
                        with open(page_file_path, 'wb') as f:
                            f.write(response.content)
            elif item['type'] == 'Assignment':
                url_assignment_info = item['url']
                print("Downloading assignment content")
                response = requests.get(url_assignment_info, params=None, headers=HEADERS)
                assignment_info = response.json()

                assignment_path = os.path.join(module_path, item['title'])
                os.makedirs(assignment_path, exist_ok=True)

                assignment_file_name = os.path.join(assignment_path, 'assignment.json')
                assignment_description_name = os.path.join(assignment_path, 'description.html')

                with open(assignment_file_name, 'w') as f:
                    f.writelines(json.dumps(assignment_info, indent=4))

                with open(assignment_description_name, 'w') as f:
                    f.writelines(assignment_info['description'])


