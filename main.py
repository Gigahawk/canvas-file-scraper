import argparse
import logging
import sys
import requests
import os
import pprint
import json
from bs4 import BeautifulSoup
import re
from canvas_file_scraper.scraper import CanvasScraper

log_formatter = logging.Formatter(
    "[%(levelname)-5.5s][%(name)s] %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

file_handler = logging.FileHandler("scraper.log")
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)


def main():
    parser = argparse.ArgumentParser(
            description='Grabs all files for all courses on Canvas')
    parser.add_argument(
        'canvas_api_key', metavar='key', type=str,
        help='Canvas API Key obtained from "settings"')
    parser.add_argument(
        '-u', '--canvas_url', type=str, default='canvas.ubc.ca',
        help='Canvas base URL (default: canvas.ubc.ca)')
    parser.add_argument(
        '-v', '--video', action='store_true',
        help='Enable kaltura video downloads (Warning: spacetime intensive)')
    parser.add_argument(
        '-o', '--overwrite', type=str, default='no',
        help='Can be one of "yes", "no", or "ask", (default: no)')
    parser.add_argument(
        '-d', '--directory', type=str, default='./files',
        help='Directory to store downloaded files in (default: ./files)')
    parser.add_argument(
        '-m', '--markdown', action="store_true",
        help='Convert downloaded pages to markdown')

    args = parser.parse_args()
    scraper = CanvasScraper(
        args.canvas_url,
        args.canvas_api_key,
        args.directory,
        args.overwrite,
        args.video,
        args.markdown,
        logger)

    logger.info("Starting scrape")
    scraper.scrape()


if __name__ == "__main__":
    main()
