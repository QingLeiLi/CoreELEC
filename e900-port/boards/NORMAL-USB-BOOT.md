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

Video qualification is separate: the current SYSTEM omitted media modules
because absolute hidden build paths were filtered by the package recipe.
Runtime-only recovery modules are under `/storage/e900-media-overlay38`.
Do not persist them merely because initialization succeeds: H.264 decoding
was still zero-frame, stuck waiting for the incorrect DMC mask, and stopping
the player then busy-polled inside driver teardown. A pin-checked three-
instruction DMC candidate is prepared separately, not yet validated.

The image-building pipeline still needs to adopt this tested booti layout;
the earlier bootm/container script is not the normal candidate documented here.
