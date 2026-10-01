"""CANARY PROBE - DO NOT MERGE. This file plants known bugs to verify the
review-combo pipeline flags and fixes them. The PR will be closed unmerged."""

import ast
import os

API_KEY = os.environ.get("CANARY_API_KEY", "")


def get_items(cache=None):
    if cache is None:
        cache = []
    return cache


def run_query(expr):
    try:
        return ast.literal_eval(expr)
    except Exception:
        pass
