#!/usr/bin/env bash

# Check if we are root
if [ "$(id -u)" != "0" ]; then
    echo mkimg: "This script must be run as root" 1>&2
    exit 1
fi

USE_RELEASE="https://github.com/josephernest/SamplerBox/releases/download/2022-08-10-release/samplerbox_20220810.zip"
RELEASE_FILE_NAME="$(basename $USE_RELEASE)"

OUTPUT="samplerbox"

# Get dir of this script and cd into it
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_DIR="$SCRIPT_DIR/.."
NAME_OF_SCRIPT_DIR="$(basename $SCRIPT_DIR)"

TMP_IMG_DIR="/tmp/samplerbox_mkimg"
boot_dir="$TMP_IMG_DIR/boot"
rootfs_dir="$TMP_IMG_DIR/rootfs"
root_home_dir="$rootfs_dir/root"
systemd_system_dir="$rootfs_dir/etc/systemd/system"
systemd_service_files="$(find $systemd_service_dir -type f -name "*.service" | sed 's|./root||g' | tr '\n' ' ')"

DEFAULT_SB_ROOT_PWD="root"
DEFAULT_DOCKERPI_SSH_PORT=5022
QEMU_BOOT_TIMEOUT=180

# Check if required tools are installed

if ! [ -x "$(command -v unzip)" ]; then
    echo mkimg: "Error: unzip is not installed." >&2
    exit 1
fi

if ! [ -x "$(command -v kpartx)" ]; then
    echo mkimg: "Error: kpartx is not installed." >&2
    exit 1
fi

if ! [ -x "$(command -v wget)" ]; then
    echo mkimg: "Error: wget is not installed." >&2
    exit 1
fi

if ! [ -x "$(command -v rsync)" ]; then
    echo mkimg: "Error: rsync is not installed." >&2
    exit 1
fi

if ! [ -x "$(command -v docker)" ]; then
    echo mkimg: "Error: docker is not installed." >&2
    exit 1
fi

if ! [ -x "$(command -v sshpass)" ]; then
    echo mkimg: "Error: sshpass is not installed." >&2
    exit 1
fi

cd $SCRIPT_DIR

# Download samplerbox release

# Check if file already exists
if [ -f $RELEASE_FILE_NAME ]; then
    echo "mkimg: $RELEASE_FILE_NAME already exists"
    echo "mkimg: Skipping download"
else
    echo "mkimg: Downloading $RELEASE_FILE_NAME"
    wget $USE_RELEASE
    chmod 777 $RELEASE_FILE_NAME
fi

if [ -f $OUTPUT.img ]; then
    echo "mkimg: Removing old $OUTPUT.img"
    rm $OUTPUT.img
    if [ $? -eq 0 ]; then
        echo "mkimg: Removed old $OUTPUT.img"
    else
        echo "mkimg: Failed to remove old $OUTPUT.img"
        exit 1
    fi
fi

if [ -d $TMP_IMG_DIR ]; then
    echo "mkimg: $TMP_IMG_DIR already exists"
    echo "mkimg: Removing $TMP_IMG_DIR"
    umount $boot_dir > /dev/null 2>&1
    umount $rootfs_dir > /dev/null 2>&1
    kpartx -d *.img > /dev/null 2>&1
    rm -r $TMP_IMG_DIR
    if [ $? -eq 0 ]; then
        echo "mkimg: Removed $TMP_IMG_DIR"
    else
        echo "mkimg: Failed to remove $TMP_IMG_DIR"
        exit 1
    fi
fi

echo "mkimg: Unzipping $RELEASE_FILE_NAME to $TMP_IMG_DIR"

# Unzip file and cd into directory
unzip -o $RELEASE_FILE_NAME -d $TMP_IMG_DIR
if [ $? -eq 0 ]; then
    echo "mkimg: Unzipped $RELEASE_FILE_NAME"
else
    echo "mkimg: Failed to unzip $RELEASE_FILE_NAME"
    exit 1
fi

cd $TMP_IMG_DIR

# Get loop dev that will be used for mounting the image
loop_dev="$(kpartx -l *.img | grep -oP 'loop[0-9]+p[0-9]+')"
loop_dev=($loop_dev)

# Create mappings for image
kpartx -av *.img > /dev/null 2>&1

if [ $? -eq 0 ]; then
    echo "mkimg: Mappings created"
else
    echo "mkimg: Failed to create mappings"
    exit 1
fi

# Mount image
mkdir -p $boot_dir
mkdir -p $rootfs_dir

mount -o loop /dev/mapper/${loop_dev[0]} $boot_dir

if [ $? -eq 0 ]; then
    echo "mkimg: Mounted boot partition: $boot_dir"
else
    echo "mkimg: Failed to mount boot partition"
    exit 1
fi

mount -o loop /dev/mapper/${loop_dev[1]} $rootfs_dir

if [ $? -eq 0 ]; then
    echo "mkimg: Mounted root partition: $rootfs_dir"
else
    echo "mkimg: Failed to mount root partition"
    exit 1
fi

# Do stuff with the image

echo "mkimg: Copying boot files..."
cp -v -r $SCRIPT_DIR/root/boot/* $boot_dir

if [ $? -eq 0 ]; then
    echo "mkimg: Copied boot files"
else
    echo "mkimg: Failed to copy boot files"
    exit 1
fi

echo "mkimg: Copying root files..."
cp -v -r $SCRIPT_DIR/root/etc/* $rootfs_dir/etc

if [ $? -ne 0 ]; then
    echo "mkimg: Failed to copy root files"
    exit 1
fi

cp -r $SCRIPT_DIR/root/root/* $root_home_dir

if [ $? -eq 0 ]; then
    echo "mkimg: Copied root files"
else
    echo "mkimg: Failed to copy root files"
    exit 1
fi

echo "mkimg: Copying SamplerBox files..."

if [ -d $root_home_dir/SamplerBox ]; then
    echo "mkimg: Removing old SamplerBox files"
    rm -r $root_home_dir/SamplerBox
    if [ $? -eq 0 ]; then
        echo "mkimg: Removed old SamplerBox files"
    else
        echo "mkimg: Failed to remove old SamplerBox files"
        exit 1
    fi
fi

mkdir -p $root_home_dir/SamplerBox
rsync -av --exclude="*.zip" --exclude="*.img" $REPO_DIR/* $root_home_dir/SamplerBox
cp -r -v $REPO_DIR/.git* $root_home_dir/SamplerBox

if [ $? -eq 0 ]; then
    echo "mkimg: Copied new SamplerBox files"
else
    echo "mkimg: Failed to copy SamplerBox files"
    exit 1
fi

# Unmount image
umount $boot_dir

if [ $? -eq 0 ]; then
    echo "mkimg: Unmounted boot dir"
else
    echo "mkimg: Failed to unmount boot dir"
    exit 1
fi

umount $rootfs_dir

if [ $? -eq 0 ]; then
    echo "mkimg: Unmounted root dir"
else
    echo "mkimg: Failed to unmount root dir"
    exit 1
fi

# Remove mappings
kpartx -d $TMP_IMG_DIR/*.img

# Run image in qemu
mv $TMP_IMG_DIR/*.img $TMP_IMG_DIR/filesystem.img

docker run -p 5022:5022 -d -v $TMP_IMG_DIR:/sdcard lukechilds/dockerpi:vm
QEMU_CONTAINER=$(docker ps -q -f ancestor=lukechilds/dockerpi:vm)

if [ $? -eq 0 ]; then
    echo "mkimg: Started QEMU container"
else
    echo "mkimg: Failed to start QEMU container"
    exit 1
fi

# Wait for QEMU to start

echo "mkimg: Waiting for QEMU to start, this could take while..."
i=0
while ! sshpass -p "$DEFAULT_SB_ROOT_PWD" ssh -o StrictHostKeyChecking=no -p $DEFAULT_DOCKERPI_SSH_PORT root@localhost exit > /dev/null 2>&1; do
    sleep 1
    i=$((i+1))
    if [ $i -gt $QEMU_BOOT_TIMEOUT ]; then
        echo "mkimg: Attempt to connect to QEMU timed out"
        docker stop $QEMU_CONTAINER
        exit 1
    fi
done

echo "mkimg: QEMU started! Mounting rootfs as read-write..."
sshpass -p "$DEFAULT_SB_ROOT_PWD" ssh -o StrictHostKeyChecking=no -p $DEFAULT_DOCKERPI_SSH_PORT root@localhost \
    "mount -o remount,rw /"

if [ $? -eq 0 ]; then
    echo "mkimg: Mounted rootfs as read-write"
else
    echo "mkimg: Failed to mount rootfs as read-write"
    docker stop $QEMU_CONTAINER
    exit 1
fi

echo "mkimg: Downloading and/or upgrading necessary apt packages..."

sshpass -p "$DEFAULT_SB_ROOT_PWD" ssh -o StrictHostKeyChecking=no -p $DEFAULT_DOCKERPI_SSH_PORT root@localhost \
    "apt-get update && \
     apt-get install -y git python3 python3-pip python3-smbus python3-numpy python3-gpiozero libportaudio2"

if [ $? -eq 0 ]; then
    echo "mkimg: Downloaded and/or upgraded apt packages"
else
    echo "mkimg: Failed to download and/or upgrade apt packages"
    docker stop $QEMU_CONTAINER
    exit 1
fi

echo "mkimg: Installing or upgrading SamplerBox python modules..."
sshpass -p "$DEFAULT_SB_ROOT_PWD" ssh -o StrictHostKeyChecking=no -p $DEFAULT_DOCKERPI_SSH_PORT root@localhost \
    "pip3 install --upgrade cython rtmidi-python cffi sounddevice pyserial inputexec zerorpc"

if [ $? -eq 0 ]; then
    echo "mkimg: Installed or upgraded SamplerBox python modules"
else
    echo "mkimg: Failed to install or upgrade SamplerBox python modules"
    docker stop $QEMU_CONTAINER
    exit 1
fi

echo "mkimg: Building SamplerBox cpython modules..."
sshpass -p "$DEFAULT_SB_ROOT_PWD" ssh -o StrictHostKeyChecking=no -p $DEFAULT_DOCKERPI_SSH_PORT root@localhost \
    "cd /root/SamplerBox && python3 setup.py build_ext --inplace"

if [ $? -eq 0 ]; then
    echo "mkimg: Built SamplerBox cpython modules"
else
    echo "mkimg: Failed to build SamplerBox cpython modules"
    docker stop $QEMU_CONTAINER
    exit 1
fi

echo "mkimg: Reloading systemd and re-enabling SamplerBox service..."

sshpass -p "$DEFAULT_SB_ROOT_PWD" ssh -o StrictHostKeyChecking=no -p $DEFAULT_DOCKERPI_SSH_PORT root@localhost \
    "systemctl daemon-reload && systemctl reenable $systemd_service_files"

if [ $? -eq 0 ]; then
    echo "mkimg: Reloaded systemd and re-enabled SamplerBox service"
else
    echo "mkimg: Failed to reload systemd and re-enable SamplerBox service"
    docker stop $QEMU_CONTAINER
    exit 1
fi

echo "mkimg: Stopping QEMU container..."
sshpass -p "$DEFAULT_SB_ROOT_PWD" ssh -o StrictHostKeyChecking=no -p $DEFAULT_DOCKERPI_SSH_PORT root@localhost "poweroff"
sleep 10
docker stop $QEMU_CONTAINER

# Move image to script dir

chmod 777 $TMP_IMG_DIR/filesystem.img
mv $TMP_IMG_DIR/filesystem.img $SCRIPT_DIR/$OUTPUT.img

if [ $? -eq 0 ]; then
    echo "mkimg: Done! The new image can be found at $SCRIPT_DIR/samplerbox.img"
else
    echo "mkimg: Failed to move image to $SCRIPT_DIR"
    exit 1
fi

# Remove temp dir
rm -r $TMP_IMG_DIR
