#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec /usr/bin/python3 -I ./ctf_event.py install "$@"
