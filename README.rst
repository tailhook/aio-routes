==========
aio-routes
==========

Aio-routes is a URL routing library for web applications. It doesn't support
typical pattern-based or regular-expression bases routing. But rather it traverses objects while resolving an url. See examples below, for more info


Usage
=====

There are two basic classes:

* ``Site`` represents top-level entity, containing list of the resources

* ``Resource`` is a point in hierarchy of url resolving

Basically you have a single ``Site`` instance, which you create in ``main``
function of the application, and multiple resources which are "mounted" into
the site hierarchy.

Let's see an example:

..code-block:: python

    class Root(aioroutes.Resource):

        @aioroutes.page
        def some_path(self):
            return "hello"

    @asyncio.coroutine
    def main():
        site = aioroutes.Site(resources=[Root()])
        serv = yield from asyncio.get_event_loop().create_server(
            partial(HttpProto, site), port=8000)
        print("Listening on http://localhost:8000")
        yield from serv.wait_closed()


    if __name__ == '__main__':
        asyncio.get_event_loop().run_until_complete(main())


Now if you go to ``http://localhost:8000/some_path`` you will see ``hello``.
In the next examples we will avoid ``main`` boilerplate.

.. note:: We don't use this property now, but ``@aioroutes.page`` makes a
   function a coroutine (just like ``@asyncio.coroutine`` do), so you can do
   some blocking things in that function

You may noticed, that home page ``http://localhost:8000`` is empty. To fill
in that page, you need to add a special method ``index``:

..code-block:: python

    class Root(aioroutes.Resource):

        @aioroutes.page
        def index(self):
            return "home page"


Parameters
==========

If your page needs any parameters, you can just add them to a method:

..code-block:: python

        @aioroutes.page
        def hello(self, name):
            return "Hello {}!".format(name)

In this case you may visit a page by any of the following urls::

    http://localhost:8000/hello/John
    http://localhost:8000/hello?name=John

Submitting arguments as urlencoded ``POST`` form works too.

The usual semantics for python arguments are observed. For example you can
make keyword-only arguments and you may have defaults:

..code-block:: python

        @aioroutes.page
        def hello(self, *, name="World"):
            return "Hello {}!".format(name)

You may also use annotations to make aguments typed:

..code-block:: python

        @aioroutes.page
        def add(self, left: int, right: int):
            return str(left + right)

Any function that raises ``ValueError`` when input is wrong, can be used as a
validator. I.e. it may be ``json.loads`` or the contract from trafaret_ library

.. note:: If arguments are not validated a 404 page is returned. It matches
   the common case where ``/forum/some_crap`` is looked for instead of
   ``/forum?topic=123``. But it's not suitable for form validation (unless you
   do it on javascript-side). See recipe below for forms.


Child Resources
===============

Multiple (sub)applications can be combined in two ways:

1. By "mounting" the application in url hierarchy.
2. By supplying multiple resources in ``Site`` constructor

The first option is used most of the time. Let's take an example. Let's
pretend we have two applications:

.. code-block:: python

    class Forum(aioroutes.Resource):

        @aioroutes.page
        def index(self):
            return 'topics'

        @aioroutes.page
        def topic(self, topic:int):
            return 'topic: {}'.format(topic)

    class News(aioroutes.Resource):

        @aioroutes.page
        def index(self):
            return 'all_news'

        @aioroutes.page
        def article(self, slug:str):
            return 'article: {}.format(slug)

Now, we can combine them in two ways:

.. code-block:: python

    class Root(aioroutes.Resource):
        forum = Forum()
        news = News()

Then pages will be accessible with the following urls::

    http://localhost:8000/forum/
    http://localhost:8000/forum/topic/1234
    http://localhost:8000/news/article/something

If you would combine them at the site level::

    site = aioroutes.Site(resources=[Forum(), News()])

You will get the following urls working::

    http://localhost:8000/ -> forum
    http://localhost:8000/topic/1234
    http://localhost:8000/article/something

The semantics are exactly the following. Given the first resource, try to
resolve URL. If that resolves, return a page. If that raises ``NotFound``
(equivalent of 404 page), try next resource. So which page is served depends
on order of resources specified. In general this way is ''not recommended''.


Stickers
========

TBD


Resolvers
=========

TBD


Dynamic Resources
=================

TBD


Decorators
==========

TBD


Exceptions
==========

TBD

Recipes
=======


Templates
---------

TBD


Forms
-----

TBD



History
=======

The library was ininitally named ``zorro.web`` and was a part of zorro_
networking library.

.. _zorro: http://github.com/tailhook/zorro
.. _trafaret: http://github.com/Deepwalker/trafaret
