import base64
import binascii
import json

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class DecryptError(Exception):
    """Qualquer falha ao decriptar: body mal formado, base64, IV, padding ou JSON ilegivel."""


def decrypt_payload(body: dict, key: bytes) -> dict:
    try:
        iv = base64.b64decode(body["iv"], validate=True)
        ciphertext = base64.b64decode(body["ciphertext"], validate=True)
        if len(iv) != 16 or not ciphertext or len(ciphertext) % 16:
            raise ValueError("tamanho invalido")
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        plain = unpadder.update(padded) + unpadder.finalize()
        return json.loads(plain.decode("utf-8"))
    except (KeyError, TypeError, ValueError, binascii.Error, UnicodeDecodeError) as exc:
        # Mensagem generica: nao vazar conteudo.
        raise DecryptError(type(exc).__name__) from exc


def encrypt_payload(payload: dict, key: bytes, iv: bytes) -> dict:
    """Usado nos testes para gerar requisicoes validas."""
    padder = padding.PKCS7(128).padder()
    padded = padder.update(json.dumps(payload).encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ct = encryptor.update(padded) + encryptor.finalize()
    return {"iv": base64.b64encode(iv).decode(), "ciphertext": base64.b64encode(ct).decode()}
