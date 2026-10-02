#!/usr/bin/env python
"""Check backend dependency sync."""
from tests.unit.test_dependency_wiring import test_requirements_and_pyproject_are_synchronized

def main():
    test_requirements_and_pyproject_are_synchronized()
    print("ok")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
