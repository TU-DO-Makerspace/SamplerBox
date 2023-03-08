#########################################
# LOCAL
# CONFIG
#########################################

AUDIO_DEVICE_ID = 2                     # change this number to use another soundcard
SAMPLES_DIR = "/media/"                 # The root directory containing the sample-sets. Example: "/media/" to look for samples on a USB stick / SD card
IGNORE_MIDI_AFTER_BOOT_FOR_SECONDS = 2  # Discard MIDI messages for provided seconds after boot to work-around garbage MIDI messages on boot
MAX_POLYPHONY = 80                      # This can be set higher, but 80 is a safe value
USE_BUTTONS = False                     # Set to True to use momentary buttons (connected to RaspberryPi's GPIO pins) to change preset
USE_I2C_7SEGMENTDISPLAY = False         # Set to True to use a 7-segment display via I2C
USE_SERIALPORT_MIDI = True              # Set to True to enable MIDI IN via SerialPort (e.g. RaspberryPi's GPIO UART pins)
USE_SYSTEMLED = True                    # Flashing LED after successful boot, only works on RPi/Linux