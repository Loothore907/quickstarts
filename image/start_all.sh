#!/bin/bash

set -e

export DISPLAY=:${DISPLAY_NUM}
/home/computeruse/image/xvfb_startup.sh
/home/computeruse/image/tint2_startup.sh
/home/computeruse/image/mutter_startup.sh
/home/computeruse/image/x11vnc_startup.sh
