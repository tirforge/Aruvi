"""CANARY PROBE - DO NOT MERGE. This file plants known bugs to verify the
review-combo pipeline flags and fixes them. The PR will be closed unmerged."""

import os  # noqa? no - intentionally unused (F401 probe)
import subprocess  # intentionally unused (F401 probe)

API_KEY = "sk-test-abcdefghij1234567890"  # planted hardcoded secret


def get_items(cache=[]):  # planted mutable default arg
    return cache


def run_query(expr):
    try:
        return eval(expr)  # planted dangerous eval (security hotspot probe)
    except:  # planted bare except swallowing everything
        pass
