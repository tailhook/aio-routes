import asyncio
import unittest

from aioroutes.static import StaticResource
from aioroutes.http import BaseHTTPRequest
from aioroutes.exceptions import NotFound
import aioroutes as web


class Request(BaseHTTPRequest):
    def __init__(self, uri):
        self.uri = uri


class TestFiles(unittest.TestCase):

    def setUp(self):
        self.site = web.Site(resources=[
            StaticResource('.', ['aioroutes']),
            ])

    def get_file(self, uri):
        loop = asyncio.new_event_loop()
        try:
            val =  loop.run_until_complete(
                self.site._resolve(Request(uri)))
        finally:
            loop.close()
        assert val[0] == '200 OK'
        return val[2]

    def test_ok(self):
        self.assertTrue(b'cached_property' in
            self.get_file('/aioroutes/util.py'))

    def test_root(self):
        with self.assertRaises(NotFound):
            self.get_file('/')

    def test_dir(self):
        with self.assertRaises(NotFound):
            self.get_file('/aioroutes/')

    def test_bad(self):
        with self.assertRaises(NotFound):
            self.get_file('/setup.py')

    def test_not_found(self):
        with self.assertRaises(NotFound):
            self.get_file('/aoiroutes/not_found_file.html')
