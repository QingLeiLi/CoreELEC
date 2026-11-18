# E900V21C normal USB boot candidate

The normal loader uses the hardware-tested clock-guarded Image and MP2 DT,
with the byte-identical original CE initramfs. It does not write evidence,
set a persistent environment, touch eMMC, or consult one-attempt markers.
Removing the USB drive retains the existing Android boot path.

Prepare with `scripts/make-normal-boot-kit.py KERNEL DTB INITRD OUTPUT --mkimage PATH`.
This tool deliberately pins the tested artifacts; it is not a generic packer
for arbitrary future kernel builds. Existing SYSTEM must match its manifest.

Live filenames are `e900-Image-guard`, `e900-full.dtb`, `e900-uInitrd-normal`,
`s905_autoscript`, `aml_autoscript`, and `cfgload`. Preserve SYSTEM and kernel.img.
Backup/rollback of the three scripts is on the box in `/storage/e900-before36`.
The normal kit also keeps manifests and the original CE initramfs hash.

Two consecutive ordinary warm reboots reached CE with different boot IDs,
Mali live, no Oops taint and Kodi active with no auto restarts. GUI geometry
was 1920x1080 using the temporary CE userdata disp_cap override. Physical
HDMI remains unverified while HPD=0. The kernel still contains a binary DI
clock guard; source equivalents have not been fully ARM-built yet.

Video qualification remains incomplete. The original SYSTEM omitted all 28
media modules because the package filtered an absolute hidden build ancestor.
The package installer fix now uses relative discovery and rejects an empty
install; the image packer also audits the actual SYSTEM module list.

Runtime trial45 combined the five-instruction VLD DMC mask candidate with a
one-boot helper that registers the seven verified media buses through the
kernel's existing API. The missing registrations previously made every codec
register read return zero. The corrected interface read real DMC status;
H.264 produced 13 frames and 27 decoder interrupts, and Stop released the
channel normally. Frames then stalled because VSYNC did not run with HPD=0.
This is first-frame decoding evidence, not sustained video/physical HDMI
validation. No runtime media overlay or helper was persisted.

A direct HDMI disp_mode experiment lost SSH and the box subsequently booted
again automatically. No persistent journal/pstore explains that reboot, so
its precise cause is unresolved. Kodi/Mali/IR are healthy after recovery;
normal USB scripts remain unchanged. Avoid repeating that force-mode test
without prearranged durable kernel logging and recovery.

The cloud image pipeline now uses `boards/e900-usb-image.src`, matching the
tested booti addresses with generic build filenames `e900-Image`,
`e900-uInitrd`, and `dtb.img`. It extracts the byte-identical original CE newc
ramdisk from Image.lzo and wraps it as an ARM64 gzip legacy initrd. ARM64
header/load bounds, init executable, ramdisk CRCs, all FAT payload readbacks,
and SYSTEM/build provenance are checked. This updated pipeline passes host
FAT/SquashFS fixture tests; a fresh full ARM source build remains pending.
