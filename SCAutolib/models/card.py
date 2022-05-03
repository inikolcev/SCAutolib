from traceback import format_exc

import time

from pathlib import Path

from SCAutolib import run, logger


class Card:
    uri: str = None
    user = None  # FIXME: add user type when it would be ready

    def __int__(self, cert: Path, key: Path, user):
        self.user = user

    def _set_uri(self): ...

    def insert(self): ...

    def remove(self): ...

    def enroll(self): ...


class VirtualCard(Card):
    softhsm2_conf: Path = None
    _service_name = None

    def __int__(self, cert: Path, key: Path, user, insert: bool = False):
        """
        Initialise virtual smart card. Constructor of the base class is also
        used.

        :param cert: Path to the certificate for this card
        :type cert: pathlib.Path
        :param key: Path to private key for this card
        :type key: pathlib.Path
        :param user: User of this card
        :type user: dict
        :param insert: If the card should be inserted on entering the context
            manger. Default False.
        :type insert: bool
        :return:
        """
        super(Card, self).__init__(cert, key, user)
        self._service_name = f"virt_cacard_{self.user.username}"
        self._insert = insert

    def __enter__(self):
        """
        Start of context manger for virtual smart card. The card would be
        inserted if ``insert`` parameter in constructor is specified.

        :return: self
        """
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
        Remove virtual smart card by stopping corresponding service.
        """
        cmd = ["systemctl", "stop", self._service_name]
        out = run(cmd, check=True)
        time.sleep(2)  # to prevent error with fast restarting of the service
        logger.info(f"Smart card {self._service_name} is removed")
        return out

    def enroll(self): ...
