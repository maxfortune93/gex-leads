import os
from dataclasses import dataclass
from pathlib import Path

QUEUE_RECEIVED = "lead.received"
QUEUE_DEAD = "lead.dead.processing_failed"
MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class Settings:
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_database: str
    rabbit_host: str
    rabbit_port: int
    rabbit_user: str
    rabbit_password: str
    aes_key: bytes

    @classmethod
    def from_env(cls) -> "Settings":
        key_file = Path(os.getenv("AES_KEY_FILE", "./data/grummer_secret.txt"))
        return cls(
            mysql_host=os.getenv("MYSQL_HOST", "localhost"),
            mysql_port=int(os.getenv("MYSQL_PORT", "3306")),
            mysql_user=os.getenv("MYSQL_USER", "gex"),
            mysql_password=os.getenv("MYSQL_PASSWORD", "gex_local_password"),
            mysql_database=os.getenv("MYSQL_DATABASE", "gex_backend_test"),
            rabbit_host=os.getenv("RABBITMQ_HOST", "localhost"),
            rabbit_port=int(os.getenv("RABBITMQ_AMQP_PORT", "5672")),
            rabbit_user=os.getenv("RABBITMQ_DEFAULT_USER", "gex"),
            rabbit_password=os.getenv("RABBITMQ_DEFAULT_PASS", "gex_local_password"),
            aes_key=bytes.fromhex(key_file.read_text().strip()),
        )
