import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand


def encode(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


class Command(BaseCommand):
    help = "Generate a VAPID key pair to copy into .env. Does not change existing settings."

    def handle(self, *args, **options):
        key = ec.generate_private_key(ec.SECP256R1())
        private = key.private_numbers().private_value.to_bytes(32, "big")
        public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.stdout.write(f"VAPID_PRIVATE_KEY={encode(private)}")
        self.stdout.write(f"VAPID_PUBLIC_KEY={encode(public)}")
        self.stderr.write("Keep the private key secret. Generate once and reuse across deployments.")
