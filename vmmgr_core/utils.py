import logging
import os
import subprocess

from .constants import AUDIT_LOG

logging.basicConfig(
    filename=AUDIT_LOG,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def audit(msg):
    logging.info(msg)


def run_cmd(cmd):
    return subprocess.run(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def get_term_width():
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80
