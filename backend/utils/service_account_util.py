import base64
import secrets


def generate_service_account_key(bytes: int = 64) -> str:
    """Create a new secret key for use in service accounts."""
    key = secrets.token_bytes(bytes)  # 512-bit key

    return base64.urlsafe_b64encode(key).decode("utf-8")


def replace_superuser_key(key: str = "SUPERUSER_KEY", file_path="backend\\.env"):
    lines = []
    found = False

    value = generate_service_account_key()

    # find entry in current .env file
    with open(file_path, "r") as file:
        for line in file:
            if line.startswith(f"{key}="):
                lines.append(f'{key}="{value}"\n')
                found = True
            else:
                lines.append(line)

    # add new entry if it doesn't exist
    if not found:
        lines.append(f'{key}="{value}"\n')

    # overwrite the file
    with open(file_path, "w") as file:
        file.writelines(lines)
