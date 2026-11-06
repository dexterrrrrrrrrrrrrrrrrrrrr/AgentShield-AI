"""Create a local Compose credential without displaying or overwriting it."""
import os
import secrets
from pathlib import Path

root=Path('.executor-secrets')
root.mkdir(mode=0o700)  # Refuse existing directory; never overwrite credentials.
fd=os.open(root/'token',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o400)
with os.fdopen(fd,'w') as f: f.write(secrets.token_urlsafe(48)+'\n')
# Compose file secrets are bind mounts: readable by app UID in containers.
# Host users are excluded by the containing directory's mode 0700.
os.chmod(root/'token',0o444)
print('Created private .executor-secrets directory and container-readable token. Keep this directory private and out of Git.')
