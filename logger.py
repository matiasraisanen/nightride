import logging
import os

# Logger is a class that handles logging to a file.
#
# Usage:
# from logger import Logger
# self.logger = Logger(
#     module_name=__name__,
#     log_file="main.log",
#     log_level=logging.DEBUG,
#     delete_old_logfile=True,
# )
# self.logger.log.debug("This is debug")
# self.logger.log.info("This is info")


class Logger:
    def __init__(
        self,
        module_name: str,
        log_level: int = logging.INFO,
        streamhandler: bool = False,
        filehandler: bool = False,
        log_file: str = "debug.log",
        delete_old_logfile: bool = True,
    ):
        self.log_file = log_file
        self.log_level = log_level
        self.log_level_name = logging.getLevelName(log_level)
        self.module_name = module_name

        self.log = logging.getLogger(module_name)
        self.log.setLevel(log_level)

        # Only root level logger should delete old log file.
        if module_name == "__main__" and delete_old_logfile:
            self.delete_old_logfile()

        # Finally create the handlers and the class is ready to be used.
        if filehandler:
            self.create_file_handler()
        if streamhandler:
            self.create_stream_handler()

    def create_file_handler(self):
        formatter = logging.Formatter(
            fmt="[%(asctime)s]-[%(name)s]-[%(levelname)s]: %(message)s",
            datefmt="%H:%M:%S",
        )

        fileHandler = logging.FileHandler(self.log_file)
        fileHandler.setFormatter(formatter)
        fileHandler.setLevel(self.log_level)
        self.log.addHandler(fileHandler)
        self.log.info(f"Initializing {self.module_name} module")
        self.log.info(f"Logging to [{self.log_file}] at level [{self.log_level_name}]")

    def create_stream_handler(self):
        formatter = logging.Formatter(
            fmt="[%(asctime)s]-[%(name)s]-[%(levelname)s]: %(message)s",
            datefmt="%H:%M:%S",
        )

        streamHandler = logging.StreamHandler()
        streamHandler.setFormatter(formatter)
        streamHandler.setLevel(self.log_level)
        self.log.addHandler(streamHandler)
        self.log.info(f"Initializing {self.module_name} module")
        self.log.info(f"Logging to [{self.log_file}] at level [{self.log_level_name}]")

    def delete_old_logfile(self):
        if os.path.exists(self.log_file):
            os.remove(self.log_file)
        else:
            pass
