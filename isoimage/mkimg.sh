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
systemd_service_files="$(cd $SCRIPT_DIR/root && find -type f -name "*.service" | sed 's|^\.||g' | tr '\n' ' ')"

DEFAULT_SB_ROOT_PWD="root"
DEFAULT_DOCKERPI_SSH_PORT=5022
QEMU_BOOT_TIMEOUT=180

function help {
    echo "Usage: mkimg.sh [OPTION]"
    echo "Create a Raspberry Pi image with SamplerBox"
    echo ""
    echo "Options:"
    echo "  --help, -h"
    echo "      Show this help message"
    echo "  --install-ubuntu-deps"
    echo "      Install dependencies for Ubuntu"
    echo ""
    echo "Examples:"
    echo "  mkimg.sh"
    echo "      Create a Raspberry Pi image with SamplerBox"
    echo "  mkimg.sh --install-ubuntu-deps"
    echo "      Install dependencies for Ubuntu"
}

function cleanup {
    _ret=true

    echo "mkimg: Cleaning up..."
    if [ -d $TMP_IMG_DIR ]; then
        umount $boot_dir > /dev/null 2>&1
        umount $rootfs_dir > /dev/null 2>&1
        kpartx -d *.img > /dev/null 2>&1
        rm -rf $TMP_IMG_DIR

        if [ $? -ne 0 ]; then
            echo "mkimg: Failed to remove $TMP_IMG_DIR"
            _ret=false
        fi
    fi

    if [ -f $OUTPUT.img ]; then
        rm $OUTPUT.img
        if [ $? -ne 0 ]; then
            echo "mkimg: Failed to remove $OUTPUT.img"
            _ret=false
        fi
    fi

    if [ _ret ]; then
        echo "mkimg: Cleaned up"
    else
        echo "mkimg: Failed to clean up"
    fi
}

function cleanup_and_exit {
    cleanup
    exit $1
}

## Check if --install-ubuntu-deps was passed

if [ "$1" == "-h" ] || [ "$1" == "--help" ]; then
    help
    exit 0
elif [ "$1" == "--install-ubuntu-deps" ]; then
    echo "mkimg: Installing dependencies for Ubuntu"
    apt-get update

    if ! [ -x "$(command -v docker)" ]; then
        echo "mkimg: Docker is not installed, adding official docker repository..."
        echo "mkimg: Installing docker..."
        apt-get install apt-transport-https ca-certificates curl software-properties-common
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        apt-get update
    fi

    echo "mkimg: Installing apt dependencies..."
    apt-get install -y unzip kpartx wget rsync sshpass docker-ce

    if [ $? -ne 0 ]; then
        echo "mkimg: Failed to install dependencies"
        exit 1
    fi

    echo "mkimg: Installed dependencies"
    exit 0
elif [ ! -z "$1" ]; then
    echo "mkimg: Unknown argument: $1"
    help
    exit 1
fi

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

cleanup

echo "mkimg: Unzipping $RELEASE_FILE_NAME to $TMP_IMG_DIR..."

# Unzip file and cd into directory
unzip -o $RELEASE_FILE_NAME -d $TMP_IMG_DIR
if [ $? -eq 0 ]; then
    echo "mkimg: Unzipped $RELEASE_FILE_NAME"
else
    echo "mkimg: Failed to unzip $RELEASE_FILE_NAME"
    cleanup_and_exit 1
fi

cd $TMP_IMG_DIR

# Get loop dev that will be used for mounting the image
loop_dev="$(kpartx -l *.img | grep -oP 'loop[0-9]+p[0-9]+')"
loop_dev=($loop_dev)

# Create mappings for image
echo "mkimg: Creating /dev/loop mappings for image..."
kpartx -av *.img > /dev/null

if [ $? -eq 0 ]; then
    echo "mkimg: Mappings created"
else
    echo "mkimg: Failed to create mappings"
    cleanup_and_exit 1
fi

# Mount image
echo "mkimg: Mounting image..."
mkdir -p $boot_dir
mkdir -p $rootfs_dir

mount -o loop /dev/mapper/${loop_dev[0]} $boot_dir

if [ $? -eq 0 ]; then
    echo "mkimg: Mounted boot partition: $boot_dir"
else
    echo "mkimg: Failed to mount boot partition"
    cleanup_and_exit 1
fi

mount -o loop /dev/mapper/${loop_dev[1]} $rootfs_dir

if [ $? -eq 0 ]; then
    echo "mkimg: Mounted root partition: $rootfs_dir"
else
    echo "mkimg: Failed to mount root partition"
    cleanup_and_exit 1
fi

# Do stuff with the image

echo "mkimg: Copying boot files..."
cp -v -r $SCRIPT_DIR/root/boot/. $boot_dir

if [ $? -eq 0 ]; then
    echo "mkimg: Copied boot files"
else
    echo "mkimg: Failed to copy boot files"
    cleanup_and_exit 1
fi

echo "mkimg: Copying root files..."
cp -v -r $SCRIPT_DIR/root/etc/. $rootfs_dir/etc/

if [ $? -ne 0 ]; then
    echo "mkimg: Failed to copy root files"
    cleanup_and_exit 1
fi

cp -r $SCRIPT_DIR/root/root/. $root_home_dir/

if [ $? -eq 0 ]; then
    echo "mkimg: Copied root files"
else
    echo "mkimg: Failed to copy root files"
    cleanup_and_exit 1
fi

echo "mkimg: Copying SamplerBox files..."

if [ -d $root_home_dir/SamplerBox ]; then
    echo "mkimg: Removing old SamplerBox files"
    rm -r $root_home_dir/SamplerBox
    if [ $? -eq 0 ]; then
        echo "mkimg: Removed old SamplerBox files"
    else
        echo "mkimg: Failed to remove old SamplerBox files"
        cleanup_and_exit 1
    fi
fi

mkdir -p $root_home_dir/SamplerBox
rsync -vaC --exclude="*.zip" --exclude="*.img" $REPO_DIR/* $root_home_dir/SamplerBox

if [ $? -eq 0 ]; then
    echo "mkimg: Copied new SamplerBox files"
else
    echo "mkimg: Failed to copy SamplerBox files"
    cleanup_and_exit 1
fi

# Unmount image
echo "mkimg: Unmounting image..."
umount $boot_dir

if [ $? -eq 0 ]; then
    echo "mkimg: Unmounted boot dir"
else
    echo "mkimg: Failed to unmount boot dir"
    cleanup_and_exit 1
fi

umount $rootfs_dir

if [ $? -eq 0 ]; then
    echo "mkimg: Unmounted root dir"
else
    echo "mkimg: Failed to unmount root dir"
    cleanup_and_exit 1
fi

# Remove mappings
echo "mkimg: Removing /dev/loop mappings..."
kpartx -d $TMP_IMG_DIR/*.img
if [ $? -eq 0 ]; then
    echo "mkimg: Mappings removed"
else
    echo "mkimg: Failed to remove mappings"
    cleanup_and_exit 1
fi

# Run image in qemu
echo "mkimg: Starting QEMU container..."
mv $TMP_IMG_DIR/*.img $TMP_IMG_DIR/filesystem.img

docker run -p 5022:5022 -d -v $TMP_IMG_DIR:/sdcard lukechilds/dockerpi:vm
QEMU_CONTAINER=$(docker ps -q -f ancestor=lukechilds/dockerpi:vm)

if [ $? -eq 0 ]; then
    echo "mkimg: Started QEMU container"
else
    echo "mkimg: Failed to start QEMU container"
    cleanup_and_exit 1
fi

# Wait for QEMU to start

echo "mkimg: Waiting for the QEMU RPi VM to boot, this could take while..."
i=0
while ! sshpass -p "$DEFAULT_SB_ROOT_PWD" ssh -o StrictHostKeyChecking=no -p $DEFAULT_DOCKERPI_SSH_PORT root@localhost exit > /dev/null 2>&1; do
    sleep 1
    i=$((i+1))
    if [ $i -gt $QEMU_BOOT_TIMEOUT ]; then
        echo "mkimg: Attempt to connect to QEMU timed out"
        docker stop $QEMU_CONTAINER
        cleanup_and_exit 1
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
    cleanup_and_exit 1
fi

echo "mkimg: Downloading and/or upgrading necessary apt packages..."

sshpass -p "$DEFAULT_SB_ROOT_PWD" ssh -o StrictHostKeyChecking=no -p $DEFAULT_DOCKERPI_SSH_PORT root@localhost \
    "apt-get update && \
     apt-get install -y git python3 python3-pip python3-smbus python3-numpy python3-gpiozero python3-evdev libportaudio2"

if [ $? -eq 0 ]; then
    echo "mkimg: Downloaded and/or upgraded apt packages"
else
    echo "mkimg: Failed to download and/or upgrade apt packages"
    docker stop $QEMU_CONTAINER
    cleanup_and_exit 1
fi

echo "mkimg: Installing or upgrading SamplerBox python modules..."
sshpass -p "$DEFAULT_SB_ROOT_PWD" ssh -o StrictHostKeyChecking=no -p $DEFAULT_DOCKERPI_SSH_PORT root@localhost \
    "pip3 install --upgrade cython rtmidi-python cffi sounddevice pyserial zerorpc"

if [ $? -eq 0 ]; then
    echo "mkimg: Installed or upgraded SamplerBox python modules"
else
    echo "mkimg: Failed to install or upgrade SamplerBox python modules"
    docker stop $QEMU_CONTAINER
    cleanup_and_exit 1
fi

echo "mkimg: Building SamplerBox cpython modules..."
sshpass -p "$DEFAULT_SB_ROOT_PWD" ssh -o StrictHostKeyChecking=no -p $DEFAULT_DOCKERPI_SSH_PORT root@localhost \
    "cd /root/SamplerBox && python3 setup.py build_ext --inplace"

if [ $? -eq 0 ]; then
    echo "mkimg: Built SamplerBox cpython modules"
else
    echo "mkimg: Failed to build SamplerBox cpython modules"
    docker stop $QEMU_CONTAINER
    cleanup_and_exit 1
fi

echo "mkimg: Reloading systemd and re-enabling SamplerBox service..."

sshpass -p "$DEFAULT_SB_ROOT_PWD" ssh -o StrictHostKeyChecking=no -p $DEFAULT_DOCKERPI_SSH_PORT root@localhost \
    "systemctl daemon-reload && systemctl reenable $systemd_service_files"

if [ $? -eq 0 ]; then
    echo "mkimg: Reloaded systemd and re-enabled SamplerBox service"
else
    echo "mkimg: Failed to reload systemd and re-enable SamplerBox service"
    docker stop $QEMU_CONTAINER
    cleanup_and_exit 1
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
    cleanup_and_exit 1
fi

cleanup_and_exit 0