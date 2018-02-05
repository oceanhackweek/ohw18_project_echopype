

from collections import defaultdict
from struct import unpack_from, unpack
import numpy as np
import os
import re
from datetime import datetime as dt
from matplotlib.dates import date2num
from echosounder_model import BaseEnum


# Set contants for unpacking .raw files
BLOCK_SIZE = 1024*4             # Block size read in from binary file to search for token
LENGTH_SIZE = 4
DATAGRAM_HEADER_SIZE = 12
CONFIG_HEADER_SIZE = 516
CONFIG_TRANSDUCER_SIZE = 320

# set global regex expressions to find all sample, annotation and NMEA sentences
SAMPLE_REGEX = b'RAW\d{1}'
SAMPLE_MATCHER = re.compile(SAMPLE_REGEX, re.DOTALL)

# Reference time "seconds since 1900-01-01 00:00:00"
REF_TIME = date2num(dt(1900, 1, 1, 0, 0, 0))

# ---------- NEED A GENERIC FILENAME PARSER -------------
# Common EK60 *.raw filename format
# EK60_RAW_NAME_REGEX = r'(?P<Refdes>\S*)_*OOI-D(?P<Date>\d{8})-T(?P<Time>\d{6})\.raw'
# EK60_RAW_NAME_MATCHER = re.compile(EK60_RAW_NAME_REGEX)

# Regex to extract the timestamp from the *.raw filename (path/to/OOI-DYYYYmmdd-THHMMSS.raw)
FILE_NAME_REGEX = r'(?P<Refdes>\S*)_*OOI-D(?P<Date>\d{8})-T(?P<Time>\d{6})\.raw'
FILE_NAME_MATCHER = re.compile(FILE_NAME_REGEX)

WINDOWS_EPOCH = dt(1601, 1, 1)
NTP_EPOCH = dt(1900, 1, 1)
NTP_WINDOWS_DELTA = (NTP_EPOCH - WINDOWS_EPOCH).total_seconds()


def read_config_header(chunk):
    """
    Reads the EK60 raw data file configuration header information
    from the byte string passed in as a chunk
    @param chunk data chunk to read the config header from
    @return: configuration header
    """
    # setup unpack structure and field names
    field_names = ('survey_name', 'transect_name', 'sounder_name',
                   'version', 'transducer_count')
    fmt = '<128s128s128s30s98sl'

    # read in the values from the byte string chunk
    values = list(unpack(fmt, chunk))
    values.pop(4)  # drop the spare field

    # strip the trailing zero byte padding from the strings
    # for i in [0, 1, 2, 3]:
    for i in range(4):
        values[i] = values[i].strip(b'\x00')

    # create the configuration header dictionary
    config_header = dict(zip(field_names, values))
    return config_header


def read_config_transducer(chunk):
    """
    Reads the EK60 raw data file configuration transducer information
    from the byte string passed in as a chunk
    @param chunk data chunk to read the configuration transducer information from
    @return: configuration transducer information
    """

    # setup unpack structure and field names
    field_names = ('channel_id', 'beam_type', 'frequency', 'gain',
                   'equiv_beam_angle', 'beam_width_alongship', 'beam_width_athwartship',
                   'angle_sensitivity_alongship', 'angle_sensitivity_athwartship',
                   'angle_offset_alongship', 'angle_offset_athwart', 'pos_x', 'pos_y',
                   'pos_z', 'dir_x', 'dir_y', 'dir_z', 'pulse_length_table', 'gain_table',
                   'sa_correction_table', 'gpt_software_version')
    fmt = '<128sl15f5f8s5f8s5f8s16s28s'

    # read in the values from the byte string chunk
    values = list(unpack(fmt, chunk))

    # convert some of the values to arrays
    pulse_length_table = np.array(values[17:22])
    gain_table = np.array(values[23:28])
    sa_correction_table = np.array(values[29:34])

    # strip the trailing zero byte padding from the strings
    for i in [0, 35]:
        values[i] = values[i].strip(b'\x00')

    # put it back together, dropping the spare strings
    config_transducer = dict(zip(field_names[0:17], values[0:17]))
    config_transducer[field_names[17]] = pulse_length_table
    config_transducer[field_names[18]] = gain_table
    config_transducer[field_names[19]] = sa_correction_table
    config_transducer[field_names[20]] = values[35]
    return config_transducer


def read_header(filehandle):
    # Read binary file a block at a time
    raw = filehandle.read(BLOCK_SIZE)

    # Read the configuration datagram, output at the beginning of the file
    length1, = unpack_from('<l', raw)
    byte_cnt = LENGTH_SIZE

    # Configuration datagram header
    byte_cnt += DATAGRAM_HEADER_SIZE

    # Configuration: header
    config_header = read_config_header(raw[byte_cnt:byte_cnt+CONFIG_HEADER_SIZE])
    byte_cnt += CONFIG_HEADER_SIZE
    config_transducer = []
    for num_transducer in range(config_header['transducer_count']):
        config_transducer.append(read_config_transducer(raw[byte_cnt:byte_cnt+CONFIG_TRANSDUCER_SIZE]))
        byte_cnt += CONFIG_TRANSDUCER_SIZE
    #byte_cnt += CONFIG_TRANSDUCER_SIZE * config_header['transducer_count']

    # Compare length1 (from beginning of datagram) to length2 (from the end of datagram) to
    # the actual number of bytes read. A mismatch can indicate an invalid, corrupt, misaligned,
    # or missing configuration datagram or a reverse byte order binary data file.
    # A bad/missing configuration datagram header is a significant error.
    length2, = unpack_from('<l', raw, byte_cnt)
    if not (length1 == length2 == byte_cnt-LENGTH_SIZE):
        print('Possible file corruption or format incompatibility.')
#         raise InstrumentDataException(
#             "Length of configuration datagram and number of bytes read do not match: length1: %s"
#             ", length2: %s, byte_cnt: %s. Possible file corruption or format incompatibility." %
#             (length1, length2, byte_cnt+LENGTH_SIZE))
    byte_cnt += LENGTH_SIZE
    filehandle.seek(byte_cnt)
    return config_header, config_transducer


class ZplscBParticleKey(BaseEnum):
    """
    Class that defines fields that need to be extracted from the data
    """
    FILE_TIME = "zplsc_timestamp"               # raw file timestamp
    ECHOGRAM_PATH = "filepath"                  # output echogram plot .png/s path and filename
    CHANNEL = "zplsc_channel"
    TRANSDUCER_DEPTH = "zplsc_transducer_depth" # five digit floating point number (%.5f, in meters)
    FREQUENCY = "zplsc_frequency"               # six digit fixed point integer (in Hz)
    TRANSMIT_POWER = "zplsc_transmit_power"     # three digit fixed point integer (in Watts)
    PULSE_LENGTH = "zplsc_pulse_length"         # six digit floating point number (%.6f, in seconds)
    BANDWIDTH = "zplsc_bandwidth"               # five digit floating point number (%.5f in Hz)
    SAMPLE_INTERVAL = "zplsc_sample_interval"   # six digit floating point number (%.6f, in seconds)
    SOUND_VELOCITY = "zplsc_sound_velocity"     # five digit floating point number (%.5f, in m/s)
    ABSORPTION_COEF = "zplsc_absorption_coeff"  # four digit floating point number (%.4f, dB/m)
    TEMPERATURE = "zplsc_temperature"           # three digit floating point number (%.3f, in degC)


# The following is used for _build_parsed_values() and defined as below:
# (parameter name, encoding function)
METADATA_ENCODING_RULES = [
    (ZplscBParticleKey.FILE_TIME, str),
    (ZplscBParticleKey.ECHOGRAM_PATH, str),
    (ZplscBParticleKey.CHANNEL, lambda x: [int(y) for y in x]),
    (ZplscBParticleKey.TRANSDUCER_DEPTH, lambda x: [float(y) for y in x]),
    (ZplscBParticleKey.FREQUENCY, lambda x: [float(y) for y in x]),
    (ZplscBParticleKey.TRANSMIT_POWER, lambda x: [float(y) for y in x]),
    (ZplscBParticleKey.PULSE_LENGTH, lambda x: [float(y) for y in x]),
    (ZplscBParticleKey.BANDWIDTH, lambda x: [float(y) for y in x]),
    (ZplscBParticleKey.SAMPLE_INTERVAL, lambda x: [float(y) for y in x]),
    (ZplscBParticleKey.SOUND_VELOCITY, lambda x: [float(y) for y in x]),
    (ZplscBParticleKey.ABSORPTION_COEF, lambda x: [float(y) for y in x]),
    (ZplscBParticleKey.TEMPERATURE, lambda x: [float(y) for y in x])
]


# Numpy data type object for unpacking the Sample datagram including the header from binary *.raw
sample_dtype = np.dtype([('length1', 'i4'),  # 4 byte int (long)
                            # DatagramHeader
                            ('datagram_type', 'a4'),  # 4 byte string
                            ('low_date_time', 'u4'),  # 4 byte int (long)
                            ('high_date_time', 'u4'),  # 4 byte int (long)
                            # SampleDatagram
                            ('channel_number', 'i2'),  # 2 byte int (short)
                            ('mode', 'i2'),  # 2 byte int (short)
                            ('transducer_depth', 'f4'),  # 4 byte float
                            ('frequency', 'f4'),  # 4 byte float
                            ('transmit_power', 'f4'),  # 4 byte float
                            ('pulse_length', 'f4'),  # 4 byte float
                            ('bandwidth', 'f4'),  # 4 byte float
                            ('sample_interval', 'f4'),  # 4 byte float
                            ('sound_velocity', 'f4'),  # 4 byte float
                            ('absorption_coefficient', 'f4'),  # 4 byte float
                            ('heave', 'f4'),  # 4 byte float
                            ('roll', 'f4'),  # 4 byte float
                            ('pitch', 'f4'),  # 4 byte float
                            ('temperature', 'f4'),  # 4 byte float
                            ('trawl_upper_depth_valid', 'i2'),  # 2 byte int (short)
                            ('trawl_opening_valid', 'i2'),  # 2 byte int (short)
                            ('trawl_upper_depth', 'f4'),  # 4 byte float
                            ('trawl_opening', 'f4'),  # 4 byte float
                            ('offset', 'i4'),  # 4 byte int (long)
                            ('count', 'i4')])                     # 4 byte int (long)
sample_dtype = sample_dtype.newbyteorder('<')

power_dtype = np.dtype([('power_data', '<i2')])     # 2 byte int (short)

angle_dtype = np.dtype([('athwart', '<i1'), ('along', '<i1')])     # 1 byte ints



def windows_to_ntp(windows_time):
    """
    Convert a windows file timestamp into Network Time Protocol
    :param windows_time:  100ns since Windows time epoch
    :return:
    """
    return windows_time / 1e7 - NTP_WINDOWS_DELTA


def build_windows_time(high_word, low_word):
    """
    Generate Windows time value from high and low date times.

    :param high_word:  high word portion of the Windows datetime
    :param low_word:   low word portion of the Windows datetime
    :return:  time in 100ns since 1601/01/01 00:00:00 UTC
    """
    return (high_word << 32) + low_word



def extract_file_time(filepath):
    match = FILE_NAME_MATCHER.match(filepath)
    if match:
        return match.group('Date') + match.group('Time')
    else:
        # Files retrieved from the instrument should always match the timestamp naming convention
        error_message = \
            "Unable to extract file time from input file name: %s. Expected format *-DYYYYmmdd-THHMMSS.raw" \
            % filepath
        log.error(error_message)
        raise InstrumentDataException(error_message)


def process_sample(input_file, transducer_count):
    # log.trace('Processing one sample from input_file: %r', input_file)
    # print('Processing one sample from input_file')

    # Read and unpack the Sample Datagram into numpy array
    sample_data = np.fromfile(input_file, dtype=sample_dtype, count=1)
    channel = sample_data['channel_number'][0]

    # Check for a valid channel number that is within the number of transducers config
    # to prevent incorrectly indexing into the dictionaries.
    # An out of bounds channel number can indicate invalid, corrupt,
    # or misaligned datagram or a reverse byte order binary data file.
    # Log warning and continue to try and process the rest of the file.
    if channel < 0 or channel > transducer_count:
        print('Invalid channel: %s for transducer count: %s. \n\
        Possible file corruption or format incompatibility.' % (channel, transducer_count))
        # log.warn("Invalid channel: %s for transducer count: %s."
        #          "Possible file corruption or format incompatibility.", channel, transducer_count)
        # raise InvalidTransducer

    # Convert high and low bytes to internal time
    windows_time = build_windows_time(sample_data['high_date_time'][0], sample_data['low_date_time'][0])
    ntp_time = windows_to_ntp(windows_time)

    count = sample_data['count'][0]

    # Extract array of power data
    power_data = np.fromfile(input_file, dtype=power_dtype, count=count).astype('f8')

    # Read the athwartship and alongship angle measurements
    if sample_data['mode'][0] > 1:
        angle_data = np.fromfile(input_file, dtype=angle_dtype, count=count)
    else:
        angle_data = []

    # Read and compare length1 (from beginning of datagram) to length2
    # (from the end of datagram). A mismatch can indicate an invalid, corrupt,
    # or misaligned datagram or a reverse byte order binary data file.
    # Log warning and continue to try and process the rest of the file.
    len_dtype = np.dtype([('length2', '<i4')])  # 4 byte int (long)
    length2_data = np.fromfile(input_file, dtype=len_dtype, count=1)
    if not (sample_data['length1'][0] == length2_data['length2'][0]):
        print('Mismatching beginning and end length values in sample datagram: \n\
        length1: %d, length2: %d.\n\
        Possible file corruption or format incompatibility.' % (sample_data['length1'][0], length2_data['length2'][0]))
        # log.warn("Mismatching beginning and end length values in sample datagram: length1"
        #          ": %s, length2: %s. Possible file corruption or format incompatibility.",
        #          sample_data['length1'][0], length2_data['length2'][0])

    return channel, ntp_time, sample_data, power_data, angle_data


def append_metadata(metadata, file_time, channel, sample_data):
    metadata[ZplscBParticleKey.FILE_TIME] = file_time
    #metadata[ZplscBParticleKey.ECHOGRAM_PATH]= file_path
    metadata[ZplscBParticleKey.CHANNEL].append(channel)
    metadata[ZplscBParticleKey.TRANSDUCER_DEPTH].append(sample_data['transducer_depth'][0])
    metadata[ZplscBParticleKey.FREQUENCY].append(sample_data['frequency'][0])
    metadata[ZplscBParticleKey.TRANSMIT_POWER].append(sample_data['transmit_power'][0])
    metadata[ZplscBParticleKey.PULSE_LENGTH].append(sample_data['pulse_length'][0])
    metadata[ZplscBParticleKey.BANDWIDTH].append(sample_data['bandwidth'][0])
    metadata[ZplscBParticleKey.SAMPLE_INTERVAL].append(sample_data['sample_interval'][0])
    metadata[ZplscBParticleKey.SOUND_VELOCITY].append(sample_data['sound_velocity'][0])
    metadata[ZplscBParticleKey.ABSORPTION_COEF].append(sample_data['absorption_coefficient'][0])
    metadata[ZplscBParticleKey.TEMPERATURE].append(sample_data['temperature'][0])
    return metadata


def parse_echogram_file(input_file_path):   #, output_file_path=None):
    """
    Parse the *.raw file.
    @param input_file_path absolute path/name to file to be parsed
    # @param output_file_path optional path to directory to write output
    If omitted outputs are written to path of input file
    """
    print('%s  unpacking file: %s' % (dt.now().strftime('%H:%M:%S'), input_file_path))
    # image_path = generate_image_file_path(input_file_path, output_file_path)

    file_time = extract_file_time(input_file_path)  # time at file generation

    with open(input_file_path, 'rb') as input_file:  # read ('r') input file using binary mode ('b')

        config_header, config_transducer = read_header(input_file)
        transducer_count = config_header['transducer_count']

        transducer_keys = range(1, transducer_count+1)
        frequencies = dict.fromkeys(transducer_keys)       # transducer frequency
        bin_size = None                                    # transducer depth measurement

        position = input_file.tell()
        particle_data = None

        last_time = None
        sample_data_temp_dict = {}
        power_data_temp_dict = {}

        power_data_dict = {}
        data_times = []
        temperature = []   # WJ: Used to check temperature reading in .RAW file --> all identical for OOI data

        # Read binary file a block at a time
        raw = input_file.read(BLOCK_SIZE)

        while len(raw) > 4:
            # We only care for the Sample datagrams, skip over all the other datagrams
            match = SAMPLE_MATCHER.search(raw)

            if match:
                # Offset by size of length value
                match_start = match.start() - LENGTH_SIZE

                # Seek to the position of the length data before the token to read into numpy array
                input_file.seek(position + match_start)

                # try:
                next_channel, next_time, next_sample, next_power, next_angle = process_sample(input_file, transducer_count)

                if next_time != last_time:  # WJ: next_time=last_time when it's the same ping but different channel
                    # Clear out our temporary dictionaries and set the last time to this time
                    sample_data_temp_dict = {}
                    power_data_temp_dict = {}
                    angle_data_temp_dict = {}
                    last_time = next_time

                # Store this data
                sample_data_temp_dict[next_channel] = next_sample
                power_data_temp_dict[next_channel] = next_power
                angle_data_temp_dict[next_channel] = next_angle

                # Check if we have enough records to produce a new row of data
                # WJ: if yes this means that data from all transducer channels have been read for a particular ping
                # WJ: a new row of data means all data from one ping
                # WJ: if only 2 channels of data were received, they are not stored in the final power_data_dict
                if len(sample_data_temp_dict) == len(power_data_temp_dict) == len(angle_data_temp_dict) == transducer_count:
                    # if this is our first set of data, create our metadata particle and store
                    # the frequency / bin_size data
                    if not power_data_dict:
                        # relpath = generate_relative_file_path(image_path)
                        first_ping_metadata = defaultdict(list)
                        for channel, sample_data in sample_data_temp_dict.items():
                            append_metadata(first_ping_metadata, file_time, channel, sample_data)

                            frequency = sample_data['frequency'][0]
                            frequencies[channel] = frequency

                            if bin_size is None:
                                bin_size = sample_data['sound_velocity'] * sample_data['sample_interval'] / 2

                        #particle_data = first_ping_metadata, next_time  # WJ: probably don't need to append next_time here
                        power_data_dict = {channel: [] for channel in power_data_temp_dict}

                    # Save the time and power data for plotting
                    data_times.append(next_time)
                    for channel in power_data_temp_dict:
                        power_data_dict[channel].append(power_data_temp_dict[channel])

                    temperature.append(next_sample['temperature'])  # WJ: check temperature values from .RAW file: all identical for OOI data

                # except InvalidTransducer:
                #   pass

            else:
                input_file.seek(position + BLOCK_SIZE - 4)

            # Need current position in file to increment for next regex search offset
            position = input_file.tell()
            # Read the next block for regex search
            raw = input_file.read(BLOCK_SIZE)

        # convert ntp time, i.e. seconds since 1900-01-01 00:00:00 to matplotlib time
        data_times = np.array(data_times)
        data_times = (data_times / (60 * 60 * 24)) + REF_TIME

        # Convert to numpy array and decompress power data to dB
        # And then transpose power data
        for channel in power_data_dict:
            power_data_dict[channel] = np.array(power_data_dict[channel]) * 10. * np.log10(2) / 256.
            power_data_dict[channel] = power_data_dict[channel].transpose()

        # WJ: Rename keys in power data to according to transducer frequency
        for channel in power_data_dict:
            power_data_dict[frequencies[channel]] = power_data_dict.pop(channel)

        return first_ping_metadata, data_times, power_data_dict, frequencies, bin_size, config_header, config_transducer