import usb
import time

class AD9959(object):
    """This class emulates the AD9959 evaluation board for python.

    An instance of the class will construct a handler for the cypress USB
    controler. Through this handler commands can be sent to the chip and piped
    to the DDS processor.
    """
    
    def __init__(self, vid=0x0456, pid=0xee25, auto_update=True):
        """Initializes a handler for the usb controler.

        vid : hex
            vendor ID of the device
        pid : hex
            product ID of the device

        """
        dev = usb.core.find(idVendor=vid, idProduct=pid)
        self.dev = dev
        dev.set_configuration()
        cnf = dev.configurations()[0]
        intf = cnf[(0,0)]

        # retrieve important endpoints of usb controller
        self._ep1 = intf[0]
        self._ep81 = intf[1]
        self._ep4 = intf[3]
        self._ep88 = intf[5]

        # create a handler for the usb controler
        self._usb_handler = usb.DeviceHandle(dev)

        # set default values for physical variables
        self.ref_clock_frequency = 20e6 # 20MHz standard
        self.system_clock_frequency = 20e6

        # set default value for auto IO update
        self.auto_update = auto_update

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
        self._usb_handler.bulkWrite(self._ep4, message)

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
        self._usb_handler.bulkWrite(self._ep1, begin_readback)

        # construct the command to read out the register
        register_bin = bin(register).lstrip('0b')
        if len(register_bin) < 7:
            register_bin = (7-len(register_bin))*'0' + register_bin
        register_bin = ''.join(' 0' + b for b in register_bin)
        readout_command = bytearray.fromhex('01' + register_bin)
        self._usb_handler.bulkWrite(self._ep4, readout_command)
        
        time.sleep(0.1)
        # read the message from endpoint 88
        readout = self._usb_handler.bulkRead(self._ep88, size=size)

        # turn off readback mode
        end_readback = bytearray.fromhex('04 00')
        self._usb_handler.bulkWrite(self._ep1, end_readback)
        return readout

    def _load_IO(self):
        """Loads the I/O update line (same as GUI load function).

        """
        load_message = bytearray.fromhex('0C 00')
        self._usb_handler.bulkWrite(self._ep1, load_message)
        readout = self._usb_handler.bulkRead(self._ep81, 1)
        return readout

    def _update_IO(self):
        """Updates the IO to the DDS chip (same as GUI function).

        """
        update_message = bytearray.fromhex('0C 10')
        self._usb_handler.bulkWrite(self._ep1, update_message)
        readout = self._usb_handler.bulkRead(self._ep81, 1)
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
        if type(channel) == int:
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

    def set_frequency(self, frequency, channel=0):
        """Sets a new frequency for a given channel.

        :frequency: float
            The new frequency in Hz. Should not exceed `system_clock_frequency`.
        :channel: int or seq
            Channel(s) for which the frequency should be set.

        """

        assert frequency <= self.system_clock_frequency, ("Frequency should not"
                + " exceed system clock frequency! System clock frequency is {0}Hz".format(self.system_clock_frequency))

        # select the chosen channels
        self._channel_select(channel)

        # calculate the fraction of the full frequency
        fraction = frequency/self.system_clock_frequency
        fraction_bin = bin(round(fraction * (2**32 - 1))).lstrip('0b') # full range are 32 bit
        if len(fraction_bin) < 32:
            fraction_bin = (32-len(fraction_bin)) * '0' + fraction_bin
        closest_possible_value = (int(fraction_bin, base=2)/(2**32 -1) *
                                    self.system_clock_frequency)
        print('Setting frequency of channel {1} to closest possible value {0}MHz'.format(
                                                        closest_possible_value/1e6, channel))

        # set the frequency word in the frequency register
        frequency_word = ''.join(' 0' + b for b in fraction_bin)
        frequency_word = frequency_word[1:]
        self._write_to_dds_register(0x04, frequency_word)

        # load and update I/O
        self._load_IO()
        if self.auto_update:
            self._update_IO()

    def set_phase(self, phase, channel=0):
        """Sets the phase offset for a given channel.

        :phase: float
            phase in degree, 0 < `phase` < 360
        :channels: int or list
            ID or list of IDs of the selected channels

        """
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
