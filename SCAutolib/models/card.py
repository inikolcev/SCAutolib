"""
This module implements classes for communication with different types of cards
that we are using in the library. Those types are: virtual smart card, real
(physical) smart card in standard reader, cards in the removinator.
"""
import re

import time
from pathlib import Path
from shutil import copy
from traceback import format_exc

from SCAutolib import run, logger, TEMPLATES_DIR


class Card:
    """
    Interface for child classes. All child classes will rewrite common methods+
    based on the type of the card.
    """
    uri: str = None
    user = None  # FIXME: add user type when it would be ready

    def _set_uri(self):
        """
        Sets card URI for the object.
        """
        ...

    def insert(self):
        """
        Insert the card.
        """
        ...

    def remove(self):
        """
        Remove the card.
        """
        ...

    def enroll(self):
        """
        Enroll the card (upload a certificate and a key on it)
        """
        ...


class VirtualCard(Card):
    """
    This class provides method for manipulating with virtual smart card. Virtual
    smart card by itself is represented by the systemd service in the system
    The card corresponds to some user, so providing the user is essential for
    correct functioning of methods for the virtual smart card.

    Card root directory has to be created before calling any method
    """

    _service_name: str = None
    _service_location: Path = None
    _softhsm2_conf: Path = None
    _nssdb: Path = None
    _template: Path = Path(TEMPLATES_DIR, "virt_cacard.service")

    def __int__(self, cert: Path, key: Path, user, insert: bool = False):
        """
        Initialise virtual smart card. Constructor of the base class is also
        used.

        :param cert: Path to the certificate for this card
        :type cert: pathlib.Path
        :param key: Path to private key for this card
        :type key: pathlib.Path
        :param user: User of this card
        :type user: User
        :param insert: If the card should be inserted on entering the context
            manger. Default False.
        :type insert: bool
        :return:
        """
        self.user = user
        assert self.user.card_dir.exists(), "Card root directory doesn't exists"

        self._private_key = key
        self._cert = cert

        self._service_name = f"virt_cacard_{self.user.username}"
        self._insert = insert
        # self._softhsm2_conf = SoftHSM2Conf(
        #   self.user.card_dir.joinpath("softhsm2.conf"))
        # self._softhsm2_conf = self.user.card_dir.joinpath("softhsm2.conf")
        self._nssdb = self.user.card_dir.joinpath("db")
        self._service_location = Path(
            f"/etc/systemd/system/{self._service_name}")

    def __enter__(self):
        """
        Start of context manger for virtual smart card. The card would be
        inserted if ``insert`` parameter in constructor is specified.

        :return: self
        """
        assert self._service_location.exists(), \
            "Service for virtual sc doesn't exists."
        if self._insert:
            self.insert()
        return self

    def __exit__(self, exp_type, exp_value, exp_traceback):
        """
        End of context manager for virtual smart card. If any exception was
        raised in the current context, it would be logged as an error.

        :param exp_type: Type of the exception
        :param exp_value: Value for the exception
        :param exp_traceback: Traceback of the exception
        """
        if exp_type is not None:
            logger.error("Exception in virtual smart card context")
            logger.error(format_exc())
        self.remove()

    @property
    def softhsm2_conf(self):
        return self._softhsm2_conf

    @softhsm2_conf.setter
    def softhsm2_conf(self, path: Path):
        assert path.exists(), "File doesn't exist"
        self._softhsm2_conf = path

    def insert(self):
        """
        Insert virtual smart card by starting the corresponding service.
        """
        cmd = ["systemctl", "start", self._service_name]
        out = run(cmd, check=True)
        time.sleep(2)  # to prevent error with fast restarting of the service
        logger.info(f"Smart card {self._service_name} is inserted")
        return out

    def remove(self):
        """
        Remove the virtual card by stopping the service
        """
        cmd = ["systemctl", "stop", self._service_name]
        out = run(cmd, check=True)
        time.sleep(2)  # to prevent error with fast restarting of the service
        logger.info(f"Smart card {self._service_name} is removed")
        return out

    def enroll(self):
        """
        Upload certificate and private key to the virtual smart card (upload to
        NSS database) with pkcs11-tool.
        """
        cmd = ["pkcs11-tool", "--module", "libsofthsm2.so", "--slot-index",
               0, "-w", self._private_key, "-y", "privkey", "--label",
               f"'{self.user.username}'", "-p", self.user.pin, "--set-id", 0,
               "-d", 0]
        run(cmd, env={"SOFTHSM2_CONF": self._softhsm2_conf})
        logger.debug(
            f"User key {self._private_key} is added to virtual smart card")

        cmd = ['pkcs11-tool', '--module', 'libsofthsm2.so', '--slot-index', 0,
               '-w', self._cert, '-y', 'cert', '-p', self.user.pin,
               '--label', f"'{self.user.username}'", '--set-id', 0, '-d', 0]
        run(cmd, env={"SOFTHSM2_CONF": self._softhsm2_conf})
        logger.debug(
            f"User certificate {self._cert} is added to virtual smart card")

    def create(self):
        """
        Creates SoftHSM2 token and systemd service for virtual smart card.
        Directory for NSS database is created in this method as separate DB is
        required for each virtual card.
        """

        assert self._softhsm2_conf is not None

        p11lib = "/usr/lib64/pkcs11/libsofthsm2.so"
        # Initialize SoftHSM2 token. An error would be raised if token with same
        # label would be created.
        cmd = ["softhsm2-util", "--init-token", "--free", "--label",
               self.user.username, "--so-pin", "12345678",
               "--pin", self.user.pin]
        run(cmd, env={"SOFTHSM2_CONF": self._softhsm2_conf}, check=True)
        logger.debug(
            f"SoftHSM token is initialized with label '{self.user.username}'")

        # Initialize NSS db
        self._nssdb.mkdir(exist_ok=True)
        run(f"modutil -create -dbdir sql:{self._nssdb} -force", check=True)
        logger.debug(f"NSS database is initialized in {self._nssdb}")

        out = run(f"modutil -list -dbdir sql:{self._nssdb}")
        if "library name: p11-kit-proxy.so" not in out.stdout:
            run(["modutil", "-force", "-add", 'SoftHSM PKCS#11', "-dbdir",
                 f"sql:{self._nssdb}", "-libfile", p11lib])
            logger.debug("SoftHSM support is added to NSS database")

        # Create systemd service
        copy(self._template, self._service_location)
        with self._service_location.open("r+") as f:
            content = f.read().format(username=self.user.username,
                                      softhsm2_conf_path=self._softhsm2_conf,
                                      card_dir=self.user.card_dir)
            f.write(content)
        run("systemctl daemon-reload")

        # To get URI of the card, the card has to be inserted
        with self:
            self.insert()
            self._set_uri()

    def _set_uri(self):
        cmd = ["p11tool", "--list-token-urls"]
        out = run(cmd).stdout
        pattern = r"(pkcs11:model=PKCS%2315%20emulated;" \
                  r"manufacturer=Common%20Access%20Card;serial=.*)"
        urls = re.findall(pattern, out)
        assert len(urls) == 1, "More URLs are matched"
        self.uri = urls[0]
