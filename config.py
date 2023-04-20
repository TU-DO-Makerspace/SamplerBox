#########################################
# LOCAL
# CONFIG
#########################################

TARGET_PLATFORM = "LINUX"                   # The target device to run on. Possible values: "RPI", "LINUX"
AUDIO_DEVICE_ID = 7                     # The ID of the audio device to use. 
					# 1 = Systems default device which will automatically switch to the USB audio device when connected
					# See https://python-sounddevice.readthedocs.io/en/0.4.6/api/checking-hardware.html

SAMPLES_DIR = "/media/patrick/SAMPLES/"                 # The root directory containing the sample-sets.
					# Example: "/media/" to look for samples on a USB stick / SD card
					
IGNORE_MIDI_AFTER_BOOT_FOR_SECONDS = 2  # Discard MIDI messages for provided seconds after boot to work-around garbage MIDI messages on boot
MAX_POLYPHONY = 80                      # This can be set higher, but 80 is a safe value
MAX_PRESETS = 99                        # The maximum number of presets to load (99 as the 7-segment display only has 2 digits)
USE_BUTTONS = False                     # Set to True to use momentary buttons (connected to RaspberryPi's GPIO pins) to change preset
BUTTON_PREV = 18                        # The GPIO pin to use for the previous preset button
BUTTON_NEXT = 17                        # The GPIO pin to use for the next preset button
USE_DOUBLE_7SEGMENT_DISPLAY = False      # Set to True to use a double 7-segment display (connected to RaspberryPi's GPIO pins)
USE_SERIALPORT_MIDI = False              # Set to True to enable MIDI IN via SerialPort (e.g. RaspberryPi's GPIO UART pins)
USE_MUTE_LED = False                     # Set to True to use a LED to indicate mute status (connected to RaspberryPi's GPIO pins)
GPIO_MUTE_LED = 17                      # The GPIO pin to use for the mute LED
USE_SYSTEMLED = False                    # Flashing LED after successful boot, only works on RPi/Linux