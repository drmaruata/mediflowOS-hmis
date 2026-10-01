#!/usr/bin/env python
"""Django CLI entrypoint."""
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError("Unable to import Django.") from exc
    execute_from_command_line(sys.argv)
