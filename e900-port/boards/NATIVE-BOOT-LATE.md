# GXLX2 native boot: registration ordering

The first nine-patch source build (58a677f, run 44288134295) did not boot on
E900V21C. Its files and all 28 SYSTEM media modules passed offline readback.
The following controls isolate registration ordering without requiring another
full rebuild for each experiment.

| Trial | Kernel and change | Observed result |
| --- | --- | --- |
| 69 | Native kernel; known-good legacy DTB, initrd and SYSTEM | Logo, then Android fallback reported by user |
| 70 | Change only the kernel to the working diagnostic kernel | Fresh CE boot, Kodi active, no restarts |
| 73 | Native kernel; only add `initcall_blacklist=vdec_reg_ops_init` | Fresh CE boot, Kodi active, no restarts |
| 74 | On boot73, register the same seven buses with a freshly audited temporary helper | DMC status 0xfffff; Kodi remains active; RDMA interrupts begin |
| 75 | Native kernel diagnostic: move original registration after the final existing late initcall | Fresh CE boot; seven bus pointers present; no blacklist or helper; Kodi active, no restarts |

Trial75 preserves the original registration function, its table, and the original
final ALSA callback and return value. A 48-byte position-independent stub occupies
verified executable linker padding after __idmap_text_end. Two RELATIVE relocation
addends redirect the early and final initcall slots. Only these locations differ
from the native build. Live RAM verifies the stub and all seven published buses.
This diagnostic binary is not a source-built release.

The ordering result does not identify the first unsafe early consumer. The
registration API copies callback records without MMIO. The codec IO driver is
registered by a core initcall; its mappings are established in its platform probe.
An unmapped callback can return -1 with a stack dump, and later mapped consumers
may also access unsupported GXLX2 blocks. Neither mechanism has yet been established
as the exact failure. Avoid claiming a proven NULL mapping or absent hardware.

The revised linux0006 keeps GXLX2 interfaces unpublished during postcore init and
registers them using late_initcall_sync. Other SoCs retain the original postcore
path. Its __initdata table remains valid until free_initmem after late initcalls.
Host checks compile the actual patched source, exercise both registered phases,
verify seven bus mappings, preserve the other CPU paths, and propagate allocation
failure from the late hook.

The exact source-linked late hook position can precede some existing synchronous
late callbacks, whereas trial75 deliberately runs after the last existing one.
An ARM source rebuild and hardware regression remain required. Full native SYSTEM
boot, media playback, physical HDMI/audio and remote input are separate gates;
the legacy SYSTEM controls do not establish those outcomes.
