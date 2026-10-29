"""Private workspace baselines and recoverable editing transactions."""

import os
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

from quickquip.configuration.errors import ConfigError
from quickquip.configuration.files import read_json, write_json, install
from quickquip.llm.config_durability import sync_directory

FORMAT = 2


class Storage:
    def __init__(self, directory):
        self.directory = Path(directory).absolute()
        if any(path.is_symlink() for path in (self.directory, *self.directory.parents)):
            raise ConfigError("invalid_workspace", "Workspace path is redirected")
        self.directory = self.directory.resolve()
        self.private = self.directory / ".qqconf"
        if self.private.is_symlink():
            raise ConfigError("invalid_workspace", "Workspace metadata is redirected")

    def state(self):
        state = read_json(self.private / "state.json")
        if state.get("format") != FORMAT:
            raise ConfigError("legacy_workspace", "Unpack into a new workspace")
        return state

    def lock(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.directory.chmod(0o700)
        self.private.mkdir(parents=True, exist_ok=True, mode=0o700)
        return FileLock(str(self.private / "write.lock"), timeout=10)

    def pending(self):
        return (self.private / "transaction.json").exists()

    def recover(self):
        if not self.pending():
            return
        record = read_json(self.private / "transaction.json")
        if (self.private / "state.json").exists() and self.state() == record["state_after"]:
            (self.private / "transaction.json").unlink()
            sync_directory(self.private)
            return
        install(self.directory, record["after"], record["before"])
        if record["state_before"] is None:
            (self.private / "state.json").unlink(missing_ok=True)
        else:
            write_json(self.private / "state.json", record["state_before"])
        (self.private / "transaction.json").unlink()
        sync_directory(self.private)

    def save(self, before, after, state):
        previous = self.state() if (self.private / "state.json").exists() else None
        if before == after and previous == state:
            return
        if previous is not None and previous.get("receipt") == state.get("receipt"):
            state["receipt"] = uuid4().hex
        write_json(
            self.private / "transaction.json",
            {
                "before": before,
                "after": after,
                "state_before": previous,
                "state_after": state,
            },
        )
        try:
            install(self.directory, before, after)
            write_json(self.private / "state.json", state)
        except BaseException:
            self.recover()
            raise
        (self.private / "transaction.json").unlink()
        sync_directory(self.private)
