import asyncio
import aioroutes as route
from aioroutes.aiohttp import HttpProto
from functools import partial


class Child(route.Resource):

    @route.page
    def page1(self):
        return 'page1'

    @route.page
    def page2(self):
        return 'page2'

    @route.page
    def index(self):
        raise route.PathRewrite('/child/page1')


class Root(route.Resource):

    child = Child()

    @route.page
    def index(self):
        return "Index Page"

    @route.page
    def hello(self):
        return "Hello world"

    @route.page
    def hello_user(self, user):
        return "Hello {}!".format(user)


@asyncio.coroutine
def main():
    serv = yield from asyncio.get_event_loop().create_server(
        partial(HttpProto, route.Site(resources=[
            Root(),
            ])), port=8000)
    print("Listening on http://localhost:8000")
    yield from serv.wait_closed()


if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(main())
