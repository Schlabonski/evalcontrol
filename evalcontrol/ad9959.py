import usb
import time

import numpy as np

from .customhandler import DeviceHandle

class AD9959(object):
    """This class emulates the AD9959 evaluation board for python.

    An instance of the class will construct a handler for the cypress USB
    controler. Through this handler commands can be sent to the chip and piped
    to the DDS processor.
    """
    
    def __init__(self, vid=0x0456, pid=0xee25, port_numbers=None, bus_number=None, auto_update=True,
            rfclk=50e6, clkmtp=10, channel=0):
        """Initializes a handler for the usb controler.

        If more than one AD9959 are connected via USB, they are in principle indistinguishable. The only way
        to identify them is by specifying their USB bus address.

        vid : hex
            vendor ID of the device
        pid : hex
            product ID of the device
        bus_number: int
            Bus number of the connected device to distinguish between identical devices.
        port_numbers: tuple
            Contains the port and subport numbers to distinguish between identical devices.
        refclk: float
            Reference clock frequency in Hertz.
        clkmtp: int
            Clock multiplier. The reference clock signal is internally multiplied by this value to generate
            the system clock frequency.
        """
        self.channel = channel

        # find all usb devices with matching vid/pid
        devs = list(usb.core.find(idVendor=vid, idProduct=pid, find_all=True))
        dev = None
        dev_mess = 'No devices with matching vID/pID {0}/{1} found!'.format(hex(vid), hex(pid))
        assert len(devs) > 0, dev_mess
        # if more than one AD9959 is present, decide by usb port address
        if len(devs) > 1:
            assert port_numbers is not None and bus_number is not None, 'More than one AD9959 present. Specify USB bus and port numbers!'
            for d in devs:
                if d.port_numbers == port_numbers and d.bus == bus_number:
                    dev = d
                    break
            assert dev is not None, 'No matching device was found. Check bus and port numbers!'

        else:
            dev = devs[0]

        dev.set_configuration()
        cnf = dev.configurations()[0]
        intf = cnf[(0,0)]
        self.dev = dev

        # retrieve important endpoints of usb controller
        self._ep1 = intf[0]
        self._ep81 = intf[1]
        self._ep4 = intf[3]
        self._ep88 = intf[5]

        # set default values for physical variables
        self.ref_clock_frequency = rfclk
        self.system_clock_frequency = rfclk

        # set default value for auto IO update
        self.auto_update = auto_update

        # try to access device, it might still be in use by another handler,
        #in this case, reset it
        try:
            self.set_clock_multiplier(clkmtp)
        except usb.USBError:
            self._reset_usb_handler()
            self.set_clock_multiplier(clkmtp)

    def __del__(self):
        usb.util.dispose_resources(self.dev)

    def _reset_usb_handler(self):
        """Resets the usb handler via which communication takes place.

        This method can be used to prevent USBErrors that occur when communication with the device times out
        because it is still in use by another process.
        """
        self.dev.reset()
        
    def _write_to_dds_register(self, register, word):
        """Writes a word to the given register of the dds chip.

        Any words that are supposed to be written directly to the DDS
        chip are sent to endpoint 0x04 of the microcrontroler.

        :register: hex
            ID of the target register on the DDS chip.
        :word: bytearray
            word that is written to the respective register. Each byte in
            the bytearray should be either 0x00 or 0x01.

        """
        # express the register name as a binary. Maintain the format that is
        # understood by endpoint 0x04. The first bit signifies read/write,
        # the next 7 bits specify the register
        register_bin = bin(register).lstrip('0b')
        if len(register_bin) < 7:
            register_bin = (7-len(register_bin))*'0' + register_bin

        register_bin = ''.join(' 0' + b for b in register_bin)

        # construct the full message that is sent to the endpoint
        message = '00' + register_bin  + ' ' + word
        message = bytearray.fromhex(message)

        # endpoint 0x04 will forward the word to the specified register
        with DeviceHandle(self.dev) as dh:
            dh.bulkWrite(self._ep4, message)

    def _read_from_register(self, register, size):
        """Reads a word of length `size` from `register` of the DDS chip.

        :register: hex
            register of the DDS chip from which to read
        :size: int
            length of the word (in bytes) that is read from the register
        :returns: bytearray
            the readout of the register

        """
        # convert the size to hex
        size_hex = hex(size).lstrip('0x')
        if len(size_hex) < 2:
            size_hex = '0' + size_hex

        # set the controler to readback mode
        begin_readback = bytearray.fromhex('07 00 ' + size_hex)
        with DeviceHandle(self.dev) as dh:
            dh.bulkWrite(self._ep1, begin_readback)

        # construct the command to read out the register
        register_bin = bin(register).lstrip('0b')
        if len(register_bin) < 7:
            register_bin = (7-len(register_bin))*'0' + register_bin
        register_bin = ''.join(' 0' + b for b in register_bin)
        readout_command = bytearray.fromhex('01' + register_bin)
        with DeviceHandle(self.dev) as dh:
            dh.bulkWrite(self._ep4, readout_command)
        
        time.sleep(0.1)
        # read the message from endpoint 88
        with DeviceHandle(self.dev) as dh:
            readout = dh.bulkRead(self._ep88, size=size)

        # turn off readback mode
        end_readback = bytearray.fromhex('04 00')
        with DeviceHandle(self.dev) as dh:
            dh.bulkWrite(self._ep1, end_readback)
        return readout

    def _load_IO(self):
        """Loads the I/O update line (same as GUI load function).

        """
        load_message = bytearray.fromhex('0C 00')
        with DeviceHandle(self.dev) as dh:
            dh.bulkWrite(self._ep1, load_message)
            readout = dh.bulkRead(self._ep81, 1)
        return readout

    def _update_IO(self):
        """Updates the IO to the DDS chip (same as GUI function).

        """
        update_message = bytearray.fromhex('0C 10')
        with DeviceHandle(self.dev) as dh:
            dh.bulkWrite(self._ep1, update_message)
            readout = dh.bulkRead(self._ep81, 1)
        return readout

    def set_clock_multiplier(self, factor):
        """Sets the multiplier for the reference clock.

        The system clock frequency is given by
           f_sys = multiplier * f_ref
        where f_ref is the frequency of the reference clock.

        :factor: int
            Multiplying factor between 4 and 20. A `factor` of 1 disables
            multiplication.

        """
        # in case of a factor of one, we want to disable multiplication
        if factor == 1:
            factor -= 1
            self.system_clock_frequency = self.ref_clock_frequency

        else:
            assert factor in range(4, 21), "Multiplier should be integer between 4 and 20!"
            self.system_clock_frequency = self.ref_clock_frequency * factor

        # construct the multiplier word
        multi_bin = bin(factor).lstrip('0b')
        if len(multi_bin) < 5:
            multi_bin = (5-len(multi_bin))*'0' + multi_bin

        # get the current state of function register 1
        fr1_old = self._read_from_register(0x01, 24)
        fr1_old_bitstring = ''.join(str(b) for b in fr1_old)

        # update the multiplier section of the bitstring
        fr1_new_bitstring = fr1_old_bitstring[0] + multi_bin + fr1_old_bitstring[6:]
        if self.system_clock_frequency > 255e6:
            l = list(fr1_new_bitstring)
            l[0] = '1'
            fr1_new_bitstring = ''.join(l)
            print("System clock exceeds 255MHz, VCO gain bit was set to True!")
        fr1_word = ''.join(' 0' + b for b in fr1_new_bitstring)[1:]

        # write the new multiplier to the register on dds chip
        self._write_to_dds_register(0x01, fr1_word)
        self._load_IO()
        if self.auto_update:
            self._update_IO()
    
    def _channel_select(self, channel):
        """Selects the chosen channels in the channel select register.

        :channels: int or list
            ID or list of the channel IDs to select e.g. [0,2,3]

        """
        if np.issubdtype(type(channel), np.integer):
            channels = [channel]
        else:
            channels = [c for c in channel]

        # set the channels in the channel select register
        channel_select_bin = list('0000')
        for ch in channels:
            channel_select_bin[ch] = '1'
        channel_select_bin = channel_select_bin[::-1] # we have inverse order
        channel_select_bin = ''.join(channel_select_bin)
                                                      # in the register
        csr_old = self._read_from_register(0x00, 8)
        csr_old_bin = ''.join(str(b) for b in csr_old)
        csr_new_bin = channel_select_bin[:4] + csr_old_bin[4:]

        csr_word = ''.join(' 0' + b for b in csr_new_bin)
        csr_word = csr_word[1:]

        self._write_to_dds_register(0x00, csr_word)

    def precompute_frequency_word(self, channel, frequency):
        """Precomputes a frequency tuning word for given channel(s) and frequency.
        
        The current implementation of this method is repetitive and clumsy!

        :channel:  int or list
            Channel number or list of channel numbers.
        :frequency: float
            frequency to be set on channel(s)
        :returns: bytearray, bytearray
           The message to select the channels and set the frequency word, which can both
           be sent to self._ep4

        """
        if np.issubdtype(type(channel), np.integer):
            channels = [channel]
        else:
            channels = [c for c in channel]

        # set the channels in the channel select register
        channel_select_bin = list('0000')
        for ch in channels:
            channel_select_bin[ch] = '1'
        channel_select_bin = channel_select_bin[::-1] # we have inverse order
        channel_select_bin = ''.join(channel_select_bin)
                                                      # in the register
        # preserve the information that is stored in the CSR
        csr_old = self._read_from_register(0x00, 8)
        csr_old_bin = ''.join(str(b) for b in csr_old)
        csr_new_bin = channel_select_bin[:4] + csr_old_bin[4:]

        csr_word = ''.join(' 0' + b for b in csr_new_bin)
        csr_word = csr_word[1:]
        word = csr_word

        # express the register name as a binary. Maintain the format that is
        # understood by endpoint 0x04. The first bit signifies read/write,
        # the next 7 bits specify the register
        register_bin = bin(0x00).lstrip('0b')
        if len(register_bin) < 7:
            register_bin = (7-len(register_bin))*'0' + register_bin

        register_bin = ''.join(' 0' + b for b in register_bin)

        # construct the full message that is sent to the endpoint
        message = '00' + register_bin  + ' ' + word
        message_channel_select = bytearray.fromhex(message)

        ## Now compute the same message to select the frequency
        assert frequency <= self.system_clock_frequency, ("Frequency should not"
                + " exceed system clock frequency! System clock frequency is {0}Hz".format(self.system_clock_frequency))

        # calculate the fraction of the full frequency
        fraction = frequency/self.system_clock_frequency
        fraction_bin = bin(round(fraction * (2**32 - 1))).lstrip('0b') # full range are 32 bit
        if len(fraction_bin) < 32:
            fraction_bin = (32-len(fraction_bin)) * '0' + fraction_bin
        closest_possible_value = (int(fraction_bin, base=2)/(2**32 -1) *
                                    self.system_clock_frequency)
        print('Frequency of channel {1} encoded as closest possible value {0}MHz'.format(
                                                        closest_possible_value/1e6, channel))

        # set the frequency word in the frequency register
        frequency_word = ''.join(' 0' + b for b in fraction_bin)
        frequency_word = frequency_word[1:]
        word = frequency_word

        # express the register name as a binary. Maintain the format that is
        # understood by endpoint 0x04. The first bit signifies read/write,
        # the next 7 bits specify the register
        register_bin = bin(0x04).lstrip('0b') # 0x04 = frequency register
        if len(register_bin) < 7:
            register_bin = (7-len(register_bin))*'0' + register_bin

        register_bin = ''.join(' 0' + b for b in register_bin)

        # construct the full message that is sent to the endpoint
        message = '00' + register_bin  + ' ' + word
        message_frequency_word = bytearray.fromhex(message)

        return message_channel_select, message_frequency_word

    def set_precomputed_frequency(message_channel_select, message_frequency_word):
        """This method sets the frequency from precomputed byte-encoded words.

        The input for this method should be the ouput of self.precompute_frequency_word.
        This method only send the precomputed byte arrays to enpoint 4 of the USB handler and
        thus be faster than the self.set_frequency method.

        :message_channel_select: bytearray
            The bytearray that encodes a given channel selection.

        :message_frequency_word: bytearray
            Encodes the setting of the frequency word.

        """
        with DeviceHandle(self.dev) as dh:
            dh.bulkWrite(self._ep4, message_channel_select)
            dh.bulkWrite(self._ep4, message_frequency_word)

    def set_frequency(self, frequency, channel=None, channel_word=0):
        """Sets a new frequency for a given channel.

        :frequency: float
            The new frequency in Hz. Should not exceed `system_clock_frequency`.
        :channel: int or seq
            Channel(s) for which the frequency should be set.
        :channel_word: int
            Determines the channel_word to which the frequency is written. Each channel has 16
            channel_words that can be used.

        """

        if channel is None:
            channel = self.channel
        assert frequency <= self.system_clock_frequency, ("Frequency should not"
                + " exceed system clock frequency! System clock frequency is {0}Hz".format(self.system_clock_frequency))

        assert channel_word < 16, ("Channel word cannot exceed 15, input was {0}".format(channel_word))

        # select the chosen channels
        self._channel_select(channel)

        # calculate the fraction of the full frequency
        fraction = frequency/self.system_clock_frequency
        fraction_bin = bin(int(round(fraction * (2**32 - 1)))).lstrip('0b') # full range are 32 bit
        if len(fraction_bin) < 32:
            fraction_bin = (32-len(fraction_bin)) * '0' + fraction_bin
        closest_possible_value = (int(fraction_bin, base=2)/(2**32 -1) *
                                    self.system_clock_frequency)
        print('Setting frequency of channel {1}:{2} to closest possible value {0}MHz'.format(
                                                        closest_possible_value/1e6, channel, channel_word))

        # set the frequency word in the frequency register
        frequency_word = ''.join(' 0' + b for b in fraction_bin)
        frequency_word = frequency_word[1:]
        if channel_word == 0:
            self._write_to_dds_register(0x04, frequency_word)
        else:
            register = channel_word - 1 + 0x0A
            self._write_to_dds_register(register, frequency_word)


        # load and update I/O
        self._load_IO()
        if self.auto_update:
            self._update_IO()

    def set_phase(self, phase, channel=None):
        """Sets the phase offset for a given channel.

        :phase: float
            phase in degree, 0 < `phase` < 360
        :channels: int or list
            ID or list of IDs of the selected channels

        """
        if channel is None:
            channel = self.channel
        assert 0 <= phase <= 360,  'Phase should be between 0 and 360 degree!'

        # select the channels
        self._channel_select(channel)

        # calculate the binary phase word
        phase_fraction = phase/360
        phase_fraction_bin = bin(round(phase_fraction * 2**14)).lstrip('0b')
        if len(phase_fraction_bin) < 16:
            phase_fraction_bin = (16 - len(phase_fraction_bin)) * '0' + phase_fraction_bin

        # construct the message for cypress chip
        phase_fraction_word = ''.join(' 0' + b for b in phase_fraction_bin)
        phase_fraction_word = phase_fraction_word[1:]

        # write the phase word to the register
        self._write_to_dds_register(0x05, phase_fraction_word)

        # update I/O
        self._load_IO()
        if self.auto_update:
            self._update_IO()

    def toggle_autoclear_phase_accumulations(self):
        """Switches the autoclear phase accumulation bit on and off.

        """
        # load the current channel function register setting
        cfr = self._read_from_register(0x03, 24)
        print(cfr)

        # set the autoclear phase accumulator bit to 1 if old value was 0 and
        # vice versa
        cfr[21] = (cfr[21] + 1) % 2 
        print(cfr)

        # construct the command for the cypress chip
        cfr_new_bin = ''.join(' 0'+str(b) for b in cfr)
        cfr_new_bin = cfr_new_bin[1:]
        print(cfr_new_bin)

        # write new values to register
        self._write_to_dds_register(0x03, cfr_new_bin)

        # update I/O
        self._load_IO()
        if self.auto_update:
            self._update_IO()

    def _enable_channel_modulation(self, channel=None, modulation_type='frequency', disable=False):
        """Enables frequency modulation for selected channel(s).
        :channel: int or list
            channel ID or list of channel IDs that are selected
        :modulation_type: str
            can be 'frequency', 'phase' or 'amplitude'. Only frequency is implemented so far.
        :disable: bool
            when True, modulation for this channel(s) is disabled.

        """
        if channel is None:
            channel = self.channel
        if np.issubdtype(type(channel), np.integer):
            channel = [channel]
        
        # we need to iterate over all channels, as the channel's individual function registers
        # might have different content
        for ch in channel:
            self._channel_select(ch)

            # the modulation type of the channel is encoded in register 0x03[23:22].
            # 00 disables modulation, 10 is frequency modulation.
            if not disable:
                if modulation_type == 'frequency':
                    modulation_type_bin = '10'
            else:
                modulation_type_bin = '00'

            # 1. read the old CFR content
            cfr_old = self._read_from_register(0x03, 24)
            cfr_old_bin = ''.join(str(b) for b in cfr_old)

            # 2. replace the modulation type
            cfr_new_bin = modulation_type_bin + cfr_old_bin[2:]
            
            cfr_word_new = ''.join(' 0' + b for b in cfr_new_bin)
            cfr_word_new = cfr_word_new[1:]

            self._write_to_dds_register(0x03, cfr_word_new)

            self._load_IO()
            if self.auto_update:
                self._update_IO()

    def enable_modulation(self, level=2, active_channels=None, modulation_type='frequency'):
        """This method chooses the modulation level and type.

        :level: int
            Can be either 2, 4 or 16. The level determines the number of registers from
            which active channels can choose.
        :active_channels: int or list
            In 4- and 16-level modulation this determines which channels can be modulated.
            Note that as there is only a 4 bit input (P0-P3), in 4-level modulation only 2 channels
            can be modulated, in 16-level modulation only one.
        :modulation_type: str
            'frequency', 'amplitude' or 'phase'

        """
        if active_channels is None:
            active_channels = self.channel
        if np.issubdtype(type(active_channels), np.integer):
            active_channels = [active_channels]
        active_channels.sort()

        # 1. get the current content of (global) function register 1
        fr_old = self._read_from_register(0x01, 24)
        fr_old_bin = ''.join(str(b) for b in fr_old)

        # 2. set the modulation level
        level_bin = '00'
        if level == 4:
            level_bin = '01'
        elif level == 16:
            level_bin = '11'
        # 3. replace the old level
        fr_new_level = fr_old_bin[:14] + level_bin + fr_old_bin[16:]

        # 3.1 if the level is 4 or 16, also the PPC bits need to be updated
        if level != 2:
            # mappings are taken from the manual of the AD9959
            if level == 4:
                configurations = [[0,1], [0,2], [0,3], [1,2], [1,3], [2,3]]
                ppcs_combinations = [bin(i)[2:] for i in range(6)]

            elif level == 16:
                configurations = [[i] for i in range(4)]
                ppcs_combinations = [bin(i)[2:] for i in range(4)]

            i = configurations.index(active_channels)
            PPC_bin = ppcs_combinations[i]
            if len(PPC_bin) < 3:
                PPC_bin = '0' * (3 - len(PPC_bin)) + PPC_bin

            # update PPC word
            fr_new_level = fr_new_level[:9] + PPC_bin + fr_new_level[12:]
        
        # write the new FR1 word to the register
        fr_new_word = ''.join(' 0' + b for b in fr_new_level)
        fr_new_word = fr_new_word[1:]
        #return fr_new_word, fr_new_level

        self._write_to_dds_register(0x01, fr_new_word)
        
        self._load_IO()
        if self.auto_update:
            self._update_IO()

        # we also make sure that the active channels are in correct modulation mode
        for ch in active_channels:
            self._enable_channel_modulation(channel=ch, modulation_type=modulation_type)

    def _enable_channel_linear_sweep(self, channels=None, disable=False):
        """TODO: Docstring for _enable_channel_linear_sweep.

        :channel: int or list
            channel ID or list of channel IDs that are selected
        :disable: bool
            when True, modulation for this channel(s) is disabled.

        """
        if channels is None:
            channels = self.channel
        if np.issubdtype(type(channels), np.integer):
            channels = [channels]
        
        # the modulation type of the channel is encoded in CFR 0x03[14].
        # 0 disables linear sweep, 1 enables
        if not disable:
            ls_enable_bin = '1'
        else:
            ls_enable_bin = '0'

        # we need to iterate over all channels, as the channel's individual function registers
        # might have different content
        for ch in channels:
            self._channel_select(ch)

            # 1. read the old CFR content
            cfr_old = self._read_from_register(0x03, 24)
            cfr_old_bin = ''.join(str(b) for b in cfr_old)

            # 2. replace the CFR by one with updated LS enable bit
            cfr_new_bin = cfr_old_bin[:9] + ls_enable_bin + cfr_old_bin[10:]
            
            cfr_word_new = ''.join(' 0' + b for b in cfr_new_bin) # translate to bytes
            cfr_word_new = cfr_word_new[1:] # crop the first white space

            self._write_to_dds_register(0x03, cfr_word_new)

            self._load_IO()
            if self.auto_update:
                self._update_IO()

            # print summary message
            mes = ['Disabled', 'Enabled'][int(ls_enable_bin)]
            mes += ' linear sweep for channel {0}.'.format(ch)
            print(mes)
            print(cfr_old_bin, len(cfr_old_bin))
            print(cfr_new_bin, len(cfr_new_bin))

        return

    def configure_linear_sweep(self, channels=None, rsrr=0, fsrr=0, rdw=0, fdw=0, disable=False):
        """Configure the linear frequency sweep parameters for selected channels.

        The linear sweep ramp rate (lsrr) specifies the timestep of the rising ramp, falling sweep ramp rate
        (fsrr) works accordingly.
        Rising delta word specifies the rising frequency stepsize, falling delta works respectively.

        :channels: int or list
            Channel ID(s) for channels to configure.
        :lsrr: float
            Timestep (in seconds) of the rising sweep. Can be 1-256 times the inverse SYNC_CLK frequency.
            SYNC_CLK frequency is the SYSCLK divided by 4.
        :fsrr: float
            Same as :lsrr:
        :rdw: float
            Frequency step (in Hertz) of the rising sweep. Can be chosen similar to the channel frequency.
        :fdw: float
            Same as :rdw:
        :disable: bool
            If True, disable linear sweep for selected channels.
        :returns: TODO

        """
        if channels is None:
            channels = self.channel
        if np.issubdtype(type(channels), np.integer):
            channels = [channels]
        channels.sort()

        # If desired, disable selected channels and return.
        self._enable_channel_linear_sweep(channels, disable=disable)
        if disable:
            return

        # All linear sweep properties are in individual channel registers, so we
        # can write all channels in one go
        self._channel_select(channels)

        ######################################################
        # 1. Set the new falling and rising sweep ramp rate
        ramp_rate_word = ''
        rr_name = ['Falling', 'Rising']
        for i, rr in enumerate([fsrr, rsrr]):
            # 1.1 Compute RR word in binary
            rr_time_step = 4/self.system_clock_frequency
            fraction_bin = round(rr/rr_time_step)

            # 1.2 Check for correct bounds
            if fraction_bin < 1:
                print('Ramp rate below lower limit, choosing lowest possible value.')
                fraction_bin = 1
            elif fraction_bin > 256:
                print('Ramp rate above upper limit, choosing highest possible value.')
                fraction_bin = 256

            # align the fraction_bin with binary representation
            print('Setting {0} sweep ramp rate to {1:1.3e} s'.format(rr_name[i], fraction_bin*rr_time_step))
            fraction_bin -= 1
            rrw_bin = bin(fraction_bin)[2:]
            if len(rrw_bin) < 8:
                rrw_bin = (8-len(rrw_bin))*'0' + rrw_bin
            ramp_rate_word += rrw_bin
            print('Len RRW', len(ramp_rate_word))
        
        # write the new ramp rate word to the RR register
        ramp_rate_word = ''.join(' 0' + b for b in ramp_rate_word)
        ramp_rate_word = ramp_rate_word[1:]
        print('RRW: {0}'.format(ramp_rate_word), len(ramp_rate_word))
        self._write_to_dds_register(0x07, ramp_rate_word)
        print(self._read_from_register(0x07, 16))
        
        ###############################################
        # 2. Set the falling and rising delta words.
        # calculate the fraction of the full frequency
        delta_word_registers = [0x09, 0x08]
        delta_words = [fdw, rdw]
        for i, dw in enumerate(delta_words):
            fraction = dw/self.system_clock_frequency
            fraction_bin = bin(int(round(fraction * (2**32 - 1)))).lstrip('0b') # full range are 32 bit
            if len(fraction_bin) < 32:
                fraction_bin = (32-len(fraction_bin)) * '0' + fraction_bin
            closest_possible_value = (int(fraction_bin, base=2)/(2**32 -1) *
                                        self.system_clock_frequency)
            print('Setting {2} delta word of channel {1} to closest possible value {0}MHz'.format(
                                                            closest_possible_value/1e6, channels, rr_name[i]))

            # set the frequency word in the frequency register
            frequency_word = ''.join(' 0' + b for b in fraction_bin)
            frequency_word = frequency_word[1:]
            self._write_to_dds_register(delta_word_registers[i], frequency_word)
            print(frequency_word)
            print(self._read_from_register(delta_word_registers[i], 32))
        return

class AD9959dev(AD9959):
    def __init__(self, experiment, *args, **kwargs):
        super(AD9959dev, self).__init__(*args, **kwargs)
        self.default_frequency = 75e6

    def __set__(self, obj, value):
        """This sets the frequency of the channels. The method is needed to
        ensure compatibility with our experimental control.
        """
        self.set_frequency(value)

    def __get__(self, obj, value):
        """This sets the frequency of the channels. The method is needed to
        ensure compatibility with our experimental control.
        """

        return self.default_frequency
