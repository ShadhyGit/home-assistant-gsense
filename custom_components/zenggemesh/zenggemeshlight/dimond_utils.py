# Copyright 2018 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Contains code derived from python-tikteck,
# Copyright 2016 Matthew Garrett <mjg59@srcf.ucam.org>

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
import random

def hex_to_str(hex_str):
    return str(bytearray([int(n, 16) for n in hex_str]))

def encrypt(key, data):
    k = AES.new(bytes(reversed(key)), AES.MODE_ECB)
    data = reversed(list(k.encrypt(bytes(reversed(data)))))
    rev = []
    for d in data:
        rev.append(d)
    return rev
 
def generate_sk(name, password, data1, data2):
    name = name.ljust(16, chr(0))
    password = password.ljust(16, chr(0))
    key = [ord(a) ^ ord(b) for a,b in zip(name,password)]
    data = data1[0:8]
    data += data2[0:8]
    return encrypt(key, data)

def key_encrypt(name, password, key):
    name = name.ljust(16, chr(0))
    password = password.ljust(16, chr(0))
    data = [ord(a) ^ ord(b) for a,b in zip(name,password)]
    return encrypt(key, data)

def encrypt_packet(sk, address, packet):
    auth_nonce = [address[0], address[1], address[2], address[3], 0x01,
                  packet[0], packet[1], packet[2], 15, 0, 0, 0, 0, 0, 0, 0]

    authenticator = encrypt(sk, auth_nonce)

    for i in range(15):
      authenticator[i] = authenticator[i] ^ packet[i+5]

    mac = encrypt(sk, authenticator)

    for i in range(2):
       packet[i+3] = mac[i]

    iv = [0, address[0], address[1], address[2], address[3], 0x01, packet[0],
          packet[1], packet[2], 0, 0, 0, 0, 0, 0, 0]

    temp_buffer = encrypt(sk, iv)
    for i in range(15):
        packet[i+5] ^= temp_buffer[i]

    return packet

def decrypt_packet(sk, address, packet):
    iv = [address[0], address[1], address[2], packet[0], packet[1], packet[2],
          packet[3], packet[4], 0, 0, 0, 0, 0, 0, 0, 0] 
    plaintext = [0] + iv[0:15]

    result = encrypt(sk, plaintext)

    for i in range(len(packet)-7):
      packet[i+7] ^= result[i]

    return packet


def send_packet(sk, mac, target, command, data, vendor=0x0211):
    # Default vendor = 0x0211
    packet_count = random.randrange(0xffff)
    macarray = mac.split(':')
    macdata = [int(macarray[5], 16), int(macarray[4], 16), int(macarray[3], 16), int(macarray[2], 16), int(macarray[1], 16), int(macarray[0], 16)]

    packet = [0] * 20
    packet[0] = packet_count & 0xff
    packet[1] = packet_count >> 8 & 0xff
    packet[5] = target & 0xff
    packet[6] = (target >> 8) & 0xff
    packet[7] = command
    packet[8] = vendor & 0xff
    packet[9] = (vendor >> 8) & 0xff
    for i in range(len(data)):
        packet[10 + i] = data[i]
    enc_packet = encrypt_packet(sk, macdata, packet)
    packet_count += 1
    if packet_count > 65535:
        packet_count = 1

    return bytes(enc_packet)