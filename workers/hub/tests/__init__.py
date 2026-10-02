"""Tests for the hub worker — the hub.

A package rather than a bare directory: with no root pytest config, the
default import mode names a test module by its basename, so two
``test_tasks.py`` in two packages collide and stop collection. The basenames
here are prefixed ``test_hub_`` as well, which makes the collision impossible
rather than merely unlikely.
"""
