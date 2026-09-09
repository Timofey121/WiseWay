"""Trusted local CLI administration for synthetic local accounts."""

from __future__ import annotations

import getpass
import re
import sys

from .audit import emit
from .auth import HASHER
from .common import ApiError, uid

_LOGIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_ROLES = {"WORKER", "ADMIN"}


def _validate(login, display_name=None, role=None, password=None):
    if not isinstance(login, str) or not _LOGIN.fullmatch(login):
        raise ApiError("VALIDATION_ERROR", "Логин должен содержать 1…64 латинских символа, цифры или ._-.")
    if display_name is not None and (
        not isinstance(display_name, str) or not display_name.strip() or len(display_name) > 200
    ):
        raise ApiError("VALIDATION_ERROR", "Отображаемое имя должно содержать 1…200 символов.")
    if role is not None and role not in _ROLES:
        raise ApiError("VALIDATION_ERROR", "Роль должна быть WORKER или ADMIN.")
    if password is not None and (
        not isinstance(password, str) or len(password) < 12 or len(password.encode("utf-8")) > 1024
    ):
        raise ApiError(
            "VALIDATION_ERROR", "Пароль должен содержать не менее 12 символов и не более 1024 байт UTF-8."
        )


class AccountService:
    def __init__(self, ctx):
        self.ctx = ctx

    def _admin(self, tx, login):
        admin = next(
            (
                u
                for u in tx.list("user")
                if u["actor"]["login"] == login and u["actor"]["role"] == "ADMIN" and not u["blocked"]
            ),
            None,
        )
        if admin is None:
            raise ApiError("FORBIDDEN", "Требуется активная локальная учётная запись администратора.", 403)
        return admin

    @staticmethod
    def _target(tx, login):
        target = next((u for u in tx.list("user") if u["actor"]["login"] == login), None)
        if target is None:
            raise ApiError("NOT_FOUND", "Учётная запись не найдена.", 404)
        return target

    @staticmethod
    def _revoke(tx, user_id):
        tx.connection.execute(
            "DELETE FROM objects WHERE kind='session' AND json_extract(body, '$.user_id')=?", (user_id,)
        )

    def create_user(self, actor_login, login, display_name, role, password):
        _validate(login, display_name, role, password)
        with self.ctx.store.transaction() as tx:
            actor = self._admin(tx, actor_login)["actor"]
            if any(u["actor"]["login"].casefold() == login.casefold() for u in tx.list("user")):
                raise ApiError("VALIDATION_ERROR", "Логин уже используется.")
            user = {
                "actor": {
                    "user_id": uid("user"),
                    "login": login,
                    "display_name": display_name.strip(),
                    "role": role,
                },
                "password_hash": HASHER.hash(password),
                "blocked": False,
            }
            tx.put("user", user["actor"]["user_id"], user)
            emit(
                tx,
                actor,
                "ACCOUNT_CREATED",
                uid("request"),
                now=self.ctx.settings.clock(),
                comment="Created account: " + login,
            )
            return user["actor"]

    def reset_password(self, actor_login, login, password):
        _validate(login, password=password)
        with self.ctx.store.transaction() as tx:
            actor, target = self._admin(tx, actor_login)["actor"], self._target(tx, login)
            target["password_hash"] = HASHER.hash(password)
            tx.put("user", target["actor"]["user_id"], target)
            self._revoke(tx, target["actor"]["user_id"])
            emit(
                tx,
                actor,
                "PASSWORD_CHANGED",
                uid("request"),
                now=self.ctx.settings.clock(),
                comment="Password changed: " + login,
            )

    def block_user(self, actor_login, login):
        _validate(login)
        with self.ctx.store.transaction() as tx:
            actor, target = self._admin(tx, actor_login)["actor"], self._target(tx, login)
            if (
                target["actor"]["role"] == "ADMIN"
                and not target["blocked"]
                and sum(u["actor"]["role"] == "ADMIN" and not u["blocked"] for u in tx.list("user")) <= 1
            ):
                raise ApiError(
                    "VALIDATION_ERROR", "Нельзя заблокировать последнего активного администратора."
                )
            target["blocked"] = True
            tx.put("user", target["actor"]["user_id"], target)
            self._revoke(tx, target["actor"]["user_id"])
            emit(
                tx,
                actor,
                "ACCOUNT_BLOCKED",
                uid("request"),
                now=self.ctx.settings.clock(),
                comment="Blocked account: " + login,
            )

    def unblock_user(self, actor_login, login):
        _validate(login)
        with self.ctx.store.transaction() as tx:
            actor, target = self._admin(tx, actor_login)["actor"], self._target(tx, login)
            target["blocked"] = False
            tx.put("user", target["actor"]["user_id"], target)
            emit(
                tx,
                actor,
                "ACCOUNT_UNBLOCKED",
                uid("request"),
                now=self.ctx.settings.clock(),
                comment="Unblocked account: " + login,
            )


def register_commands(subparsers):
    for command, help_text in (
        ("create-user", "Create a local account"),
        ("reset-password", "Reset a local password"),
        ("unblock-user", "Unblock a local account"),
        ("block-user", "Block a local account"),
    ):
        parser = subparsers.add_parser(command, help=help_text)
        parser.add_argument("login")
        parser.add_argument("--actor", required=True, help="Active local ADMIN login for audit attribution")
        if command == "create-user":
            parser.add_argument("--display-name", required=True)
            parser.add_argument("--role", required=True, choices=sorted(_ROLES))
        if command in {"create-user", "reset-password"}:
            parser.add_argument("--password-stdin", action="store_true")


def execute(args, ctx, parser):
    if args.command not in {"create-user", "reset-password", "unblock-user", "block-user"}:
        return False
    service = AccountService(ctx)
    password = None
    if args.command in {"create-user", "reset-password"}:
        password = sys.stdin.readline().rstrip("\n") if args.password_stdin else getpass.getpass("Password: ")
    try:
        if args.command == "create-user":
            service.create_user(args.actor, args.login, args.display_name, args.role, password)
            print("Account created.")
        elif args.command == "reset-password":
            service.reset_password(args.actor, args.login, password)
            print("Password changed; existing sessions were revoked.")
        elif args.command == "unblock-user":
            service.unblock_user(args.actor, args.login)
            print("Account unblocked; sign in again to create a new session.")
        else:
            service.block_user(args.actor, args.login)
            print("Account blocked; its sessions were revoked.")
    except ApiError as error:
        parser.error(error.message)
    return True
