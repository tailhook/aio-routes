import asyncio
from .exceptions import OutOfScopeError


class cached_property(object):

    def __init__(self, fun):
        self.function = fun
        self.name = fun.__name__

    def __get__(self, obj, cls):
        if obj is None:
            return self
        res = obj.__dict__[self.name] = self.function(obj)
        return res


class marker_object(object):
    __slots__ = ('name',)

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return '<{}>'.format(self.name)


class DictResourceMixin(dict):

    @asyncio.coroutine
    def resolve_local(self, name):
        try:
            return self[name]
        except KeyError:
            raise OutOfScopeError()


