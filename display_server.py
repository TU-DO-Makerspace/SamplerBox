import zerorpc
import time
import gevent
from gpiozero import LEDCharDisplay
from display_server_config import *

class DisplayServer(object):
	def __init__(self):
		self._initialized = False
		
		# Layer 1
		self._layer1_val = None

		# Layer 2
		self._layer2_val = None		
		self._layer2_tstamp = None

		self._seg1 = LEDCharDisplay(*GPIOS_7SEGMENT_DISPLAY_1, active_high = GPIOS_7SEGMENT_DISPLAY_1_ACTIVE_HIGH)
		self._seg2 = LEDCharDisplay(*GPIOS_7SEGMENT_DISPLAY_2, active_high = GPIOS_7SEGMENT_DISPLAY_2_ACTIVE_HIGH)
		
		self._seg1.on()
		self._seg2.on()

		self._initialized = True

	def _num_val_to_2c(self, val: int):
		if val < 10:
			return '0' + str(val)
		elif val > 99:
			return 'XX'
		else:
			return str(val)

	def _str_val_to_2c(self, val: str):
		if len(val) == 1:
			return val + ' '
		elif len(val) == 2:
			return val
		else:
			return 'XX'

	def initialized(self):
		return self._initialized
	
	def set_layer1_n(self, val: int):
		if not self._initialized:
			return
		self._layer1_val = self._num_val_to_2c(val)

	def set_layer1_2c(self, s: str):
		if not self._initialized:
			return
		self._layer1_val = self._str_val_to_2c(s)

	def set_layer2_n(self, val: int, duration_s: int):
		if not self._initialized:
			return
		self._layer2_val = self._num_val_to_2c(val)
		self._layer2_tstamp = time.time() + duration_s

	def set_layer2_2c(self, s: str, duration_s: int):
		if not self._initialized:
			return
		self._layer2_val = self._str_val_to_2c(s)
		self._layer2_tstamp = time.time() + duration_s

	def _display(self, val):
		if val == None:
			self._seg1.off()
			self._seg2.off()
			return
		
		if val[0] == ' ':
			self._seg1.off()
		else:
			self._seg1.value = val[0]
		
		if val[1] == ' ':
			self._seg2.off()
		else:
			self._seg2.value = val[1]

	def _update(self):
		if self._layer2_tstamp != None:
			if time.time() < self._layer2_tstamp:
				self._display(self._layer2_val)
				return
			else:
				self._layer2_tstamp = None
		
		self._display(self._layer1_val)

	def _run(self):
		while True:
			self._update()
			gevent.sleep(0)

display_server = DisplayServer()
s = zerorpc.Server(display_server)
s.bind("tcp://127.0.0.1:4242")

gevent.joinall([
	gevent.spawn(s.run),
	gevent.spawn(display_server._run)
])