#!/bin/sh
# Run only after the receiver has confirmed the netconsole READY marker.
set -eu
p=/sys/module/amvideo/parameters
[ "$(cat "$p/gxlx2_hw_init_wait")" = Y ]
[ "$(cat "$p/gxlx2_hw_init_status")" = 1 ]
systemctl stop kodi
[ "$(cat /sys/class/vdec/vdec_status)" = 'No vdec.' ]
printf '<6>E900_VIDEO_INIT_RELEASE_BEGIN\n' > /dev/kmsg
printf '1\n' > "$p/gxlx2_hw_init_run"
[ "$(cat "$p/gxlx2_hw_init_status")" = 2 ]
printf '<6>E900_VIDEO_INIT_RELEASE_OK\n' > /dev/kmsg
systemctl start kodi
