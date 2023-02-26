#!/usr/bin/python3
import argparse
import copy
import urllib.request
import os


class ET312FirmwareUtils(object):

    KEYS = [0x65, 0xed, 0x83]
    IV = [0xb9, 0xfe, 0x8f]

    def __init__(self, input_file, output_file=None):
        self.iv = copy.copy(ET312FirmwareUtils.IV)
        with open(input_file, "rb") as f:
            self.input_file = bytearray(f.read())
        self.fill_space()
        if output_file:
            self.output_file = open(output_file, "wb")

    def generate_crc(self):
        xor = 0
        add = 0
        for c in range(15872 - 16):
            xor ^= self.input_file[c]
            add += self.input_file[c]
        return [xor, (add & 0xff), ((add >> 8) & 0xff)]

    def encrypt(self, write_crc=True):
        funcs = {0: lambda x: ((x - 0x41 if x >= 0x41
                                else ((x - 0x41) + 0x100)) ^ 0x62) & 0xff,
                 1: lambda x: (x >> 4) | ((x & 0x0f) << 4),
                 2: lambda x: x}

        if write_crc:
            crc = self.generate_crc()
            for i in range(3):
                self.input_file[-16 + i] = crc[i]

        for i in range(0, len(self.input_file)):
            n = self.input_file[i]
            choice = i % 3
            output = funcs[choice](n ^ self.iv[choice] ^ self.KEYS[choice])
            self.output_file.write(bytearray([output]))
            self.iv[choice] = output

    def decrypt(self):
        funcs = {0: lambda x: ((x ^ 0x62) + 0x41) & 0xff,
                 1: lambda x: (n >> 4) | ((n & 0x0f) << 4),
                 2: lambda x: x}

        for i in range(0, len(self.input_file)):
            n = self.input_file[i]
            choice = i % 3
            output = funcs[choice](n) ^ self.iv[choice] ^ self.KEYS[choice]
            self.output_file.write(bytearray([output]))
            self.iv[choice] = n

    def fill_space(self):
        if len(self.input_file) >= 15872:
            return
        self.input_file += bytearray([0] * (15872 - len(self.input_file)))

    def upload(self, port):
        import serial
        from xmodem import XMODEM
        import io
        # In case xmodem starts acting up
        # import logging
        # logging.basicConfig(level=logging.DEBUG)

        s = serial.Serial(port, 19200, timeout=1,
                          parity=serial.PARITY_NONE,
                          bytesize=8, stopbits=1,
                          xonxoff=0, rtscts=0)

        def getc(size, timeout=1):
            return s.read(size)

        def putc(data, timeout=1):
            return s.write(data)

        modem = XMODEM(getc, putc)
        modem.send(io.BytesIO(self.input_file))

    # Our patch file is the output of avr-objdump -D somefile.elf
    #
    # 00003022 <replace_0x438>:
    #   3022:       0c 94 00 18     jmp     0x3000  ; 0x3000 <loopmain>
    #
    # read the input binary file
    # patch following the instructions above
    # so in that case replacing bytes at 0x438 with 0c 94 00 18
    # note the asm might go over multiple lines, stop at EOF or a blank line
    #
    # For code in the output which isn't in a replace_ section, just patch it
    # in at the location specified.
        
    def patch(self, patchfile):
        import re
        self.verbose = False

        patched = 0
        
        f = open(patchfile,"r")
        for line in f:
            replace = re.search('<replace_([^>]+)',line)
            if replace:
                replacestart = int(replace.group(1),16)
                line = f.readline()
                replacewith = ""

                while (":" in line):
                    replacewith += line.split("\t")[1]
                    line = f.readline()

                for bytes in replacewith.split():
                    decbyte = int(bytes,16)
                    if (self.verbose):
                        print ("Patched %04x with %02x"%(replacestart,decbyte))
                    self.input_file[replacestart] = decbyte
                    patched+=1
                    replacestart+=1
            elif (':' in line):
                try:
                    location = int(line.split("\t")[0].rstrip(':'),16)
                    hexbytes = line.split("\t")[1]
                    for bytes in hexbytes.split():
                        decbyte = int(bytes,16)
                        self.input_file[location] = decbyte
                        if (self.verbose):
                            print ("Code %04x %02x"%(location,decbyte))
                        location+=1
                        patched+=1
                except:
                    pass

        print("Patched %d bytes" %(patched))
        self.output_file.write(bytearray(self.input_file))
        return        

def download_firmware_file(path, filename):
    # If this url ever goes away, just attach
    # https://web.archive.org/web/20160824194422if_/ to the front of it.
    url = 'http://media.erostek.com.s3.amazonaws.com/support/%s' % (filename)
    dl = os.path.join(path, filename)
    print("Downloading %s to %s..." % (url, path))
    urllib.request.urlretrieve(url, dl)


def download_firmware():
    script_dir = os.path.dirname(os.path.realpath(__file__))
    path = os.path.realpath(os.path.join(script_dir, "..", "firmware"))
    os.makedirs(path, exist_ok=True)
    for f in ["312-16.upg"]:
        download_firmware_file(path, f)
        dcfw = os.path.join(path, f.split(".")[0] + "-decrypted.bin")
        print("Making decrypted version at %s" % (dcfw))
        etfw = ET312FirmwareUtils(os.path.join(path, f),
                                  dcfw)
        etfw.decrypt()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", dest="input_file",
                        help="File to take action on")
    parser.add_argument("-o", "--output", dest="output_file",
                        help="File to output, if needed by action")
    parser.add_argument("-d", "--decrypt", dest="decrypt", action="store_true",
                        help="Decrypt input file, store in output file")
    parser.add_argument("-e", "--encrypt", dest="encrypt", action="store_true",
                        help="Encrypt input file, store in output file."
                        " Adds checksum to output by default.")
    parser.add_argument("-p", "--patch", dest="patch", help="Patch decrypted firmware " +
                        "using fwpatch file as argument, store in output file")
    parser.add_argument("-u", "--upload", dest="upload",
                        help="Upload input file to box, expects com port as " +
                        "argument. (requires serial and xmodem packages)")
    parser.add_argument("-c", "--crc", dest="crc", action="store_true",
                        help="Output xor/checksum for input file")
    parser.add_argument("-f", "--downloadfw", dest="download", action="store_true",
                        help="Downloads encrypted update files from website, " +
                        "as they cannot be stored with repo/project due to " +
                        "copyright. Decrypts files after downloading.")
    args = parser.parse_args()

    if args.download:
        download_firmware()
        return 0

    if not args.input_file:
        print("ERROR: Input file required to run.")
        parser.print_help()
        return 1

    if (args.decrypt or args.encrypt or args.patch) and not args.output_file:
        print("ERROR: Output file required for encryption/decryption/patching.")
        parser.print_help()
        return 1

    etfw = ET312FirmwareUtils(args.input_file, args.output_file)
    if args.encrypt:
        etfw.encrypt()
    elif args.decrypt:
        etfw.decrypt()
    elif args.patch:
        etfw.patch(args.patch)
    elif args.upload:
        etfw.upload(args.upload)
    elif args.crc:
        print(["0x%.02x" % x for x in etfw.generate_crc()])
    return 0

if __name__ == "__main__":
    main()
