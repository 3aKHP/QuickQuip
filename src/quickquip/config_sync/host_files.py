"""Keep host-managed plaintext readable by the invoking deployment account."""

import os


def return_ownership(path):
    uid, gid = os.getenv("QUICKQUIP_SYNC_UID"), os.getenv("QUICKQUIP_SYNC_GID")
    if os.name == "posix" and os.geteuid() == 0 and uid is not None and gid is not None:
        os.chown(path, int(uid), int(gid))
