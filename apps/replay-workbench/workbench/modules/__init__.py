"""Built-in module registry. A module is registered by the application's own code, never by an uploaded archive or a request.

Only S3 is registered. A module provides describe(), inspect(), command() and collect() (blueprint section 10); the core owns uploads,
workspaces, supervision, cancellation, HTTP, logs and export.
"""
import re

MODULE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


class UnknownModule(KeyError):
    """The module identifier is not registered (or is not even a well-formed identifier)."""


class Registry:
    def __init__(self):
        self._modules = {}

    def register(self, module):
        mid = module.name
        if not isinstance(mid, str) or not MODULE_ID_RE.match(mid):
            raise ValueError(f"invalid module identifier {mid!r}")
        if mid in self._modules:
            raise ValueError(f"module {mid!r} is already registered")
        self._modules[mid] = module
        return module

    def get(self, module_id):
        if not isinstance(module_id, str) or not MODULE_ID_RE.match(module_id) or module_id not in self._modules:
            raise UnknownModule(module_id if isinstance(module_id, str) and len(module_id) <= 64 else "?")
        return self._modules[module_id]

    def ids(self):
        return sorted(self._modules)

    def describe_all(self):
        return [self._modules[i].describe() for i in self.ids()]


def default_registry():
    from .s3 import S3Module
    r = Registry()
    r.register(S3Module.shipped())
    return r


def default_module():
    """Used by the worker process (module_ref): the shipped S3 module."""
    return default_registry().get("s3")
