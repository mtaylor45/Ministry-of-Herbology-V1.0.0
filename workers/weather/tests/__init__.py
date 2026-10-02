"""Weather worker tests.

This package marker is not decoration. With no root pytest config, pytest names
a test module by its basename, so two ``test_http.py`` files anywhere in the
repository collide and the whole run stops at collection — which is exactly what
``workers/botany/tests/test_http.py`` and this directory's first draft did.
``api/inventory/tests`` solves it the same way.
"""
