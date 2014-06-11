import abc
import logging
import asyncio
from functools import partial

from .util import marker_object
from .exceptions import OutOfScopeError
from .scope import Scope
from .signature import compile_signature


log = logging.getLogger(__name__)

LEAF_KIND = marker_object('leaf')
RESOURCE_METHOD_KIND = marker_object('resource_method')
RESOURCE_KIND = marker_object('resource')
GENERIC_SCOPE = Scope('generic')

# Helps to return result ealier, i.e. in preprocessor
_INTERRUPT = marker_object('INTERRUPT')


class BaseResolver(metaclass=abc.ABCMeta):

    default_method = None

    def _consumed(self, ctx, n=1):
        pass

    @asyncio.coroutine
    @abc.abstractmethod
    def resolve(self, ctx):
        pass

    def child_not_found(self, ctx, name):
        return None

    def _update_args(self, ctx):
        pass

    def _base_resolve(self, ctx, name):
        node = ctx.resource_path[-1]
        # assert name is not None, "Wrong name from {!r}".format(self)
        try:
            node = yield from node.resolve_local(name)
        except OutOfScopeError:
            if self.default_method is not None:
                node = getattr(node, self.default_method, None)
            else:
                node = self.child_not_found(ctx, name)
        else:
            self._consumed(ctx)
        scope = getattr(node, '_aio_scope', None)
        if scope is None or not scope.intersection(ctx.scope_set):
            raise OutOfScopeError(ctx.scope)
        self._update_args(ctx)
        kind = getattr(node, '_aio_kind', None)
        if kind is LEAF_KIND:
            ctx.leaf = node
            result = yield from ctx.dispatch_leaf(node, ctx.args, ctx.kwargs)
            return result
        elif kind is RESOURCE_METHOD_KIND:
            node, val = yield from ctx.dispatch_resource(node,
                ctx.args, ctx.kwargs)
            if node is _INTERRUPT:
                return val  # val is actual result in this case
            self._consumed(ctx, val)
        elif kind is RESOURCE_KIND:
            pass
        else:
            raise RuntimeError("Wrong kind {!r}".format(kind))
        ctx.resource_path.append(node)
        resolver = node.get_resolver_for_scope(ctx.scope)
        if resolver is None:
            raise RuntimeError("Value {!r} is not a resource".format(node))
        result = yield from resolver.resolve(ctx)
        return result


class ValueResolver(BaseResolver):

    @asyncio.coroutine
    def resolve(self, ctx):
        return self._base_resolve(ctx, self.get_value(ctx))

    @abc.abstractmethod
    def get_value(self):
        pass


class HierarchicalResolver(BaseResolver):

    index_method = None
    future_path_artifact = None
    past_path_artifact = None

    @abc.abstractmethod
    def get_path(cls, ctx):
        pass

    def get_path_cached(self, ctx):
        path = ctx.artifacts.get(self.future_path_artifact)
        if path is None:
            path = self.get_path(ctx)
            ctx.artifacts[self.past_path_artifact] = []
            ctx.artifacts[self.future_path_artifact] = path
        return path

    def _get_next_item(self, ctx):
        path = self.get_path_cached(ctx)
        if path:
            return path[0]
        else:
            return None

    def _update_args(self, ctx):
        ctx.set_args(ctx.artifacts.get(self.future_path_artifact))

    def _consumed(self, ctx, n=1):
        fp = ctx.artifacts[self.future_path_artifact]
        pp = ctx.artifacts[self.past_path_artifact]
        if n == 1: # very common case
            if fp:  # may consume more than there is
                pp.append(fp.pop(0))
        else:
            pp.extend(fp[:n])
            del fp[:n]

    @asyncio.coroutine
    def resolve(self, ctx):
        name = self._get_next_item(ctx)
        if name is None:
            if self.index_method is None:
                raise OutOfScopeError(ctx.scope)
            meth = getattr(ctx.resource_path[-1], self.index_method, None)
            scope = getattr(meth, '_aio_scope', None)
            if scope is None or not scope.intersection(ctx.scope_set):
                raise OutOfScopeError(ctx.scope)
            kind = getattr(meth, '_aio_kind', None)
            if kind is not LEAF_KIND:
                raise OutOfScopeError(ctx.scope)
            ctx.leaf = meth
            result = yield from ctx.dispatch_leaf(meth,
                ctx.args, ctx.kwargs)
            return result
        else:
            result = yield from self._base_resolve(ctx, name)
            return result


class ResourceInterface(metaclass=abc.ABCMeta):

    @abc.abstractmethod
    @asyncio.coroutine
    def resolve_local(self, name):
        """Returns child resource or method or raises OutOfScopeError"""

    def get_resolver_for_scope(self, scope):
        return getattr(self, scope.name + '_resolver', None)


class BaseResource(ResourceInterface):
    _aio_kind = RESOURCE_KIND
    # by default all resources work for everything
    _aio_scope = frozenset([GENERIC_SCOPE])

    @asyncio.coroutine
    def resolve_local(self, name):
        if not name.isidentifier() or name.startswith('_'):
            raise OutOfScopeError()
        target = getattr(self, name, None)
        if target is None:
            raise OutOfScopeError()
        kind = getattr(target, '_aio_kind', None)
        if kind is not None:
            return target
        raise OutOfScopeError()


def resource(fun, *, scopes=frozenset([GENERIC_SCOPE])):
    """Decorator to denote a method which returns resource to be traversed"""
    fun = asyncio.coroutine(fun)
    fun._aio_kind = RESOURCE_METHOD_KIND
    fun._aio_scope = frozenset(scopes)
    fun._aio_sig = compile_signature(fun, partial=True)
    return fun


def endpoint(fun, *, scopes):
    """Decorator to denote a method which returns some result to the user"""
    fun = asyncio.coroutine(fun)
    if not hasattr(fun, '_aio_post'):
        fun._aio_post = []
    fun._aio_kind = LEAF_KIND
    fun._aio_scope = frozenset(scopes)
    fun._aio_sig = compile_signature(fun, partial=False)
    return fun


class Context(object):

    def __init__(self, request, scope):
        self.request = request
        self.scope = scope
        self.scope_set = frozenset([GENERIC_SCOPE, scope])
        self.resource_path = []
        self.stickers = {}
        self.artifacts = {}
        self.args = ()
        self.kwargs = {}

    def start(self, resource, *args, **kwargs):
        self.resource_path = [resource]
        self.args = args
        self.kwargs = kwargs
        self.artifacts.clear()

    def set_args(self, args):
        self.args = args

    def set_kwargs(self, kwargs):
        self.kwargs = kwargs

    @asyncio.coroutine
    def dispatch_resource(self, fun, args, kw):
        owner = fun.__self__
        preproc = getattr(fun, '_aio_pre', ())
        result = None
        for prefun in preproc:
            result = yield from prefun(owner, self,
                *args, **kw)
            if result is not None:
                break
        if result is None:
            deco = getattr(fun, '_aio_deco', None)
            if deco is not None:
                result = yield from deco(owner, self,
                    partial(fun._aio_deco_callee, owner, self),
                    *args, **kw)
                return result
            else:
                try:
                    args, tail, kw = yield from fun._aio_sig(self,
                        *args, **kw)
                except (TypeError, ValueError) as e:
                    log.debug("Signature mismatch %r %r",
                        args, kw, exc_info=e)  # debug
                    raise OutOfScopeError(self.scope)
                else:
                    resource = yield from fun(*args, **kw)
                    return resource, tail
        else:
            for proc in fun._aio_post:
                result = yield from proc(owner, self, result)
            return _INTERRUPT, result

    @asyncio.coroutine
    def dispatch_leaf(self, fun, args, kw):
        owner = fun.__self__
        preproc = getattr(fun, '_aio_pre', ())
        result = None
        for prefun in preproc:
            result = yield from prefun(owner, self, *args, **kw)
            if result is not None:
                break
        if result is None:
            deco = getattr(fun, '_aio_deco', None)
            if deco is not None:
                result = yield from deco(owner, self,
                    partial(fun._aio_deco_callee, owner, self), *args, **kw)
            else:
                try:
                    args, tail, kw = yield from fun._aio_sig(self,
                        *args, **kw)
                except (TypeError, ValueError) as e:
                    log.debug("Signature mismatch %r %r",
                        args, kw, exc_info=e)  # debug
                    raise OutOfScopeError(self.scope)
                else:
                    result = yield from fun(*args, **kw)
        for proc in fun._aio_post:
            result = yield from proc(owner, self, result)
        return result
