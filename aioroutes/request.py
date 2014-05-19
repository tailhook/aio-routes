import asyncio
from urllib.parse import urlparse, parse_qsl
from http.cookies import SimpleCookie

from .util import cached_property
from .core import Sticker


FORM_CONTENT_TYPE = 'application/x-www-form-urlencoded'


class LegacyMultiDict(object):
    """Utilitary class which wrap dict to make it suitable for old utilities
    like wtforms"""

    def __init__(self, pairs=None):
        self._dic = {}
        if not pairs is None:
            self.update(pairs)

    def update(self, pairs):
        for k, v in pairs:
            if k not in self._dic:
                self._dic[k] = [v]
            else:
                self._dic[k].append(v)

    def getlist(self, k):
        return list(self._dic[k])

    def __contains__(self, k):
        return k in self._dic

    def __iter__(self):
        for k in self._dic:
            yield k

    def __len__(self):
        return len(self._dic)


@Sticker.register
class BaseRequest(object):
    """Base request object

    It has some common preprocessing, but the key is that concrete constructor
    must populate the following attributes, for it to work:
    * method: str
    * uri: str
    * content_type: str
    * cookie: str
    * body: bytes (used only for form-urlencoded content-type)

    """

    @cached_property
    def parsed_uri(self):
        return urlparse(self.uri)

    @cached_property
    def form_arguments(self):
        arguments = {}
        if hasattr(self, 'uri'):
            arguments.update(parse_qsl(self.parsed_uri.query))
        body = getattr(self, 'body', None)
        if body and self.content_type == FORM_CONTENT_TYPE:
            arguments.update(parse_qsl(self.body.decode('ascii')))
        return arguments

    @cached_property
    def legacy_arguments(self):
        arguments = LegacyMultiDict()
        if hasattr(self, 'uri'):
            arguments.update(parse_qsl(self.parsed_uri.query))
        body = getattr(self, 'body', None)
        if body and self.content_type == FORM_CONTENT_TYPE:
            arguments.update(parse_qsl(self.body.decode('ascii')))
        return arguments

    @cached_property
    def cookies(self):
        cobj = SimpleCookie(self.cookie)
        return dict((k, cobj[k].value) for k in cobj)

    @classmethod
    @asyncio.coroutine
    def create(cls, resolver):
        return resolver.request
