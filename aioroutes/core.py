import abc
import logging
import inspect
import asyncio
from functools import partial

from .util import marker_object
from .exceptions import NotFound, ChildNotFound, MethodNotAllowed
from .exceptions import InternalError, WebException, InternalRedirect


log = logging.getLogger(__name__)

_LEAF_METHOD = marker_object('LEAF_METHOD')
_LEAF_HTTP_METHOD = marker_object('LEAF_HTTP_METHOD')
_RESOURCE_METHOD = marker_object('RESOURCE_METHOD')
_RES_HTTP_METHOD = marker_object('RES_HTTP_METHOD')
_RESOURCE = marker_object('RESOURCE')

# Helps to return result ealier, i.e. in preprocessor
_INTERRUPT = marker_object('INTERRUPT')


class BaseResolver(metaclass=abc.ABCMeta):

    _LEAF_METHODS = {_LEAF_METHOD}
    _RES_METHODS = {_RESOURCE_METHOD}
    resolver_class_attr = 'resolver_class'
    default_method = None
    index_method = None

    def __init__(self, request, parent=None):
        self.request = request
        self.parent = parent
        self.resource = None

    @abc.abstractmethod
    def __next__(self):
        pass

    def __iter__(self):
        return self

    def child_error(self):
        raise NotFound()

    @abc.abstractmethod
    def set_args(self, args):
        pass

    def unused_part(self, name):
        pass  # Do nothing for many resolvers except Path

    @asyncio.coroutine
    def resolve(self, root):
        self.resource = node = root
        for name in self:
            # assert name is not None, "Wrong name from {!r}".format(self)
            try:
                node = yield from node.resolve_local(name)
            except ChildNotFound:
                if self.default_method is not None:
                    try:
                        node = getattr(node, self.default_method)
                    except AttributeError:
                        self.child_error()
                    else:
                        # current path part should be passed to default method
                        self.unused_part(name)
                else:
                    self.child_error()
            kind = getattr(node, '_zweb', None)
            if kind in self._LEAF_METHODS:
                result = yield from  _dispatch_leaf(node, node.__self__, self)
                return result
            elif kind in self._RES_METHODS:
                newnode, tail = yield from _dispatch_resource(
                    node, node.__self__, self)
                if newnode is _INTERRUPT:
                    return tail  # tail is actual result in this case
                self.set_args(tail)
                self.resource = node = newnode
            elif kind is _RESOURCE:
                self.resource = node
            else:
                log.debug("Wrong kind %r", kind)
                raise NotFound()  # probably impossible but ...
            res_class = getattr(node, self.resolver_class_attr, None)
            if res_class is None:
                raise RuntimeError("Value {!r} is not a resource"
                    .format(node))
            if not isinstance(self, res_class):
                newres = res_class(self.request, self)
                result = yield from newres.resolve(node)
                return result

        if self.index_method is not None:
            meth = getattr(node, self.index_method, None)
            if(meth is not None
                and getattr(meth, '_zweb', None) in self._LEAF_METHODS):
                result = yield from _dispatch_leaf(meth, node, self)
                return result

        raise NotFound()


class PathResolver(BaseResolver):

    _LEAF_METHODS = {_LEAF_METHOD, _LEAF_HTTP_METHOD}
    _RES_METHODS = {_RESOURCE_METHOD, _RES_HTTP_METHOD}
    resolver_class_attr = 'http_resolver_class'
    index_method = 'index'
    default_method = 'default'

    def __init__(self, request, parent=None):
        super().__init__(request, parent)
        while parent is not None:
            if isinstance(parent, PathResolver):
                self.args = parent.args.copy()
                break
        else:
            path = request.parsed_uri.path.strip('/')
            if path:
                self.args = path.split('/')
            else:
                self.args = []
        self.kwargs = dict(request.form_arguments)

    def __next__(self):
        try:
            return self.args.pop(0)
        except IndexError:
            raise StopIteration()

    def set_args(self, args):
        self.args = list(args)

    def unused_part(self, part):
        self.args.insert(0, part)


class MethodResolver(BaseResolver):

    _LEAF_METHODS = {_LEAF_METHOD, _LEAF_HTTP_METHOD}
    _RES_METHODS = {_RESOURCE_METHOD, _RES_HTTP_METHOD}
    resolver_class_attr = 'http_resolver_class'

    def __init__(self, request, parent=None):
        super().__init__(request, parent)
        self.args = parent.args
        self.kwargs = dict(request.form_arguments)

    def __next__(self):
        return self.request.method.upper()

    def child_error(self):
        raise MethodNotAllowed()

    def set_args(self, args):
        self.args = args


class ResourceInterface(metaclass=abc.ABCMeta):

    @abc.abstractmethod
    @asyncio.coroutine
    def resolve_local(self, name):
        """Returns child resource or method or raises ChildNotFound"""


@ResourceInterface.register
class Resource(object):
    http_resolver_class = PathResolver
    _zweb = _RESOURCE

    @asyncio.coroutine
    def resolve_local(self, name):
        if not name.isidentifier() or name.startswith('_'):
            raise ChildNotFound()
        target = getattr(self, name, None)
        if target is None:
            raise ChildNotFound()
        kind = getattr(target, '_zweb', None)
        if kind is not None:
            return target
        raise ChildNotFound()


@ResourceInterface.register
class DictResource(dict):

    http_resolver_class = PathResolver
    _zweb = _RESOURCE


    @asyncio.coroutine
    def resolve_local(self, name):
        try:
            return self[name]
        except KeyError:
            raise ChildNotFound()


class Site(object):

    def __init__(self, *, resources=()):
        self.resources = resources

    @asyncio.coroutine
    def _resolve(self, request):
        for i in self.resources:
            res = i.http_resolver_class(request)
            try:
                return (yield from res.resolve(i))
            except NotFound:
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


@asyncio.coroutine
def _dispatch_resource(fun, self, resolver):
    preproc = getattr(fun, '_zweb_pre', ())
    result = None
    for prefun in preproc:
        result = yield from prefun(self, resolver,
            *resolver.args, **resolver.kwargs)
        if result is not None:
            break
    if result is None:
        deco = getattr(fun, '_zweb_deco', None)
        if deco is not None:
            result = yield from deco(self, resolver,
                partial(fun._zweb_deco_callee, self, resolver),
                *resolver.args, **resolver.kwargs)
            return result
        else:
            try:
                args, tail, kw = yield from fun._zweb_sig(resolver,
                    *resolver.args, **resolver.kwargs)
            except (TypeError, ValueError) as e:
                log.debug("Signature mismatch %r %r",
                    resolver.args, resolver.kwargs,
                    exc_info=e)  # debug
                raise NotFound()
            else:
                resource = yield from fun(*args, **kw)
                return resource, tail
    else:
        for proc in fun._zweb_post:
            result = yield from proc(self, resolver, result)
        return _INTERRUPT, result


class ReprHack(str):
    __slots__ = ()
    def __repr__(self):
        return str(self)


def _compile_signature(fun, partial):
    sig = inspect.signature(fun)
    fun_params = [
        inspect.Parameter('resolver',
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD)]
    args = []
    kwargs = []
    vars = {
        '__empty__': object(),
        }
    lines = []
    self = True
    varkw = None
    varpos = None

    for name, param in sig.parameters.items():
        ann = param.annotation
        if param.default is not inspect.Parameter.empty:
            vars[name + '_def'] = param.default
            if ann is not inspect.Parameter.empty:
                # If we have annotation, we want to make sure that annotation
                # is not applied to a default value so we pass __empty__
                # and check for it later
                defname = ReprHack('__empty__')
            else:
                defname = ReprHack(name + '_def')
        else:
            defname = inspect.Parameter.empty
        if ann is not inspect.Parameter.empty:
            if isinstance(ann, type) and issubclass(ann, Sticker):
                lines.append('  {0} = yield from {0}_create(resolver)'
                    .format(name))
                vars[name + '_create'] = ann.create
            elif ann is not inspect.Parameter.empty:
                lines.append('  if {0} is __empty__:'.format(name))
                lines.append('    {0} = {0}_def'.format(name))
                lines.append('  else:')
                if isinstance(ann, type) and ann.__module__ == 'builtins':
                    lines.append('    {0} = {1}({0})'.format(
                        name, ann.__name__))
                    fun_params.append(param.replace(
                        default=defname))
                else:
                    lines.append('    {0} = {0}_type({0})'.format(name))
                    vars[name + '_type'] = ann
                    fun_params.append(param.replace(
                        annotation=ReprHack(name + '_type'),
                        default=defname))
        elif not self:
            fun_params.append(param.replace(default=defname))

        if param.kind == inspect.Parameter.VAR_KEYWORD:
            varkw = name
            assert varkw, "Empty argument name?"
        elif param.kind == inspect.Parameter.VAR_POSITIONAL:
            varpos = name
            assert varpos, "Empty argument name?"
        else:
            if param.kind == inspect.Parameter.KEYWORD_ONLY:
                kwargs.append('{0!r}: {0}'.format(name))
            elif not self:
                args.append(name)
        if self:
            self = False
    if not varpos and partial:
        for i, p in enumerate(fun_params):
            if p.kind == inspect.Parameter.KEYWORD_ONLY:
                fun_params.insert(i, inspect.Parameter('__tail__',
                    kind=inspect.Parameter.VAR_POSITIONAL))
                break
        else:
            fun_params.append(inspect.Parameter('__tail__',
                kind=inspect.Parameter.VAR_POSITIONAL))
    if not varkw:
        fun_params.append(inspect.Parameter('__kw__',
            kind=inspect.Parameter.VAR_KEYWORD))
    funsig = inspect.Signature(fun_params)
    lines.insert(0, 'def __sig__{}:'.format(funsig))
    if len(args) == 1:
        args = args[0] + ','
    else:
        args = ', '.join(args)
    kwarg_string = '{' + ', '.join(kwargs) + '}'
    if varkw:
        if kwargs:
            lines.append('  {}.update({})'.format(varkw, kwarg_string))
        kwarg_string = varkw
    if varpos:
        lines.append('  return ({}) + {}, (), {}'.format(
            args, varpos,  kwarg_string))
    elif partial:
        lines.append('  return ({}), __tail__, {}'.format(args, kwarg_string))
    else:
        lines.append('  return ({}), (), {}'.format(args, kwarg_string))
    text = '\n'.join(lines)
    code = compile(text, '__sig__', 'exec')
    exec(code, vars)
    sigfun = asyncio.coroutine(vars['__sig__'])
    if __debug__:
        sigfun.__text__ = text
    return sigfun


def resource(fun):
    """Decorator to denote a method which returns resource to be traversed"""
    fun = asyncio.coroutine(fun)
    fun._zweb = _RESOURCE_METHOD
    fun._zweb_sig = asyncio.coroutine(_compile_signature(fun, partial=True))
    return fun


def http_resource(fun):
    """Decorator to denote a method which returns HTTP-only resource"""
    fun = resource(fun)
    fun._zweb = _RES_HTTP_METHOD
    return fun


@asyncio.coroutine
def _dispatch_leaf(fun, self, resolver):
    preproc = getattr(fun, '_zweb_pre', ())
    result = None
    for prefun in preproc:
        result = yield from prefun(self, resolver,
            *resolver.args, **resolver.kwargs)
        if result is not None:
            break
    if result is None:
        deco = getattr(fun, '_zweb_deco', None)
        if deco is not None:
            result = yield from deco(self, resolver,
                partial(fun._zweb_deco_callee, self, resolver),
                *resolver.args, **resolver.kwargs)
        else:
            try:
                args, tail, kw = yield from fun._zweb_sig(resolver,
                    *resolver.args, **resolver.kwargs)
            except (TypeError, ValueError) as e:
                log.debug("Signature mismatch %r %r",
                    resolver.args, resolver.kwargs,
                    exc_info=e)  # debug
                raise NotFound()
            else:
                result = yield from fun(*args, **kw)
    for proc in fun._zweb_post:
        result = yield from proc(self, resolver, result)
    return result


def endpoint(fun):
    """Decorator to denote a method which returns some result to the user"""
    fun = asyncio.coroutine(fun)
    if not hasattr(fun, '_zweb_post'):
        fun._zweb_post = []
    fun._zweb = _LEAF_METHOD
    fun._zweb_sig = asyncio.coroutine(_compile_signature(fun, partial=False))
    return fun


def page(fun):
    """Decorator to denote a method which works only for http"""
    fun = endpoint(fun)
    fun._zweb = _LEAF_HTTP_METHOD
    return fun


def postprocessor(fun):
    """A decorator that accepts method's output and processes it

    Works only on leaf nodes. Typical use cases are:

    * turn dict of variables into a JSON
    * render a template from the dict.
    """
    if not hasattr(fun, '_zweb_post'):
        fun._zweb_post = []
    def wrapper(proc):
        proc = asyncio.coroutine(proc)
        fun._zweb_post.append(proc)
        return fun
    return wrapper


def preprocessor(fun):
    """A decorators that runs before request

    When preprocessor returns None, request is processed as always. If
    preprocessor return not None it's return value treated as return value
    of a leaf node (even if it's resource) including executing all
    postprocessors.

    Works both on resources and leaf nodes. Typical use casees are:

    * access checking
    * caching
    """
    if not hasattr(fun, '_zweb_pre'):
        fun._zweb_pre = []
    def wrapper(proc):
        proc = asyncio.coroutine(proc)
        fun._zweb_pre.append(proc)
        return fun
    return wrapper


def decorator(fun):
    fun = asyncio.coroutine(fun)
    assert asyncio.iscoroutinefunction(fun), \
        "Decorated function must be coroutine"
    def wrapper(parser):
        parser = asyncio.coroutine(parser)
        olddec = getattr(fun, '_zweb_deco', None)
        oldcallee = getattr(fun, '_zweb_deco_callee', None)
        if olddec is None:
            @asyncio.coroutine
            def callee(self, resolver, *args, **kw):
                try:
                    args, tail, kw = yield from fun._zweb_sig(
                        resolver, *args, **kw)
                except (TypeError, ValueError) as e:
                    log.debug("Signature mismatch %r %r", args, kw,
                        exc_info=e)  # debug
                    raise NotFound()
                else:
                    return (yield from fun(self, *args, **kw))
        else:
            @asyncio.coroutine
            def callee(self, resolver, *args, **kw):
                return (yield from olddec(self, resolver,
                    partial(oldcallee, self, resolver),
                    *args, **kw))

        fun._zweb_deco = parser
        fun._zweb_deco_callee = callee
        return fun
    return wrapper


class Sticker(metaclass=abc.ABCMeta):
    """
    An object which is automatically put into arguments in the view if
    specified in annotation
    """
    __superseded = {}

    @classmethod
    @abc.abstractmethod
    @asyncio.coroutine
    def create(cls, resolver):
        """Creates an object of this class based on resolver"""

    @classmethod
    def supersede(cls, sub):
        oldsup = cls.__superseeded.get(cls, None)
        if oldsup is not None:
            if issubclass(sub, oldsup):
                pass  # just supersede it again
            elif issubclass(oldsup, sub):
                return  # already superseeded by more specific subclass
            else:
                raise RuntimeError("{!r} is already superseeded by {!r}"
                    .format(cls, oldsup))

        super().register(sub)
        cls.__superseded[cls] = sub
