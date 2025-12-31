from __future__ import annotations

from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken


@dataclass(frozen=True)
class Crypto:
    fernet: Fernet

    @staticmethod
    def from_master_key(master_key: str) -> "Crypto":
        return Crypto(fernet=Fernet(master_key.encode("utf-8")))

    def encrypt_text(self, plaintext: str) -> str:
        token = self.fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt_text(self, token: str) -> str:
        try:
            plaintext = self.fernet.decrypt(token.encode("utf-8"))
        except InvalidToken as e:
            raise ValueError("Invalid encrypted token (wrong APP_MASTER_KEY?)") from e
        return plaintext.decode("utf-8")

