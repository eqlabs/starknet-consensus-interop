import os
import paramiko
import time


def ssh_connect(ip, username='ubuntu', key_path='~/.ssh/interop.pem', retries=5, delay=2):
    """
    Connect to a remote VM over SSH using a private key.
    Retries on AuthenticationException with exponential backoff.
    """
    key = paramiko.RSAKey.from_private_key_file(os.path.expanduser(key_path))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    for attempt in range(1, retries + 1):
        try:
            print(f"🔐 Connecting to {ip} via SSH... (attempt {attempt})")
            client.connect(hostname=ip, username=username, pkey=key)
            return client
        except paramiko.ssh_exception.AuthenticationException as e:
            if attempt == retries:
                print("❌ SSH authentication failed after multiple attempts.")
                raise
            print(f"⚠️ SSH auth failed (attempt {attempt}), retrying in {delay}s...")
            time.sleep(delay)
            delay *= 2  # exponential backoff


def ssh_run_command(client, command):
    """
    Run a shell command on a remote machine over an existing SSH connection.
    """
    print(f"⚙️ Running remote command: {command}")
    stdin, stdout, stderr = client.exec_command(command)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out:
        print(f"🟢 STDOUT: {out.strip()}")
    if err:
        print(f"🔴 STDERR: {err.strip()}")
    return out, err


def ssh_upload_file(client, local_path, remote_path):
    """
    Upload a local file to a remote path using SFTP.
    """
    print(f"📤 Uploading {local_path} to {remote_path}")
    sftp = client.open_sftp()
    sftp.put(local_path, remote_path)
    sftp.close()

def wait_for_ssh(ip, timeout=60):
    import socket
    import time

    print(f"⏳ Waiting for SSH to become available on {ip}...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            sock = socket.create_connection((ip, 22), timeout=5)
            sock.close()
            print("✅ SSH is now available.")
            return
        except (ConnectionRefusedError, socket.timeout, OSError):
            time.sleep(3)
    raise Exception(f"SSH not available on {ip} after {timeout} seconds.")
