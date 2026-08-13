#!/bin/bash
#
# Lints the source. This is what CI runs, so it is the check to satisfy before
# pushing.
#
# There is deliberately no --fix: the formatter that used to live here (black
# -l 132) treats the line length as a target rather than a ceiling, so it joins
# hand-wrapped code into single long lines. Nothing in the source needs
# reformatting -- max-line-length in tox.ini is a limit, and wrapping shorter
# than it is a choice made for readability, not a defect to be corrected.

uv run flake8 --config tox.ini
