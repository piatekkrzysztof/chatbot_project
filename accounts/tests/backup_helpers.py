from django.core.management import call_command


def make_readable_backup(path):
    encrypted = str(path) + ".fernet"
    call_command("backup_data", output=encrypted)
    call_command("decrypt_backup", encrypted, output=str(path))
