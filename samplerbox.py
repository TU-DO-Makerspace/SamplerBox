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

samples = [{}, {}, {}]
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

    if TARGET_PLATFORM != "RPI":
        print("ERROR: Double 7-segment display is only supported on Raspberry Pi")
        sys.exit(1)

    import zerorpc

# The display server is used to allow multiple processes to access the display
# simultaneously, in our case samplerbox.py and volume_control.py. The display is
# composed of two layers:
#
# Layer 1: Symbols displayed on this layer are always visible unless Layer 2
#          is active. This layer should be used for symbols that are generally
#          useful to the user. Currently, it is only used to display the current
#          preset number.
#          
#          Functions that write to Layer 1 are:
#           - displayNumber(n)
#           - display2Chars(s)
#
# Layer 2: Symbols displayed on this layer are temporary and are displayed
#          on top of the symbols on Layer 1. They can only be displayed for a
#          limited time, after which the display reverts to Layer 1. This layer
#          should be used for symbols that need to be displayed temporarily,
#          such as the new volume level after the volume has been changed, or
#          to indicate if a preset is empty.
# 
#          Functions that write to Layer 2 are:
#           - displayNumberTemporary(n, t)
#           - display2CharsTemporary(s, t)

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

        def display2CharsTemporary(self, s:str, t:int):
            pass

        def displayNumberTemporary(self, s:str, t:int):
            pass

#########################################
# AUDIO CALLBACK
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

#########################################
# MIDI
#
#########################################

## Constants for MIDI messages

# Size and indices of MIDI messages
MIDI_MSG_N_BYTES = 3        # Number of bytes in a MIDI message
I_MIDI_MSG_STATUS_BYTE = 0  # Index of the status byte in a MIDI message
I_MIDI_MSG_DATA_BYTE_1 = 1  # Index of the first data byte in a MIDI message
I_MIDI_MSG_DATA_BYTE_2 = 2  # Index of the second data byte in a MIDI message

# Status byte values
MIDI_MSG_NOTE_OFF = 8       # Status byte value for note off messages
MIDI_MSG_NOTE_ON = 9        # Status byte value for note on messages
MIDI_MSG_CC = 11            # Status byte value for sustain messages
MIDI_MSG_PORG_CHANGE = 12   # Status byte value for program change messages

# CC messages (provided in data byte 1) 
MIDI_CC_MSG_SUSTAIN = 64    # CC message for sustain pedal

def MidiCallback(message, time_stamp):
    global playingnotes, sustain, sustainplayingnotes
    global preset
    
    status = message[I_MIDI_MSG_STATUS_BYTE] >> 4
    channel = (message[I_MIDI_MSG_STATUS_BYTE] & 15) + 1
    data1 = message[I_MIDI_MSG_DATA_BYTE_1] if len(message) > 1 else None
    data2 = message[I_MIDI_MSG_DATA_BYTE_2] if len(message) > 2 else None

    # Note ON/OFF messages
    if status == MIDI_MSG_NOTE_ON or status == MIDI_MSG_NOTE_OFF:
        midinote = data1 + globaltranspose
        velocity = data2

        # Note ON and velocity > 0
        if status == MIDI_MSG_NOTE_ON and velocity > 0:
            try:
                # 
                playingnotes.setdefault(midinote, []).append(samples[channel - 1][midinote, velocity].play(midinote))
            except:
                pass
        
        # Note OFF or Note ON with velocity = 0 
        else:
            if not midinote in playingnotes:
                return
            
            # If sustain pedal is on, then sustain all notes
            # referenced by the midinote by adding them to the
            # sustainplayingnotes list. Otherwise, fade out all
            # notes referenced by the midinote.
            for n in playingnotes[midinote]:
                if sustain:
                    sustainplayingnotes.append(n)
                else:
                    n.fadeout(50)
            
            playingnotes[midinote] = []

    # Program change message
    elif status == MIDI_MSG_PORG_CHANGE:
        programnumber = data1
        print('Program change ' + str(programnumber))
        preset[selectedchannel] = programnumber
        LoadSamples()
        
    # Sustain pedal message
    elif status == MIDI_MSG_CC and data1 == MIDI_CC_MSG_SUSTAIN:
        # Sustain pedal on (data2 >= 64)
        if data2 >= 64:
            sustain = True

        # Sustain pedal off (data2 <= 63)
        else:
            for n in sustainplayingnotes:
                n.fadeout(50)
            sustainplayingnotes = []
            sustain = False

## MIDI IN via SERIAL PORT
if USE_SERIALPORT_MIDI:

    if TARGET_PLATFORM != "RPI":
        print("ERROR: Serial port MIDI is only supported on Raspberry Pi")
        exit(1)

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
# LOAD SAMPLES
#
#########################################

LoadingThread = [None, None, None]
LoadingInterrupt = [False, False, False]

def LoadSamples():
    global LoadingThread
    global LoadingInterrupt
    global selectedchannel

    if LoadingThread[selectedchannel]:
        LoadingInterrupt[selectedchannel] = True
        LoadingThread[selectedchannel].join()
        LoadingThread[selectedchannel] = None

    LoadingInterrupt[selectedchannel] = False
    LoadingThread[selectedchannel] = threading.Thread(target=ActuallyLoad, args=(selectedchannel,))
    LoadingThread[selectedchannel].daemon = True
    LoadingThread[selectedchannel].start()

NOTES = ["c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b"]

def ActuallyLoad(channel):
    
    global preset
    global samples
    global playingsounds
    global globalvolume, globaltranspose

    playingsounds = []               # stop all sounds
    samples[channel] = {}                     # clear samples
    globalvolume = 10 ** (-12.0/20)  # -12dB default global volume
    globaltranspose = 0              # no transpose by default
    double_7seg = Double7Segment()   # init 7-segment display (Must be seperately initialized for each thread)

    # Find directory containing samples for the current preset
    # The directory name must start with the preset number followed by a space
    # Ex: 0 saw, 1 piano, 2 drums, etc.
    samplesdir = SAMPLES_DIR if os.listdir(SAMPLES_DIR) else '.'                                    # use current folder (containing 0 Saw) if no user media containing samples has been found
    basename = next((f for f in os.listdir(samplesdir) if f.startswith("%d " % preset[channel])), None)      # find directory starting with preset number followed by a space
    
    # Report no directory could be found for the current preset
    if basename:
        presetpath = os.path.join(samplesdir, basename)
    else:
        print('Preset empty: %s (CH %s)' % (preset[channel], channel + 1))
        double_7seg.display2CharsTemporary("EP", 1)
        double_7seg.displayNumber(preset[channel])
        return
   
    print('Preset loading: %s (CH %s) (%s)' % (preset[channel], channel + 1, basename))
    double_7seg.display2Chars("LO")
    definitionfile = os.path.join(presetpath, "definition.txt")
    
    # Load and parse the definition.txt file
    if os.path.isfile(definitionfile):
        with open(definitionfile, 'r') as definitionfile:
            for i, pattern in enumerate(definitionfile):
                try:
                    # Parse parameters starting with "%%"
                    # These are treated as global parameters
                    #
                    # Possible parameters:
                    #   volume: global volume in dB
                    #   transpose: global transpose in semitones
                    #
                    # Example: %%volume=-12
                    if r'%%volume' in pattern:
                        globalvolume *= 10 ** (float(pattern.split('=')[1].strip()) / 20) # convert dB to linear
                        continue
                    if r'%%transpose' in pattern:
                        globaltranspose = int(pattern.split('=')[1].strip())
                        continue

                    # Evaluate sample specific patterns
                    #
                    # The syntax for a sample specific pattern is:
                    #  <filepattern>, %<parameter1>=<value1>, %<parameter2>=<value2>, ...
                    # 
                    # If a parameter is not specified, the default value will be used.
                    #
                    # Possible parameters are:
                    #   midinote (Default 0)    : MIDI note to which the sample will be assigned
                    #
                    #   velocity (Default 127)  : MIDI velocity to which the sample will be assigned,
                    #                             Undefined Lower and higher velocities will be interpolated
                    #                             (See loop for "# Fill in/transpose missing samples" below)
                    #
                    #   notename (Default '')   : Note name to which the sample will be assigned, this may be 
                    #                             used instead of midinote
                    #
                    # For Example:
                    #   bruh.wav, %midinote=60, %velocity=100
                    # 
                    # Will load the sample bruh.wav at midinote 60 and velocity 100.
                    #
                    # Altough somewhat confusing, the parameters may also
                    # be used as file patterns to match filenames.
                    #
                    # For Example:
                    #  %drum%midinote.wav, %velocity=100
                    #
                    # Will match all files that contain "drum" followed by midinote number, and
                    # load them at their corresponding midi number with velocity 100.
                    # 
                    # File patterns can also be combined.

                    sampleparams = {'midinote': '0', 'velocity': '127', 'notename': ''} # default parameters

                    # Check if line overrides default parameters
                    # If so, update sampleparams with the provided parameters
                    if len(pattern.split(',')) > 1:
                        sampleparams.update(dict([item.split('=') for item in pattern.split(',', 1)[1].replace(' ', '').replace('%', '').split(',')]))
                    
                    # Get pattern to match filenames targeted by the filepattern
                    filepattern = pattern.split(',')[0]
                    filepattern = re.escape(filepattern.strip())  # note for Python 3.7+: "%" is no longer escaped with "\"
                    filepattern_re = filepattern.replace(r"%midinote", r"(?P<midinote>\d+)").replace(r"%velocity", r"(?P<velocity>\d+)")\
                                     .replace(r"%notename", r"(?P<notename>[A-Ga-g]#?[0-9])").replace(r"\*", r".*?").strip()    # .*? => non greedy
                    
                    for fname in os.listdir(presetpath):
                        # Check if loading has been interrupted
                        # by a new preset being selected
                        if LoadingInterrupt[channel]:
                            return
                        
                        # Check if filename matches filepattern
                        m = re.match(filepattern_re, fname)
                        
                        if m:
                            # If filename contains midinote or notename, use it
                            # Otherwise use the the parameters provided by the
                            # sampleparams dictionary (Either default or from
                            # overrides the definition file)
                            info = m.groupdict()
                            midinote = int(info.get('midinote', sampleparams['midinote']))
                            velocity = int(info.get('velocity', sampleparams['velocity']))
                            notename = info.get('notename', sampleparams['notename'])
                            
                            if notename:
                                midinote = NOTES.index(notename[:-1].lower()) + (int(notename[-1])+2) * 12
                            
                            # Load sample at the specified midinote and velocity
                            samples[channel][midinote, velocity] = Sound(os.path.join(presetpath, fname), midinote, velocity)
                except Exception as e:
                    print("Error in definition file, skipping line %s." % (i+1))
    else:
        # No definition file found
        # Load samples with filenames matching the midinote
        # Ex: 0.wav, 1.wav, 2.wav, etc.
        for midinote in range(0, 127):
            if LoadingInterrupt[channel]:
                return
            
            file = os.path.join(presetpath, "%d.wav" % midinote)
           
            if os.path.isfile(file):
                samples[channel][midinote, 127] = Sound(file, midinote, 127)
    
    initial_keys = set(samples[channel].keys())

    # Fill in/transpose missing samples
    for midinote in range(128):
        lastvelocity = None

        # Copies/Transposes defined samples to missing
        # velocities
        #
        # All undefined velocities that are smaller than the first defined velocity
        # get the value of the first defined velocity.
        # For example, suppose that a sample is defined at samples[60, 100], 
        # but all samples at samples[60, 0-99] are missing. In this case,
        # the sample at samples[60, 100] is copied to samples[60, 0-99].
        # 
        # After that, all undefined velocities that are larger than the last defined velocity
        # get the value of the last defined velocity.
        # For example, suppose that a sample is defined at samples[60, 100],
        # but all samples at samples[60, 101-127] are missing. In this case,
        # the sample at samples[60, 100] is copied to samples[60, 101-127].
        #
        for velocity in range(128):
            if (midinote, velocity) not in initial_keys:
                samples[channel][midinote, velocity] = lastvelocity
            else:
                if not lastvelocity:
                    for v in range(velocity):
                        samples[channel][midinote, v] = samples[channel][midinote, velocity]
                lastvelocity = samples[channel][midinote, velocity]

        # No defined velocity was found for this note,
        # I.e this happens if no sample file was providedfor this note.
        #
        # Try to copy the sample from the previous midinote!
        # NOTE: This means all samples before the first defined sample
        # will remain blank (silence).
        if not lastvelocity:
            for velocity in range(128):
                try:
                    samples[channel][midinote, velocity] = samples[channel][midinote-1, velocity]
                except:
                    pass
    
    # Report if preset is empty
    if len(initial_keys) > 0:
        print('CH' + str(channel + 1) + ': Preset loaded: ' + str(preset[channel]))
    else:
        print('CH' + str(channel + 1) + ': Preset empty: ' + str(preset[channel]))
        double_7seg.display2CharsTemporary("EP", 1)

    double_7seg.displayNumber(preset[channel])

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
    if TARGET_PLATFORM != "RPI":
        print("Buttons are only supported on Raspberry Pi!")
        exit(1)

    import RPi.GPIO as GPIO
    DEBOUNCE_TIME = 0.2  # seconds

    def IncPreset():
        global preset
        global selectedchannel
        preset[selectedchannel] += 1
        if preset[selectedchannel] > MAX_PRESETS:
            preset[selectedchannel] = 0
        LoadSamples()

    def DecPreset():
        global preset
        global selectedchannel
        preset[selectedchannel] -= 1
        if preset[selectedchannel] < 0:
            preset[selectedchannel] = MAX_PRESETS
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
# MIDI CHANNEL SELECTION FOR PRESETS
#
#########################################

if USE_MULTIPLE_MIDI_CHANNELS:
    if TARGET_PLATFORM != "RPI":
        print("Multiple MIDI channels are only supported on Raspberry Pi!")
        exit(1)

    def HandleMidiChannelSelection():
        global selectedchannel
        
        double_7seg = Double7Segment()
        lastselectedchannel = selectedchannel
        
        while True:
            if not GPIO.input(MIDI_CH_SELECT_SWITCH_LEFT) and GPIO.input(MIDI_CH_SELECT_SWITCH_RIGHT):
                selectedchannel = 0
            if not GPIO.input(MIDI_CH_SELECT_SWITCH_LEFT) and not GPIO.input(MIDI_CH_SELECT_SWITCH_RIGHT):
                selectedchannel = 1
            else:
                selectedchannel = 2

            if selectedchannel != lastselectedchannel:
                double_7seg.displayNumber(preset[selectedchannel])
                lastselectedchannel = selectedchannel
                print("Selected MIDI channel: " + str(selectedchannel+1))
            
            time.sleep(0.02)

    GPIO.setup(MIDI_CH_SELECT_SWITCH_LEFT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(MIDI_CH_SELECT_SWITCH_RIGHT, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    MidiChannelSelectionThread = threading.Thread(target=HandleMidiChannelSelection)
    MidiChannelSelectionThread.daemon = True
    MidiChannelSelectionThread.start()

#########################################
# LOAD FIRST SOUNDBANK
#
#########################################

preset = [0, 0, 0]

for i in range(len(samples)):
    selectedchannel = i
    LoadSamples()

selectedchannel = 0 # MIDI channel 1

#########################################
# SYSTEM LED
#
#########################################
if USE_SYSTEMLED:
    if TARGET_PLATFORM != "RPI":
        print("System LED is only supported on Raspberry Pi!")
        exit(1)

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