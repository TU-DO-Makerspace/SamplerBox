#
#  SamplerBox
#
#  author:    Joseph Ernest (twitter: @JosephErnest, mail: contact@samplerbox.org)
#  url:       http://www.samplerbox.org/
#  license:   Creative Commons ShareAlike 3.0 (http://creativecommons.org/licenses/by-sa/3.0/)
#
#  samplerbox.py: Main file (now requiring at least Python 3.7)
#

#########################################
# IMPORT
# MODULES
#########################################

from config import *
import wave
import time
import numpy
import os
import sys
import re
import sounddevice
import threading
from chunk import Chunk
import struct
import rtmidi_python as rtmidi
import samplerbox_audio

#########################################
# SLIGHT MODIFICATION OF PYTHON'S WAVE MODULE
# TO READ CUE MARKERS & LOOP MARKERS
#########################################

class waveread(wave.Wave_read):
    def initfp(self, file):
        self._convert = None
        self._soundpos = 0
        self._cue = []
        self._loops = []
        self._ieee = False
        self._file = Chunk(file, bigendian=0)
        if self._file.getname() != b'RIFF':
            raise IOError('file does not start with RIFF id')
        if self._file.read(4) != b'WAVE':
            raise IOError('not a WAVE file')
        self._fmt_chunk_read = 0
        self._data_chunk = None
        while 1:
            self._data_seek_needed = 1
            try:
                chunk = Chunk(self._file, bigendian=0)
            except EOFError:
                break
            chunkname = chunk.getname()
            if chunkname == b'fmt ':
                self._read_fmt_chunk(chunk)
                self._fmt_chunk_read = 1
            elif chunkname == b'data':
                if not self._fmt_chunk_read:
                    raise IOError('data chunk before fmt chunk')
                self._data_chunk = chunk
                self._nframes = chunk.chunksize // self._framesize
                self._data_seek_needed = 0
            elif chunkname == b'cue ':
                numcue = struct.unpack('<i', chunk.read(4))[0]
                for i in range(numcue):
                    id, position, datachunkid, chunkstart, blockstart, sampleoffset = struct.unpack('<iiiiii', chunk.read(24))
                    self._cue.append(sampleoffset)
            elif chunkname == b'smpl':
                manuf, prod, sampleperiod, midiunitynote, midipitchfraction, smptefmt, smpteoffs, numsampleloops, samplerdata = struct.unpack(
                    '<iiiiiiiii', chunk.read(36))
                for i in range(numsampleloops):
                    cuepointid, type, start, end, fraction, playcount = struct.unpack('<iiiiii', chunk.read(24))
                    self._loops.append([start, end])
            chunk.skip()
        if not self._fmt_chunk_read or not self._data_chunk:
            raise IOError('fmt chunk and/or data chunk missing')

    def getmarkers(self):
        return self._cue

    def getloops(self):
        return self._loops

#########################################
# MIXER CLASSES
#
#########################################

class PlayingSound:
    def __init__(self, sound, note):
        self.sound = sound
        self.pos = 0
        self.fadeoutpos = 0
        self.isfadeout = False
        self.note = note

    def fadeout(self, i):
        self.isfadeout = True

    def stop(self):
        try:
            playingsounds.remove(self)
        except:
            pass

class Sound:
    def __init__(self, filename, midinote, velocity):
        wf = waveread(filename)
        self.fname = filename
        self.midinote = midinote
        self.velocity = velocity
        if wf.getloops():
            self.loop = wf.getloops()[0][0]
            self.nframes = wf.getloops()[0][1] + 2
        else:
            self.loop = -1
            self.nframes = wf.getnframes()
        self.data = self.frames2array(wf.readframes(self.nframes), wf.getsampwidth(), wf.getnchannels())
        wf.close()

    def play(self, note):
        snd = PlayingSound(self, note)
        playingsounds.append(snd)
        return snd

    def frames2array(self, data, sampwidth, numchan):
        if sampwidth == 2:
            npdata = numpy.frombuffer(data, dtype=numpy.int16)
        elif sampwidth == 3:
            npdata = samplerbox_audio.binary24_to_int16(data, len(data)//3)
        if numchan == 1:
            npdata = numpy.repeat(npdata, 2)
        return npdata

FADEOUTLENGTH = 30000
FADEOUT = numpy.linspace(1., 0., FADEOUTLENGTH)            # by default, float64
FADEOUT = numpy.power(FADEOUT, 6)
FADEOUT = numpy.append(FADEOUT, numpy.zeros(FADEOUTLENGTH, numpy.float32)).astype(numpy.float32)
SPEED = numpy.power(2, numpy.arange(0.0, 84.0)/12).astype(numpy.float32)

samples = {}
playingnotes = {}
sustainplayingnotes = []
sustain = False
playingsounds = []
globalvolume = 10 ** (-12.0/20)  # -12dB default global volume
globaltranspose = 0

#########################################
# 2x 7-SEGMENT DISPLAY
#
#########################################

if USE_DOUBLE_7SEGMENT_DISPLAY:
    import zerorpc

    class Double7Segment(object):
        def __init__(self):
            self.init_success = False
            self.display_client = zerorpc.Client()
            ret = self.display_client.connect("tcp://127.0.0.1:4242")
            if len(ret) > 0:
                self.init_success = True
            else:
                print("WARNING: Could not connect to display server")


        # Permanently display a number on the 7-segment display
        def displayNumber(self, n:int):
            if not self.init_success:
                return
            self.display_client.set_layer1_n(n)

        # Permanently display 2 characters on the 7-segment display
        def display2Chars(self, s:str):
            if not self.init_success:
                return
            self.display_client.set_layer1_2c(s)

        # Display a number for a given time on the 7-segment display
        # After the time has passed, the previous permanent display 
        # is restored
        def displayNumberTemporary(self, n:int, t:int):
            if not self.init_success:
                return
            self.display_client.set_layer2_n(n, t)

        # Display 2 characters for a given time on the 7-segment display
        # After the time has passed, the previous permanent display
        # is restored
        def display2CharsTemporary(self, s:str, t:int):
            if not self.init_success:
                return
            self.display_client.set_layer2_2c(s, t)

else:
    
    class Double7Segment(object):
        def __init__(self):
            pass

        def display2Chars(self, s:str):
            pass

        def displayNumber(self, s:str):
            pass

#########################################
# AUDIO AND MIDI CALLBACKS
#
#########################################

def AudioCallback(outdata, frame_count, time_info, status):
    global playingsounds
    rmlist = []
    playingsounds = playingsounds[-MAX_POLYPHONY:]
    b = samplerbox_audio.mixaudiobuffers(playingsounds, rmlist, frame_count, FADEOUT, FADEOUTLENGTH, SPEED)
    for e in rmlist:
        try:
            playingsounds.remove(e)
        except:
            pass
    b *= globalvolume
    outdata[:] = b.reshape(outdata.shape)

def MidiCallback(message, time_stamp):
    global playingnotes, sustain, sustainplayingnotes
    global preset
    messagetype = message[0] >> 4
    messagechannel = (message[0] & 15) + 1
    note = message[1] if len(message) > 1 else None
    midinote = note
    velocity = message[2] if len(message) > 2 else None
    if messagetype == 9 and velocity == 0:
        messagetype = 8
    if messagetype == 9:    # Note on
        midinote += globaltranspose
        try:
            playingnotes.setdefault(midinote, []).append(samples[midinote, velocity].play(midinote))
        except:
            pass
    elif messagetype == 8:  # Note off
        midinote += globaltranspose
        if midinote in playingnotes:
            for n in playingnotes[midinote]:
                if sustain:
                    sustainplayingnotes.append(n)
                else:
                    n.fadeout(50)
            playingnotes[midinote] = []
    elif messagetype == 12:  # Program change
        print('Program change ' + str(note))
        preset = note
        LoadSamples()
    elif (messagetype == 11) and (note == 64) and (velocity < 64):  # sustain pedal off
        for n in sustainplayingnotes:
            n.fadeout(50)
        sustainplayingnotes = []
        sustain = False
    elif (messagetype == 11) and (note == 64) and (velocity >= 64):  # sustain pedal on
        sustain = True

#########################################
# LOAD SAMPLES
#
#########################################

LoadingThread = None
LoadingInterrupt = False

def LoadSamples():
    global LoadingThread
    global LoadingInterrupt

    if LoadingThread:
        LoadingInterrupt = True
        LoadingThread.join()
        LoadingThread = None

    LoadingInterrupt = False
    LoadingThread = threading.Thread(target=ActuallyLoad)
    LoadingThread.daemon = True
    LoadingThread.start()

NOTES = ["c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b"]

def ActuallyLoad():
    global preset
    global samples
    global playingsounds
    global globalvolume, globaltranspose
    playingsounds = []
    samples = {}
    globalvolume = 10 ** (-12.0/20)  # -12dB default global volume
    globaltranspose = 0
    double_7seg = Double7Segment()
    samplesdir = SAMPLES_DIR if os.listdir(SAMPLES_DIR) else '.'      # use current folder (containing 0 Saw) if no user media containing samples has been found
    basename = next((f for f in os.listdir(samplesdir) if f.startswith("%d " % preset)), None)      # or next(glob.iglob("blah*"), None)
    if basename:
        dirname = os.path.join(samplesdir, basename)
    if not basename:
        print('Preset empty: %s' % preset)
        double_7seg.display2CharsTemporary("EP", 1)
        double_7seg.displayNumber(preset)
        return
    print('Preset loading: %s (%s)' % (preset, basename))
    double_7seg.display2Chars("LO")
    definitionfname = os.path.join(dirname, "definition.txt")
    if os.path.isfile(definitionfname):
        with open(definitionfname, 'r') as definitionfile:
            for i, pattern in enumerate(definitionfile):
                try:
                    if r'%%volume' in pattern:        # %%paramaters are global parameters
                        globalvolume *= 10 ** (float(pattern.split('=')[1].strip()) / 20)
                        continue
                    if r'%%transpose' in pattern:
                        globaltranspose = int(pattern.split('=')[1].strip())
                        continue
                    defaultparams = {'midinote': '0', 'velocity': '127', 'notename': ''}
                    if len(pattern.split(',')) > 1:
                        defaultparams.update(dict([item.split('=') for item in pattern.split(',', 1)[1].replace(' ', '').replace('%', '').split(',')]))
                    pattern = pattern.split(',')[0]
                    pattern = re.escape(pattern.strip())  # note for Python 3.7+: "%" is no longer escaped with "\"
                    pattern = pattern.replace(r"%midinote", r"(?P<midinote>\d+)").replace(r"%velocity", r"(?P<velocity>\d+)")\
                                     .replace(r"%notename", r"(?P<notename>[A-Ga-g]#?[0-9])").replace(r"\*", r".*?").strip()    # .*? => non greedy
                    for fname in os.listdir(dirname):
                        if LoadingInterrupt:
                            return
                        m = re.match(pattern, fname)
                        if m:
                            info = m.groupdict()
                            midinote = int(info.get('midinote', defaultparams['midinote']))
                            velocity = int(info.get('velocity', defaultparams['velocity']))
                            notename = info.get('notename', defaultparams['notename'])
                            if notename:
                                midinote = NOTES.index(notename[:-1].lower()) + (int(notename[-1])+2) * 12
                            samples[midinote, velocity] = Sound(os.path.join(dirname, fname), midinote, velocity)
                except:
                    print("Error in definition file, skipping line %s." % (i+1))
    else:
        for midinote in range(0, 127):
            if LoadingInterrupt:
                return
            file = os.path.join(dirname, "%d.wav" % midinote)
            if os.path.isfile(file):
                samples[midinote, 127] = Sound(file, midinote, 127)
    initial_keys = set(samples.keys())
    for midinote in range(128):
        lastvelocity = None
        for velocity in range(128):
            if (midinote, velocity) not in initial_keys:
                samples[midinote, velocity] = lastvelocity
            else:
                if not lastvelocity:
                    for v in range(velocity):
                        samples[midinote, v] = samples[midinote, velocity]
                lastvelocity = samples[midinote, velocity]
        if not lastvelocity:
            for velocity in range(128):
                try:
                    samples[midinote, velocity] = samples[midinote-1, velocity]
                except:
                    pass
    if len(initial_keys) > 0:
        print('Preset loaded: ' + str(preset))
    else:
        print('Preset empty: ' + str(preset))
        double_7seg.display2CharsTemporary("EP", 1)
    double_7seg.displayNumber(preset)

#########################################
# OPEN AUDIO DEVICE
#
#########################################

try:
    sd = sounddevice.OutputStream(device=AUDIO_DEVICE_ID, blocksize=512, samplerate=44100, channels=2, dtype='int16', callback=AudioCallback)
    sd.start()
    print('Opened audio device #%i' % AUDIO_DEVICE_ID)
except:
    print('Invalid audio device #%i' % AUDIO_DEVICE_ID)
    exit(1)

#########################################
# BUTTONS THREAD (RASPBERRY PI GPIO)
#
#########################################

if USE_BUTTONS:
    import RPi.GPIO as GPIO
    DEBOUNCE_TIME = 0.2  # seconds

    def IncPreset():
        global preset
        preset += 1
        if preset > MAX_PRESETS:
            preset = 0
        LoadSamples()

    def DecPreset():
        global preset
        preset -= 1
        if preset < 0:
            preset = MAX_PRESETS
        LoadSamples()

    # Handle button presses.
    def HandleButtons():
        last_button_time = 0
        while True:
            now = time.time()

            currently_debouncing = (now - last_button_time) < DEBOUNCE_TIME

            if not currently_debouncing:
                if not GPIO.input(BUTTON_PREV):
                    last_button_time = now
                    DecPreset()
                elif not GPIO.input(BUTTON_NEXT):
                    last_button_time = now
                    IncPreset()
            
            time.sleep(0.02)

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(BUTTON_PREV, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(BUTTON_NEXT, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    ButtonsThread = threading.Thread(target=HandleButtons)
    ButtonsThread.daemon = True
    ButtonsThread.start()

#########################################
# MIDI IN via SERIAL PORT
#
#########################################

if USE_SERIALPORT_MIDI:
    import serial

    # Open serial port
    ser = serial.Serial('/dev/serial0', baudrate=38400)
    # NOTE: Although the serial port here is opened with 38400 baud, it's a hack and actually runs at 31250 baud.
    #       This hack requires to also "underclock" the UART0 peripheral clock in /boot/config.tx and .boot/cmdline.txt
    #       See     : https://www.raspberrypi.org/forums/viewtopic.php?t=161577
    #       And/Or  : http://m0xpd.blogspot.com/2013/01/midi-controller-on-rpi.html
    #
    #       Providing a baudrate of 31250 does not work, as the Pi serial driver does not officially support this
    #       baudrate. Attempting to do so will deliver some jankey data when attempting to read MIDI messages over
    #       the serial port.

    # Constants for MIDI messages
    MIDI_MSG_N_BYTES = 3        # Number of bytes in a MIDI message
    I_MIDI_MSG_STATUS_BYTE = 0  # Index of the status byte in a MIDI message
    I_MIDI_MSG_DATA_BYTE_1 = 1  # Index of the first data byte in a MIDI message
    I_MIDI_MSG_DATA_BYTE_2 = 2  # Index of the second data byte in a MIDI message
    MIDI_MSG_PORG_CHANGE = 12   # Status byte value for program change messages

    def MidiSerialReader():
        message = [0, 0, 0]
        
        while True:
            i = 0
            while i < MIDI_MSG_N_BYTES:
                data = ord(ser.read(1))  # read a byte
                
                # Check for beginning of a MIDI message
                is_status = data >> 7 != 0
                if is_status:
                    i = I_MIDI_MSG_STATUS_BYTE
                
                message[i] = data
                
                # Check for program change message
                # If detected, ignore the second data byte as
                # it is not required for program change messages
                prog_change_detected = (i == I_MIDI_MSG_DATA_BYTE_1 and 
                                        message[I_MIDI_MSG_STATUS_BYTE] >> 4 == MIDI_MSG_PORG_CHANGE)
                
                if prog_change_detected:
                    message[I_MIDI_MSG_DATA_BYTE_2] = 0
                    break

                i += 1
                    
            MidiCallback(message, None)
    
    MidiThread = threading.Thread(target=MidiSerialReader)
    MidiThread.daemon = True
    MidiThread.start()

#########################################
# LOAD FIRST SOUNDBANK
#
#########################################

preset = 0
LoadSamples()

#########################################
# SYSTEM LED
#
#########################################
if USE_SYSTEMLED:
    os.system("modprobe ledtrig_heartbeat")
    os.system("echo heartbeat >/sys/class/leds/led0/trigger")

#########################################
# MIDI DEVICES DETECTION
# MAIN LOOP
#########################################

midi_in_scanner = rtmidi.MidiIn(b'in')  # Continuously scans for new MIDI devices
midi_in_listeners = []                  # List of MIDI input listeners
evaluated_ports = []                    # List of ports that have already been evaluated

# Check if the '--boot' flag was passed as an argument. If so, we discard MIDI
# input the first few seconds.
# 
# Due to some unknown reason, when samplerbox is executed as a systemd service
# after boot, it can sometimes read unwanted data from the MIDI device, causing
# a random program change to be interpreted. I'm not entirely sure why this happens,
# but adding a 'sleep' call in the service file also does not seem to help. It's
# possible that the unwanted data is perhaps being queued up?

if len(sys.argv) > 1 and sys.argv[1] == '--boot':
    ignore_midi_for_seconds = IGNORE_MIDI_AFTER_BOOT_FOR_SECONDS
else:
    ignore_midi_for_seconds = 0

# Main loop
# ---------
# This loop continuously scans for new MIDI devices 
# and opens them as they are detected.
# It also ensures that the program runs indefinitely
# and doesn't terminate
#
while True:
    current_ports = midi_in_scanner.ports
    new_ports = set(current_ports) - set(evaluated_ports) # List of new

    # Iterate over the new ports and open each one
    for port in new_ports:

        # Ignore the 'Midi Through' port, as it's a virtual port that is created
        if b'Midi Through' not in port:
            midi_in = rtmidi.MidiIn(b'in')
            midi_in.open_port(port)

            # Ignore MIDI input for a few seconds after boot
            now = time.time()
            while time.time() < now + ignore_midi_for_seconds:
                midi_in[-1].get_message()

            midi_in.callback = MidiCallback     # Callback for incoming MIDI messages
            midi_in_listeners.append(midi_in)   # Add to list of MIDI input listeners
            print('Opened MIDI: ' + str(port))

    evaluated_ports = current_ports # Update list of evaluated ports
    time.sleep(2)