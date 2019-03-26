# Canvas File Scraper

This repo hosts a simple python script to download all available files in all courses on your Canvas page.

## Dependencies
 - Python 3.6+
 - [requests](https://pypi.org/project/requests/)
 - [markdownify](https://github.com/matthewwithanm/python-markdownify)
 - [bs4](https://pypi.org/project/bs4/)

If you use [pipenv](https://github.com/pypa/pipenv) you can just run `pipenv install` to setup the environment.

## Usage
```shell
python canvas-scraper.py <CANVAS_API_KEY>
```

For info on how to get an API key please refer to the [Canvas Dev course](https://canvas.instructure.com/courses/785215/pages/getting-started-with-the-api)

## Todo
 - Add async option
 - Add support for more item types
 - Store returned json data from Canvas API
