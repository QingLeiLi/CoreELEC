#!/bin/sh
# Do not turn WOL off in ExecStop: systemd stops services before suspend/shutdown.
set -eu
board=$(tr -d '\000' < /proc/device-tree/coreelec-dt-id)
[ "$board" = gxlx2_p291_1g_e900v21c ] || exit 0
state=$(LC_ALL=C /usr/sbin/ethtool eth0)
# The vendor driver increments IRQ wake depth on every set, even if already g.
case "$state" in
  *"Wake-on: g"*) exit 0 ;;
esac
exec /usr/sbin/ethtool -s eth0 wol g
