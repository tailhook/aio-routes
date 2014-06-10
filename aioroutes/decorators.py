import logging
import asyncio
from functools import partial

from .exceptions import OutOfScopeError


log = logging.getLogger(__name__)


def postprocessor(fun):
    """A decorator that accepts method's output and processes it

    Works only on leaf nodes. Typical use cases are:

    * turn dict of variables into a JSON
    * render a template from the dict.
    """
    if not hasattr(fun, '_aio_post'):
        fun._aio_post = []
    def wrapper(proc):
        proc = asyncio.coroutine(proc)
        fun._aio_post.append(proc)
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
    if not hasattr(fun, '_aio_pre'):
        fun._aio_pre = []
    def wrapper(proc):
        proc = asyncio.coroutine(proc)
        fun._aio_pre.append(proc)
        return fun
    return wrapper


def decorator(fun):
    fun = asyncio.coroutine(fun)
    assert asyncio.iscoroutinefunction(fun), \
        "Decorated function must be coroutine"
    def wrapper(parser):
        parser = asyncio.coroutine(parser)
        olddec = getattr(fun, '_aio_deco', None)
        oldcallee = getattr(fun, '_aio_deco_callee', None)
        if olddec is None:
            @asyncio.coroutine
            def callee(self, ctx, *args, **kw):
                try:
                    args, tail, kw = yield from fun._aio_sig(
                        ctx, *args, **kw)
                except (TypeError, ValueError) as e:
                    log.debug("Signature mismatch %r %r", args, kw,
                        exc_info=e)  # debug
                    raise OutOfScopeError()
                else:
                    return (yield from fun(self, *args, **kw))
        else:
            @asyncio.coroutine
            def callee(self, resolver, *args, **kw):
                return (yield from olddec(self, resolver,
                    partial(oldcallee, self, resolver),
                    *args, **kw))

        fun._aio_deco = parser
        fun._aio_deco_callee = callee
        return fun
    return wrapper
