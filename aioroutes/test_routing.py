import asyncio
import unittest
from time import time
from functools import wraps

# Sorry "web." notation is a legacy from zorro
import aioroutes as web
from aioroutes.http import BaseHTTPRequest
from aioroutes.exceptions import OutOfScopeError, NotFound, MethodNotAllowed


def instantiate(klass):
    """Class decorator which instantiates class in-place"""
    return klass()


class Request(BaseHTTPRequest):
    def __init__(self, uri):
        self.uri = uri


class MethRequest(BaseHTTPRequest):
    def __init__(self, method, uri):
        self.method = method
        self.uri = uri


class RoutingTestBase(unittest.TestCase):

    def resolve(self, uri):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.site._resolve(Request(uri)))
        finally:
            loop.close()

    def dispatch(self, uri):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.site._safe_dispatch(self.Request(uri)))
        finally:
            loop.close()


class TestLocalDispatch(unittest.TestCase):

    def setUp(self):

        class MyRes(web.Resource):

            @web.page
            def hello(self):
                return 'hello'

            @web.page
            def _hidden(self):
                return 'hidden'

            def invisible(self):
                return 'invisible'

        self.r = MyRes()

    def resolve_local(self, name):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.r.resolve_local(name))
        finally:
            loop.close()

    def testOK(self):
        self.assertEqual(self.resolve_local('hello'), self.r.hello)

    def testHidden(self):
        with self.assertRaises(OutOfScopeError):
            self.resolve_local('_hidden')

    def testInvisible(self):
        with self.assertRaises(OutOfScopeError):
            self.resolve_local('invisible')

    def testStrange(self):
        with self.assertRaises(OutOfScopeError):
            self.resolve_local('hello world')


class TestResolve(unittest.TestCase):

    def setUp(self):

        class Root(web.Resource):

            @web.page
            def index(self):
                return 'index'

            @web.page
            def about(self):
                return 'about'

            @web.resource
            def forum(self, id:int = None):
                if id is not None:
                    return Forum(id)
                raise web.PathRewrite('/forums')

            @web.page
            def no_annotation(self, val='default'):
                return 'na:' + val

            @web.page
            def forums(self):
                return 'forums'

            @web.page
            def request(self, req:BaseHTTPRequest):
                return req

        class Forum(web.Resource):

            def __init__(self, id):
                self.id = id

            @web.page
            def index(self):
                return 'forum(%d).index' % self.id

            @web.page
            def new_topic(self):
                return 'forum(%d).new_topic' % self.id

            @web.page
            def topic(self, topic:int, *, offset:int = 0, num:int = 10):
                return 'forum({}).topic({})[{}:{}]'.format(
                    self.id, topic, offset, num)
        self.site = web.Site(resources=[Root()])

    def resolve(self, uri):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.site._resolve(Request(uri)))
        finally:
            loop.close()

    def dispatch(self, uri):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.site._safe_dispatch(Request(uri)))
        finally:
            loop.close()


    def testIndex(self):
        self.assertEqual(self.resolve('/'), 'index')

    def testRequest(self):
        """Check how request sticker is passed to handler"""
        req = Request('/request')
        loop = asyncio.new_event_loop()
        try:
            nreq = loop.run_until_complete(self.site._resolve(req))
        finally:
            loop.close()
        self.assertIs(req, nreq)

    def testPage(self):
        self.assertEqual(self.resolve('/about'), 'about')

    def testSlash(self):
        self.assertEqual(self.resolve('/about/'), 'about')

    def testSuffix(self):
        with self.assertRaises(NotFound):
            self.resolve('/about/test')

    def testNoAnnotation(self):
        self.assertEqual(self.resolve('/no_annotation'), 'na:default')

    def testNoAnnotationVal(self):
        self.assertEqual(self.resolve('/no_annotation/val'), 'na:val')

    def testRedirect(self):
        self.assertEqual(self.dispatch('/forum'), 'forums')

    def testSlashRedirect(self):
        self.assertEqual(self.dispatch('/forum/'), 'forums')

    def testArg(self):
        self.assertEqual(self.resolve('/forum/10'), 'forum(10).index')

    def testArgSlash(self):
        self.assertEqual(self.resolve('/forum/10/'), 'forum(10).index')

    def testArgQuery(self):
        self.assertEqual(self.resolve('/forum?id=10'), 'forum(10).index')

    def testArgQuerySlash(self):
        self.assertEqual(self.resolve('/forum/?id=10'), 'forum(10).index')

    def testQueryAndPos(self):
        with self.assertRaises(NotFound):
            self.resolve('/forum/10?id=10')

    def testValueError(self):
        with self.assertRaises(NotFound):
            self.resolve('/forum/test')

    def testNested(self):
        self.assertEqual(self.resolve('/forum/11/new_topic'),
            'forum(11).new_topic')

    def testNestedSlash(self):
        self.assertEqual(self.resolve('/forum/11/new_topic/'),
            'forum(11).new_topic')

    def testNestedArg(self):
        self.assertEqual(self.resolve('/forum/12/topic/10'),
            'forum(12).topic(10)[0:10]')

    def testNestedQuery(self):
        self.assertEqual(self.resolve('/forum/12/topic/10?offset=10'),
            'forum(12).topic(10)[10:10]')

    def testNestedExcessive(self):
        with self.assertRaises(NotFound):
            self.resolve('/forum/12/topic/10/10')

    def testNestedQuery2(self):
        self.assertEqual(self.resolve('/forum/12/topic/10?offset=20&num=20'),
            'forum(12).topic(10)[20:20]')

    def testNestedAllQuery(self):
        self.assertEqual(
            self.resolve('/forum/12/topic?topic=13&offset=20&num=20'),
            'forum(12).topic(13)[20:20]')


class TestDecorators(unittest.TestCase):

    def setUp(self):

        @web.Sticker.register
        class User(object):
            def __init__(self, uid):
                self.id = uid
            @classmethod
            @asyncio.coroutine
            def create(cls, resolver):
                return cls(int(resolver.request.form_arguments.get('uid')))

        def add_prefix(fun):
            @web.postprocessor(fun)
            def processor(self, resolver, value):
                return 'prefix:[' + value + ']'
            return processor

        def add_suffix(suffix):
            def decorator(fun):
                @web.postprocessor(fun)
                def processor(self, resolver, value):
                    return '[' + value + ']:' + suffix
                return processor
            return decorator

        def form(fun):
            @web.decorator(fun)
            def wrapper(self, resolver, meth, **kw):
                if resolver.request.form_arguments:
                    return (yield from meth(1, b=2))
                else:
                    return 'form'
            return wrapper

        def hidden(fun):
            @web.decorator(fun)
            def wrapper(self, resolver, meth, a, b):
                return (yield from meth(a, b=b, c=69))
            return wrapper

        def check_access(real_checker):
            def decorator(fun):
                @web.preprocessor(fun)
                def wrapper(self, resolver, *args, **kw):
                    if real_checker((yield from User.create(resolver))):
                        return None
                    return 'denied'

                return wrapper
            return decorator

        self.last_latency = None
        def timeit(fun):
            @wraps(fun)
            def wrapper(me, *args, **kwargs):
                start = time()
                result = fun(me, *args, **kwargs)
                self.last_latency = time() - start
                return result
            return wrapper


        class Root(web.Resource):

            @web.page
            @add_prefix
            def about(self):
                return 'about'

            @web.page
            def profile(self, user: User):
                return 'profile(%d)' % (user.id)

            @web.page
            def friend(self, user: User, friend: int):
                return 'profile(%d).friend(%d)' % (user.id, friend)

            @add_prefix
            @web.page
            def info(self, uid: int):
                return 'info(%d)' % uid

            @web.page
            @timeit
            @add_prefix
            @add_suffix('suf')
            def banner(self, ad: int, user: User, *, position: str = "norm"):
                return 'banner(ad:{:d}, uid:{:d}, position:{})'.format(
                    ad, user.id, position)

            @web.resource
            @add_suffix('denied')
            @check_access(lambda u: u.id % 2 == 0)
            def forum(self, user:User, id:int=-1):
                return Forum(user, id)

            @form
            @web.page
            def form1(self, a, b):
                return 'form1({}, {})'.format(a, b)

            @add_prefix
            @web.page
            @form
            @hidden
            def form2(self, u:User, a, b, c):
                return 'form2({}, {}, {}, {})'.format(a, b, c, u.id)

        class Forum(web.Resource):

            def __init__(self, user, id):
                self.user = user
                self.id = id

            @web.page
            def index(self):
                return "forum(user:{})".format(self.user.id)

            @web.page
            @add_suffix('allowed')
            @check_access(lambda u: u.id % 3 == 0)
            @check_access(lambda u: u.id % 7 == 0)
            def topic(self, id:int):
                return "forum(user:{}, forum:{}, topic:{})".format(
                    self.user.id, self.id, id)

        self.site = web.Site(resources=[Root()])

    def resolve(self, uri):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.site._resolve(Request(uri)))
        finally:
            loop.close()

    def testPost(self):
        self.assertEqual(self.resolve('/about'), 'prefix:[about]')

    def testResourceSticker(self):
        self.assertEqual(self.resolve('/forum?uid=14'), 'forum(user:14)')

    def testSticker(self):
        self.assertEqual(self.resolve('/profile?uid=3'), 'profile(3)')

    def testStickerArg(self):
        self.assertEqual(self.resolve('/friend/2?uid=3'),
            'profile(3).friend(2)')

    def testPostArg(self):
        self.assertEqual(self.resolve('/info/3'), 'prefix:[info(3)]')

    def test2PostAndWrapDefPos(self):
        self.assertEqual(self.resolve('/banner/3?uid=4'),
            'prefix:[[banner(ad:3, uid:4, position:norm)]:suf]')
        self.assertTrue(self.last_latency < 0.01)  # also fail if it's None

    def test2PostAndWrapDefQuery(self):
        self.assertEqual(self.resolve('/banner/?ad=2&uid=5'),
            'prefix:[[banner(ad:2, uid:5, position:norm)]:suf]')
        self.assertTrue(self.last_latency < 0.01)  # also fail if it's None

    def test2PostAndWrapFull(self):
        self.assertEqual(self.resolve('/banner/3?uid=12&position=abc'),
            'prefix:[[banner(ad:3, uid:12, position:abc)]:suf]')

    def testDecoSkip(self):
        self.assertEqual(self.resolve('/form1'), 'form')

    def testDecoInvent(self):
        self.assertEqual(self.resolve('/form1?a=7'), 'form1(1, 2)')

    def test2DecoSkip(self):
        self.assertEqual(self.resolve('/form2'), 'prefix:[form]')

    def test2DecoInvent(self):
        self.assertEqual(self.resolve('/form2?uid=13'),
            'prefix:[form2(1, 2, 69, 13)]')

    def testCheckAccess(self):
        self.assertEqual(self.resolve('/forum/1/topic/2?uid=42'),
            '[forum(user:42, forum:1, topic:2)]:allowed')
        self.assertEqual(self.resolve('/forum/1/topic/2?uid=6'),
            '[denied]:allowed')
        self.assertEqual(self.resolve('/forum/1/topic/2?uid=21'),
            '[denied]:denied')
        self.assertEqual(self.resolve('/forum/1/topic/2?uid=14'),
            '[denied]:allowed')


class TestMethod(unittest.TestCase):

    def setUp(self):

        class Root(web.Resource):

            def __init__(self):
                super().__init__()
                self.about = About()
                self.hello = Hello()
                self.greeting = Greeting()

            @web.resource
            def forum(self, uid:int):
                return Forum(uid)


        class About(web.Resource):
            """Uses default resolver"""

            @web.page
            def index(self):
                return 'blank'

            @web.page
            def more(self, page:str):
                return 'PAGE:%s' % page

        class Hello(web.Resource):
            http_resolver = web.MethodResolver()

            @web.page
            def GET(self):
                return "hello:get"

            @web.page
            def PUT(self, data):
                return "hello:put:" + data

        class Forum(web.Resource):
            http_resolver = web.MethodResolver()

            def __init__(self, user):
                self.user = user

            @web.page
            def GET(self):
                return "forum(user:{})".format(self.user)

            @web.page
            def PATCH(self, topic:int):
                return "set:forum(user:{},topic:{})".format(self.user, topic)

        class NewResolver(web.PathResolver):
            index_method = 'default'

        class Greeting(web.Resource):
            http_resolver = NewResolver()

            @web.page
            def default(self, arg=None):
                assert arg != 'greeting', arg
                return 'greeting_default'

            @web.page
            def index(self):
                raise RuntimeError("Problem")

        self.site = web.Site(resources=[Root()])

    def resolve(self, meth, uri):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.site._resolve(MethRequest(meth, uri)))
        finally:
            loop.close()

    def testAbout(self):
        self.assertEqual(self.resolve('GET', '/about'), 'blank')

    def testHello(self):
        self.assertEqual(self.resolve('GET', '/hello'), 'hello:get')

    def testHelloPUT(self):
        self.assertEqual(self.resolve('PUT', '/hello/value'),
                         'hello:put:value')

    def testHelloPUTQuery(self):
        self.assertEqual(self.resolve('PUT', '/hello?data=something'),
                         'hello:put:something')

    def testLessArgs(self):
        with self.assertRaises(NotFound):
            self.resolve('GET', '/about/more')
        with self.assertRaises(NotFound):
            self.resolve('GET', '/about/more/')

    def testLonger(self):
        self.assertEqual(self.resolve('GET', '/about/more/abc'), 'PAGE:abc')

    def testGet(self):
        self.assertEqual(self.resolve('GET', '/forum?uid=37'),
            'forum(user:37)')

    def testLower(self):
        self.assertEqual(self.resolve('get', '/forum?uid=37'),
            'forum(user:37)')

    def testNonExistent(self):
        with self.assertRaises(MethodNotAllowed):
            self.resolve('FIX', '/forum?uid=37')

    @unittest.expectedFailure
    def testPatch(self):
        self.assertEqual(self.resolve('PATCH', '/forum/12?uid=37'),
            'set:forum(user:37,topic:12)')

    def testPatchQuery(self):
        self.assertEqual(self.resolve('PATCH', '/forum?uid=7&topic=6'),
            'set:forum(user:7,topic:6)')

    def testPatchQuerySlash(self):
        self.assertEqual(self.resolve('PATCH', '/forum/?uid=9&topic=8'),
            'set:forum(user:9,topic:8)')

    @unittest.expectedFailure
    def testPatchSlash(self):
        self.assertEqual(self.resolve('PATCH', '/forum/77/?uid=9'),
            'set:forum(user:9,topic:77)')

    def testNotEnough(self):
        with self.assertRaises(NotFound):
            self.resolve('PATCH', '/forum?uid=9')

    def testNewResolver(self):
        self.assertEqual(self.resolve('GET', '/greeting'), 'greeting_default')


class TestDictResource(unittest.TestCase):

    def setUp(self):

        class About(web.Resource):
            """Uses default resolver"""

            @web.page
            def index(self):
                return 'blank'

            @web.page
            def more(self, page:str):
                return 'PAGE:%s' % page

        self.site = web.Site(resources=[
            web.DictResource(about=About()),
            ])

    def resolve(self, uri):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.site._resolve(Request(uri)))
        finally:
            loop.close()

    def testAbout(self):
        self.assertEqual(self.resolve('/about'), 'blank')

    def testLessArgs(self):
        with self.assertRaises(NotFound):
            self.resolve('/about/more')
        with self.assertRaises(NotFound):
            self.resolve('/about/more/')

    def testLonger(self):
        self.assertEqual(self.resolve('/about/more/abc'), 'PAGE:abc')


class TestDefault(RoutingTestBase):

    def setUp(self):

        class Root(web.Resource):

            @web.page
            def default(self):
                return 'root_default'

            @instantiate
            class one(web.Resource):

                @web.page
                def index(self):
                    return 'one_index'

                @web.page
                def default(self, one):
                    return 'one:{}'.format(one)

            @instantiate
            class star(web.Resource):

                @web.page
                def default(self, *star):
                    return 'star:{}'.format(":".join(star))

            @instantiate
            class onestar(web.Resource):

                @web.page
                def default(self, one, *star):
                    return 'onestar({}):{}'.format(one, ":".join(star))


        self.site = web.Site(resources=[Root()])


    def testDefault(self):
        with self.assertRaises(NotFound):
            self.resolve('/')  # no arg default is not supported

    def testDefaultArg(self):
        self.assertEqual(self.resolve('/one/arg'), 'one:arg')

    def testDefaultIndex(self):
        self.assertEqual(self.resolve('/one'), 'one_index')

    def testDefaultMany(self):
        with self.assertRaises(NotFound):
            self.resolve('/one/arg/test')

    def testStar(self):
        with self.assertRaises(NotFound):
            self.resolve('/star')  # no arg default is not supported

    def testStarArg(self):
        self.assertEqual(self.resolve('/star/a'), 'star:a')

    def testStarArg2(self):
        self.assertEqual(self.resolve('/star/a/b'), 'star:a:b')

    def testOneStar(self):
        with self.assertRaises(NotFound):
            self.resolve('/onestar')  # no arg default is not supported

    def testOneStarArg(self):
        self.assertEqual(self.resolve('/onestar/a'), 'onestar(a):')

    def testOneStarArg2(self):
        self.assertEqual(self.resolve('/onestar/a/b'), 'onestar(a):b')

    def testOneStarArg3(self):
        self.assertEqual(self.resolve('/onestar/a/b/c'), 'onestar(a):b:c')


class TestVarKw(RoutingTestBase):

    def setUp(self):

        class Root(web.Resource):

            @web.page
            def justkw(self, **kw):
                return 'justkw:{!r}'.format(kw)

            @web.page
            def kwargkw(self, *, a, **kw):
                return 'kwargkw:{}:{!r}'.format(a, kw)

            @web.page
            def poskw(self, a, **kw):
                return 'poskw:{}:{!r}'.format(a, kw)

            @web.page
            def varposkw(self, *a, **kw):
                return 'varposkw:{}:{!r}'.format(','.join(a), kw)

        self.Root = Root
        self.site = web.Site(resources=[Root()])


    def testJustkwEmpty(self):
        self.assertEqual(self.resolve('/justkw'), 'justkw:{}')

    def testJustkw(self):
        self.assertEqual(self.resolve('/justkw?a=1'), "justkw:{'a': '1'}")

    def testKwargkw(self):
        self.assertEqual(self.resolve('/kwargkw?a=1&b=2'),
            "kwargkw:1:{'b': '2'}")

    def testPoskw(self):
        self.assertEqual(self.resolve('/poskw/a?b=2'),
            "poskw:a:{'b': '2'}")

    def testPoskw2(self):
        self.assertEqual(self.resolve('/poskw?a=1&b=2'),
            "poskw:1:{'b': '2'}")

    def testVarposkw(self):
        self.assertEqual(self.resolve('/varposkw/a/b/c?b=2'),
            "varposkw:a,b,c:{'b': '2'}")



if __name__ == '__main__':
    unittest.main()

