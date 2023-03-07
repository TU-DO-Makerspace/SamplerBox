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
root_dir="$TMP_IMG_DIR/root"

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
    umount $boot_dir || /bin/true
    umount $root_dir || /bin/true
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
mkdir -p $root_dir

mount -o loop /dev/mapper/${loop_dev[0]} $boot_dir

if [ $? -eq 0 ]; then
    echo "mkimg: Mounted boot partition: $boot_dir"
else
    echo "mkimg: Failed to mount boot partition"
    exit 1
fi

mount -o loop /dev/mapper/${loop_dev[1]} $root_dir

if [ $? -eq 0 ]; then
    echo "mkimg: Mounted root partition: $root_dir"
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
cp -v -r $SCRIPT_DIR/root/etc/* $root_dir/etc

if [ $? -ne 0 ]; then
    echo "mkimg: Failed to copy root files"
    exit 1
fi

cp -r $SCRIPT_DIR/root/root/* $root_dir

if [ $? -eq 0 ]; then
    echo "mkimg: Copied root files"
else
    echo "mkimg: Failed to copy root files"
    exit 1
fi

echo "mkimg: Copying SamplerBox files..."

mkdir -p $root_dir/root/SamplerBox
rsync -av --exclude="$NAME_OF_SCRIPT_DIR" $REPO_DIR/* $root_dir/root/SamplerBox

if [ $? -eq 0 ]; then
    echo "mkimg: Copied SamplerBox files"
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

umount $root_dir

if [ $? -eq 0 ]; then
    echo "mkimg: Unmounted root dir"
else
    echo "mkimg: Failed to unmount root dir"
    exit 1
fi

# Remove mappings
kpartx -d $TMP_IMG_DIR/*.img > /dev/null 2>&1

# Move image to script dir

chmod 777 *.img
mv $TMP_IMG_DIR/*.img $SCRIPT_DIR/$OUTPUT.img

if [ $? -eq 0 ]; then
    echo "mkimg: Done! The new image can be found at $SCRIPT_DIR/samplerbox.img"
else
    echo "mkimg: Failed to move image to $SCRIPT_DIR"
    exit 1
fi

# Remove temp dir
rm -r $TMP_IMG_DIR
