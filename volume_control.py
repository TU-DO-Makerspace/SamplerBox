import sys
import os
import zerorpc
from config import *
from gpiozero import LED
from evdev.ecodes import *
from evdev import ecodes as e
from evdev import InputDevice
from evdev.events import KeyEvent

INC_VOL_BY = 10
CARD_CH = 2

vol = 50

mute_led = LED(GPIO_MUTE_LED)

def amixer_set_volume(v):
	global vol
	vol = v
	os.popen('amixer -c' + str(CARD_CH) + ' set PCM,0 ' + str(vol) + '%')

def amixer_increase_volume(p):
	global vol
	vol += p
	if vol > 100:
		vol = 100
	os.popen('amixer -c' + str(CARD_CH) + ' set PCM,0 ' + str(vol) + '%')

def amixer_decrease_volume(p):
	global vol
	vol -= p
	if vol < 0:
		vol = 0
	os.popen('amixer -c' + str(CARD_CH) + ' set PCM,0 ' + str(vol) + '%')

def amixer_muted():
	return os.popen('amixer -c' + str(CARD_CH) + ' get PCM,0').read().find('[off]') != -1

def amixer_toggle_mute():
	os.popen('amixer -c' + str(CARD_CH) + ' set PCM,0 toggle')
	ret = amixer_muted()

double_7seg = zerorpc.Client()
ret = double_7seg.connect("tcp://127.0.0.1:4242")
display_initialized = True
if len(ret) == 0:
	display_initialized = False
	print("Failed to connect to display server")

def double_7seg_display_volume():
	global vol
	global display_initialized

	if not display_initialized:
		return
	
	show = vol
	if vol > 99:
		show = 99

	try:
		double_7seg.set_layer2_n(show, 3)
	except:
		print("Failed to connect to display server")
		display_initialized = False
		pass

dev = InputDevice('/dev/input/event0')
dev.grab()

mute_led.value = amixer_muted()

amixer_set_volume(50)

for event in dev.read_loop():
	if event.type == e.EV_KEY and event.value == KeyEvent.key_down:
		if event.code == e.KEY_VOLUMEUP:
			amixer_increase_volume(INC_VOL_BY)
			double_7seg_display_volume()
		elif event.code == e.KEY_VOLUMEDOWN:
			amixer_decrease_volume(INC_VOL_BY)
			double_7seg_display_volume()
		elif event.code == e.KEY_MUTE:
			amixer_toggle_mute()
			mute_led.value = amixer_muted()