import logging
import os
import time

# Logger is a class that handles logging to a file.
#
# Usage:
# from logger import Logger
# self.logger = Logger(
#     module_name=__name__,
#     log_file="main.log",
#     log_level=logging.DEBUG,
#     filehandler=True,
# )
# self.logger.log.debug("This is debug")
# self.logger.log.info("This is info")
#
# The log file is kept across restarts. Entries older than a day are dropped when the player starts, and
# if the file grows past MAX_BYTES (say, a radio left on for days with --debug), the oldest half is dropped.

# Log entries older than this are dropped at start
KEEP_SECONDS = 24 * 60 * 60
# Past this size, the oldest half of the log is dropped
MAX_BYTES = 1024 * 1024
# How many entries are written between checks of the file's size
CHECK_EVERY = 100
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# One handler per log file, shared by every module's logger, so only one file handle writes to it
_handlers = {}


class Logger:
    def __init__(
        self,
        module_name: str,
        log_level: int = logging.INFO,
        streamhandler: bool = False,
        filehandler: bool = False,
        log_file: str = "debug.log",
    ):
        self.log_file = log_file
        self.log_level = log_level
        self.module_name = module_name

        self.log = logging.getLogger(module_name)
        self.log.setLevel(log_level)

        if filehandler:
            self.add_handler(file_handler(log_file))
        if streamhandler:
            self.add_handler(logging.StreamHandler())

    def add_handler(self, handler):
        if handler in self.log.handlers:
            return
        handler.setFormatter(
            logging.Formatter(fmt="[%(asctime)s]-[%(name)s]-[%(levelname)s]: %(message)s", datefmt=TIME_FORMAT)
        )
        self.log.addHandler(handler)


def file_handler(path):
    if path not in _handlers:
        _handlers[path] = TrimmedFileHandler(path)
    return _handlers[path]


class TrimmedFileHandler(logging.FileHandler):
    def __init__(self, path):
        drop_old_entries(path)
        super().__init__(path, encoding="utf-8")
        self.written = 0

    def emit(self, record):
        # logging calls this with the handler's lock held, so trimming can't mix with writing
        super().emit(record)
        self.written += 1
        if self.written % CHECK_EVERY == 0:
            self.trim_if_big()

    def trim_if_big(self):
        try:
            if os.path.getsize(self.baseFilename) <= MAX_BYTES:
                return
        except OSError:
            return
        # Close the file while it is rewritten. The next entry opens it again.
        if self.stream:
            self.stream.close()
            self.stream = None
        keep_newest(self.baseFilename, MAX_BYTES // 2)


def entry_time(line):
    # The time a "[2026-11-22 23:40:01]-..." line was written, or None for other lines (e.g. a traceback's)
    try:
        return time.mktime(time.strptime(line[1:20], TIME_FORMAT)) if line.startswith("[") else None
    except ValueError:
        return None


def drop_old_entries(path):
    cutoff = time.time() - KEEP_SECONDS
    lines = read_lines(path)
    # Keep everything from the first recent entry on. Lines without a time go with the entry above them.
    # Entries from older versions, which had no date, count as old.
    first = next((i for i, line in enumerate(lines) if (entry_time(line) or 0) >= cutoff), len(lines))
    if first:
        write_lines(path, lines[first:])


def keep_newest(path, max_bytes):
    lines = read_lines(path)
    size = sum(len(line.encode("utf-8")) for line in lines)
    first = 0
    while first < len(lines) and size > max_bytes:
        size -= len(lines[first].encode("utf-8"))
        first += 1
    # Start at an entry, not in the middle of one
    while first < len(lines) and entry_time(lines[first]) is None:
        first += 1
    write_lines(path, lines[first:])


def read_lines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except OSError:
        return []


def write_lines(path, lines):
    # Write a new file and swap it in. If that fails (another player has the file open on Windows),
    # the log just stays as it is.
    temp_file = path + ".tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            f.writelines(lines)
        os.replace(temp_file, path)
    except OSError:
        pass
