import argparse
import requests
import pprint
import os
import urllib
import re

INVALID_CHARS = "[<>:/\\|?*\"]|[\0-\31]"

def __removeInvalidChars(name):
    name = name.strip()
    return re.sub(INVALID_CHARS, "-", name)

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

response = requests.get(url_courses, params=None, headers=HEADERS)
courses = response.json()

for course in courses:
    course_name = __removeInvalidChars(course['name'])
    course_id = course['id']
    print(f'COURSE: {course_name}')
    url_modules = f'{url_courses}/{course_id}/modules'
    response = requests.get(url_modules, params=None, headers=HEADERS)
    modules = response.json()
    for module in modules:
        module_name = __removeInvalidChars(module['name'])
        module_path = os.path.join('.', args.directory, course_name, module_name)
        url_items = module['items_url']
        print(f'MODULE: {module_name}')
        response = requests.get(url_items, params=None, headers=HEADERS)
        items = response.json()
        os.makedirs(module_path, exist_ok=True)
        for item in items:
            if item['type'] == 'File':
                url_file_info = item['url']
                response = requests.get(url_file_info, params=None, headers=HEADERS)
                file_info = response.json()

                # Could use unquote_plus, but files downloaded from
                # the site leave the plusses in
                # file_name = urllib.parse.unquote_plus(file_info['filename'])
                file_name = __removeInvalidChars(urllib.parse.unquote(file_info['filename']))

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

                open(file_path, 'wb').write(response.content)


