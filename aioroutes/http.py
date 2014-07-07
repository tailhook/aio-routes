import asyncio
import logging
from operator import attrgetter
from urllib.parse import urlparse, parse_qsl
from http.cookies import SimpleCookie

from .util import cached_property
from .core import Context
from .core import ValueResolver, HierarchicalResolver
from .core import Scope, endpoint, resource
from .exceptions import NotFound, InternalRedirect, InternalError
from .exceptions import WebException, OutOfScopeError, MethodNotAllowed
from .request import BaseRequest


log = logging.getLogger(__name__)

HTTP = Scope('http')
FORM_CONTENT_TYPE = 'application/x-www-form-urlencoded'


class PathResolver(HierarchicalResolver):

    index_method = 'index'
    default_method = 'default'
    future_path_artifact = 'future_path'
    past_path_artifact = 'past_path'

    @staticmethod
    def get_path(ctx):
        path = ctx.request.parsed_uri.path.strip('/')
        if path:
            path = path.split('/')
        else:
            path = []
        return path



class MethodResolver(ValueResolver):

    def get_value(self, ctx):
        return ctx.request.method.upper()

    def child_not_found(self, ctx, name):
        # TODO(tailhook) enumerate allowed methods
        raise MethodNotAllowed()


def http_resource(fun):
    """Decorator to denote a method which returns HTTP-only resource"""
    return resource(fun, scopes=[HTTP])


def page(fun):
    """Decorator to denote a method which works only for http"""
    return endpoint(fun, scopes=[HTTP])


class Site(object):
    site_scope = HTTP
    positional_arguments_factory = staticmethod(PathResolver.get_path)  # sorry
    keyword_arguments_factory = attrgetter('request.form_arguments')
    context_factory = Context

    def __init__(self, *, resources=()):
        self.resources = resources

    @asyncio.coroutine
    def _resolve(self, request):
        ctx = self.context_factory(request, self.site_scope)
        for i in self.resources:
            ctx.start(i,
                *self.positional_arguments_factory(ctx),
                **self.keyword_arguments_factory(ctx))
            resolver = i.get_resolver_for_scope(self.site_scope)
            if resolver:
                try:
                    return (yield from resolver.resolve(ctx))
                except OutOfScopeError:
                    continue
        else:
            raise NotFound()

    def _safe_dispatch(self, request):
        while True:
            try:
                result = yield from self._resolve(request)
            except InternalRedirect as e:
                e.update_request(request)
                continue
            except Exception as e:
                if not isinstance(e, WebException):
                    log.exception("Can't process request %r", request)
                    e = InternalError(e)
                try:
                    return (yield from self.error_page(e))
                except Exception:
                    log.exception("Can't make error page for %r", e)
                    return e.default_response()
            else:
                return result

    @asyncio.coroutine
    def error_page(self, e):
        return e.default_response()

    @asyncio.coroutine
    def dispatch(self, req):
        result = yield from self._safe_dispatch(req)
        responsemeth = getattr(result, 'http_response', None)
        if responsemeth is not None:
            if asyncio.iscoroutinefunction(responsemeth):
                result = yield from responsemeth()
            else:
                result = result.http_response()
        if isinstance(result, (str, bytes)):
            if isinstance(result, str):
                result = result.encode('utf-8')
            result = [200, (), result]
        if len(result) < 3:
            if len(result) == 2:
                result = [result[0], (), result[1]]
            else:
                result = [200, (), result[0]]
        return result


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


class BaseHTTPRequest(BaseRequest):
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
