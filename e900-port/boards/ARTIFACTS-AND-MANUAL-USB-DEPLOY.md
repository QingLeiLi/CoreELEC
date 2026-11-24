# 构建产物结构与手动部署U盘

更新：2026-11-24。适用于提交`3a58f58120`起的初始化修复/网络诊断测试构建。以下是操作说明，本次编写文档没有写入U盘或操作设备。

## 1. 下载哪个产物

Actions选择`profile=decoder`、`target=image`。下载名称类似`e900-decoder-image-<run_id>`的artifact ZIP并解压。外层可能因下载方式多套一层目录，以找到`USB-TEST-STATUS.txt`所在目录为准。

典型目录：

```text
artifact解压目录/
├── export/
│   └── decoder/
│       ├── USB-TEST-STATUS.txt
│       ├── build-metadata.json
│       ├── target/
│       │   ├── CoreELEC-...-E900V21C-USB-TEST.img.gz
│       │   ├── CoreELEC-...-E900V21C-USB-TEST.img.gz.sha256
│       │   └── CoreELEC-...-E900V21C-USB-TEST.img.gz.json
│       ├── build.CoreELEC-Amlogic-ng.arm-21/
│       │   └── build/
│       │       ├── linux-<固定commit>/
│       │       │   ├── .config
│       │       │   ├── arch/arm64/boot/
│       │       │   │   ├── Image
│       │       │   │   ├── Image.lzo
│       │       │   │   └── dts/amlogic/coreelec-gxl/
│       │       │   │       └── gxlx2_p291_1g_e900v21c.dtb
│       │       │   └── drivers/net/netconsole.ko
│       │       └── media_modules-aml-<固定commit>/drivers/.../*.ko
│       └── logs/
└── logs/
```

`.config`是隐藏文件。旧任务没有新增加的netconsole.ko导出，某些诊断构建也没有完整镜像，不能只凭artifact下载成功就认定可写盘。

| 产物 | 用途 |
|---|---|
| `target/*-E900V21C-USB-TEST.img.gz` | **本板完整U盘测试镜像；部署首选**，包含分区表、FAT启动分区及STORAGE分区 |
| 同名`.sha256`、`.json` | 镜像摘要、任务来源、配套文件摘要和准备结果，不是启动文件 |
| `build-metadata.json` | profile、版本、补丁和编译结果；完整镜像应为`last_action=image`、`last_action_exit_code=0`、`usb_image_prepared=true` |
| 裸`Image` | ARM64内核，不是完整系统；直接写到整个U盘不能启动本项目 |
| `Image.lzo` | 此CE构建流程使用的Android boot-image容器，不能仅凭后缀把它当普通lzo数据；准备镜像时放为`kernel.img` |
| DTB | 本板设备树；完整镜像已放为根目录`dtb.img` |
| `.ko` | 内核/媒体模块，必须与对应内核配套；正常完整部署由SYSTEM提供，不需逐个手工复制 |

内核或媒体模块构建失败时仍可能导出部分文件。只有已经准备成功的USB-TEST镜像用于下面的完整部署。

## 2. 镜像内部与启动关系

解压`.img.gz`得到的`.img`是磁盘镜像，不是单个分区或普通安装包：

```text
U盘
├── 第1分区：FAT，卷标 COREELEC
│   ├── aml_autoscript       ┐
│   ├── s905_autoscript      ├─ 三份相同的U-Boot二进制脚本
│   ├── cfgload              ┘
│   ├── e900-Image             原始ARM64内核
│   ├── e900-uInitrd           配套CE initramfs的U-Boot封装
│   ├── dtb.img                本机1GB板级DTB
│   ├── SYSTEM                 SquashFS只读根系统，包含Kodi和内核模块
│   ├── kernel.img             原CE容器，当前脚本不以它作为booti输入
│   └── 其他原CE附带配置、摘要及device_trees等文件
└── 第2分区：ext4，卷标 STORAGE
    └── 挂载为/storage，保存Kodi配置、视频、日志等
```

实际脚本执行`booti`，依次加载`e900-Image`到0x11000000、`e900-uInitrd`到0x15000000、`dtb.img`到0x18000000。启动参数按卷标寻找COREELEC/STORAGE；initramfs挂载FAT根目录的SYSTEM。

当前USB-TEST脚本包含：

```text
amvideo.gxlx2_hw_init_wait=1
loglevel=7
```

这意味着系统先等待网络日志校准，再手动执行新增寄存器初始化；看到pending状态不是自动判定启动失败。完整脚本源码见[启动脚本](e900-usb-image.src)。三个autoscript文件是带头部和CRC的二进制，**不能直接用文本编辑器修改字符串**。

## 3. 方法A：整盘写入，适合新U盘或可覆盖的U盘

此方法覆盖整个目标U盘，包括原STORAGE里的Kodi配置和视频；请先把需要保留的内容复制到电脑。只写外置U盘，不涉及盒子eMMC。

### Windows

1. 解压artifact ZIP，再将`*-E900V21C-USB-TEST.img.gz`解压为`.img`。
2. 在现有镜像写盘工具（例如你之前使用的Rufus）中选择目标U盘及该`.img`，以原始磁盘镜像/DD方式写入，不要把镜像作为普通文件复制到U盘。
3. 写入结束后安全弹出。Windows不能正常浏览ext4 STORAGE分区是预期现象；弹出“格式化磁盘”时取消，不格式化，也不重新分区。
4. 盒子断电时插入U盘，再通电；本机此前已启用外置启动，无需再次线刷或修改eMMC。

### macOS命令行

先在电脑上解压，路径替换为自己下载的实际文件：

```sh
gzip -dk '/实际路径/CoreELEC-...-E900V21C-USB-TEST.img.gz'
diskutil list external physical
```

根据型号和容量确认目标U盘的**整盘编号**。下面的`diskN`只是占位符，必须替换；不要选择系统盘或其分区：

```sh
diskutil unmountDisk /dev/diskN
sudo dd if='/实际路径/CoreELEC-...-E900V21C-USB-TEST.img' \
  of=/dev/rdiskN bs=4m
sync
diskutil eject /dev/diskN
```

macOS的dd运行中可按Ctrl-T查看进度。写完后同样不需要让电脑识别STORAGE；盒子启动后会使用它。

## 4. 方法B：保留现有分区和/storage，只更新FAT文件

适合当前已能启动CE、包含SYSTEM214/278等旧试验文件的U盘。**在盒子断电后取下U盘，在电脑上离线复制**，不要覆盖正在运行的SYSTEM文件，也不要运行中拔出根盘。

### 4.1 先把新镜像的FAT内容取出来

macOS可只读挂载解压后的`.img`：

```sh
hdiutil attach -readonly -nobrowse '/实际路径/CoreELEC-...-E900V21C-USB-TEST.img'
```

记录输出的虚拟磁盘编号及FAT挂载路径，例如`/Volumes/COREELEC 1`；编号和名字以实际输出为准。Linux分区无需挂载。若电脑提示无法识别另一分区，不要初始化。

Windows可用能够读取分区磁盘镜像的工具提取**第1个FAT分区**；如果工具不能读取，使用方法A写到另一只空U盘后从FAT分区复制，不要把整个`.img`改名为SYSTEM。

### 4.2 备份与空间

* 把现有U盘FAT根目录完整备份到电脑，包含三个启动脚本和它们引用的内核/SYSTEM/DTB/initrd。备份不要仍放在同一个FAT分区里占空间。
* 确认现有两个分区卷标仍是COREELEC、STORAGE。保留分区表和STORAGE不动。
* 新文件典型合计约200–230MiB，复制前建议FAT至少空出250MiB；以本次实际文件大小为准。放不下新旧两套时，可在电脑备份完成后移走旧试验文件，故障时离线还原。不要只恢复旧脚本却已经删掉它引用的旧payload。

### 4.3 同一构建的文件成套复制，脚本最后更新

从新镜像FAT根目录复制以下文件到现有U盘FAT根目录：

1. `e900-Image`、`e900-uInitrd`、`dtb.img`、`SYSTEM`。
2. `kernel.img`，以及新镜像中对应的`kernel.img.md5`、`SYSTEM.md5`（如存在），一并保持一致；不要用旧容器搭配新摘要。
3. **最后**复制`aml_autoscript`、`s905_autoscript`、`cfgload`三份脚本，避免根目录仍由旧脚本选择SYSTEM278等旧文件。

数据文件必须来自同一个USB-TEST镜像。导出的裸Image和DTB虽然可用于诊断，但不能替代缺失的配套SYSTEM/initramfs。

macOS示例，两个目录必须按实际挂载路径填写；源目录必须是新镜像，目标目录必须是物理U盘：

```sh
src='/Volumes/COREELEC 1'  # 新镜像，只读
dst='/Volumes/COREELEC'    # 物理U盘

cp "$src/e900-Image" "$src/e900-uInitrd" "$src/dtb.img" "$src/SYSTEM" "$dst/"
cp "$src/kernel.img" "$dst/"
for name in kernel.img.md5 SYSTEM.md5; do
  if [ -f "$src/$name" ]; then cp "$src/$name" "$dst/"; fi
done
cp "$src/aml_autoscript" "$src/s905_autoscript" "$src/cfgload" "$dst/"
sync
```

这里使用新镜像原始标准文件名，不再需要自己生成带编号的脚本。现有Image277/SYSTEM214等文件即使保留，也不会被新标准脚本选中。

复制结束，安全弹出物理U盘；对挂载的新镜像执行`hdiutil detach /dev/diskM`（用其实际虚拟磁盘编号），再把U盘插回断电的盒子通电。

## 5. 首次启动与网络日志

从路由器或SSH确认盒子地址；旧地址是192.168.31.11，但不能保证每次不变。SSH进入后先查看：

```sh
cat /proc/cmdline
cat /sys/module/amvideo/parameters/gxlx2_hw_init_wait
cat /sys/module/amvideo/parameters/gxlx2_hw_init_status
```

应有wait=1，对应参数读取Y、状态1。若仍显示`BOOT_IMAGE=e900-Image278 SYSTEM_IMAGE=SYSTEM278`，说明还在用旧自定义脚本；先解决脚本选择，不要触发测试。新标准脚本没有这两个带编号的选择参数。

网络工具源码在本地仓库`e900-port/scripts/`，当前artifact**没有打包这三个脚本**，需另行上传。Mac上执行：

```sh
python3 e900-port/scripts/receive-netconsole.py \
  --output /Users/lql/Downloads/e900-netconsole.log

# 下面命令另开终端执行；BOX_IP替换为盒子地址。
ssh root@BOX_IP 'mkdir -p /storage/e900-netconsole'
scp e900-port/scripts/arm-netconsole.py e900-port/scripts/release-video-init.sh \
  root@BOX_IP:/storage/e900-netconsole/
```

盒子上配置Mac的实际局域网IP和MAC：

```sh
python3 /storage/e900-netconsole/arm-netconsole.py \
  --receiver-ip MAC_IP --receiver-mac MAC_ADDRESS
```

只有Mac收到`E900_NETCONSOLE_READY`，才在盒子执行：

```sh
sh /storage/e900-netconsole/release-video-init.sh
```

这会停止Kodi、确认无解码任务后触发一次配置；成功才恢复Kodi。不能收到READY就不要释放。完整机制与观测边界见[网络诊断说明](NETCONSOLE-INIT-DIAGNOSTICS.md)。

## 6. 回退

* 方法A：使用写盘前保存的完整备份或已知可启动镜像重新写盘；不要用新旧版本的内核/模块混搭。
* 方法B：断电取盘，在电脑上还原之前备份的FAT文件及三份脚本。若使用Image277/SYSTEM214等带编号的回退组，确认其全部引用文件也在根目录。STORAGE可以保留。
* 需要先回安卓时：断电、拔U盘、再通电，使用现有eMMC安卓启动路径；本项目USB部署没有写eMMC。

如果菜单可用但视频黑屏，属于后续显示验证；如果根本没有SSH，或出现mount_sysroot/SYSTEM错误，先检查配套文件、脚本选择和FAT空间，不继续触发初始化。
