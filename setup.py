import sys
import sysconfig as _sc

from setuptools import Extension, setup

# Stable ABI (py_limited_api) is only valid for CPython non-free-threaded builds.
# PyPy uses its own ABI; free-threaded CPython (Py_GIL_DISABLED) is incompatible.
_is_cpython = sys.implementation.name == "cpython"
_ext_suffix = _sc.get_config_var("EXT_SUFFIX") or ""
_freethreaded = bool(_sc.get_config_var("Py_GIL_DISABLED")) or "t-" in _ext_suffix
_use_stable_abi = _is_cpython and not _freethreaded

extra_compile_args: list[str] = []
extra_link_args: list[str] = []

if sys.platform == "win32":
    extra_link_args = ["-static"]
    extra_compile_args = ["/std:c11"]
    if _use_stable_abi:
        extra_compile_args += ["/DPy_LIMITED_API=0x030A0000"]
else:
    extra_compile_args = ["-Werror=incompatible-pointer-types"]
    if _use_stable_abi:
        extra_compile_args += ["-DPy_LIMITED_API=0x030A0000"]


def get_c_sources(include_headers=False):
    sources = [
        "module.c",
        "upstream-quickjs/dtoa.c",
        "upstream-quickjs/libregexp.c",
        "upstream-quickjs/libunicode.c",
        "upstream-quickjs/quickjs.c",
    ]
    if include_headers:
        sources += [
            "upstream-quickjs/cutils.h",
            "upstream-quickjs/dtoa.h",
            "upstream-quickjs/libregexp-opcode.h",
            "upstream-quickjs/libregexp.h",
            "upstream-quickjs/libunicode-table.h",
            "upstream-quickjs/libunicode.h",
            "upstream-quickjs/list.h",
            "upstream-quickjs/quickjs-atom.h",
            "upstream-quickjs/quickjs-opcode.h",
            "upstream-quickjs/quickjs.h",
        ]
    return sources


_quickjs = Extension(
    "_quickjs",
    # HACK.
    # See https://github.com/pypa/packaging-problems/issues/84.
    sources=get_c_sources(include_headers=("sdist" in sys.argv)),
    extra_compile_args=extra_compile_args,
    extra_link_args=extra_link_args,
    py_limited_api=_use_stable_abi,
)

setup(ext_modules=[_quickjs])
