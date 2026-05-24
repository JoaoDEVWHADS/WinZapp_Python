import os
import json
import requests
from cryptography.fernet import Fernet

def generate_and_save_key(filepath):
    key = Fernet.generate_key()
    with open(filepath, 'wb') as key_file:
        key_file.write(key)
    return key

def retrieve_key(filepath):
    with open(filepath, 'rb') as key_file:
        key = key_file.read()
    return key

def encrypt(data, key):
    fernet = Fernet(key)
    #Encode only if data is string
    if isinstance(data, str):
        data = data.encode()
    encrypted_data = fernet.encrypt(data)
    return encrypted_data

def decrypt(encrypted_data, key):
    fernet = Fernet(key)
    decrypted_data = fernet.decrypt(encrypted_data)
    return decrypted_data.decode()

def decrypt_bytes(encrypted_data, key):
    fernet = Fernet(key)
    return fernet.decrypt(encrypted_data)

def encrypt_json(data, key):
    fernet = Fernet(key)
    json_data = json.dumps(data).encode()
    encrypted_data = fernet.encrypt(json_data)
    return encrypted_data

def decrypt_json(encrypted_data, key):
    fernet = Fernet(key)
    decrypted_data = fernet.decrypt(encrypted_data)
    data = json.loads(decrypted_data.decode())
    return data

def format_number(string_number):
    #Removes any non-digit characters
    clean_number = string_number.split('@')[0]

    #Extracts DDI and DDD
    ddi = clean_number[:2]
    ddd = clean_number[2:4]
    remaining = clean_number[4:]

    # If the number has 9 digits in the remaining part
    if len(remaining) == 9:
        part1 = remaining[:5]
        part2 = remaining[5:]
    else:
        # Assumes the number has 8 digits in the remaining part
        part1 = remaining[:4]
        part2 = remaining[4:]

    return f'+{ddi} {ddd} {part1}-{part2}'

def check_internet_connection(test_url="https://www.google.com", timeout=10):
    try:
        response = requests.get(test_url, timeout=timeout)
        return True
    except (requests.ConnectionError, requests.Timeout):
        return False
