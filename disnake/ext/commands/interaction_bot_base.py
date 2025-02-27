# The MIT License (MIT)

# Copyright (c) 2021-present EQUENOS

# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

from __future__ import annotations

import asyncio
import sys
import traceback
import warnings
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Coroutine,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    TypeVar,
    Union,
)

import disnake
from disnake.app_commands import (
    ApplicationCommand,
    Option,
    PartialGuildApplicationCommandPermissions,
)
from disnake.custom_warnings import ConfigWarning, SyncWarning
from disnake.enums import ApplicationCommandType

from . import errors
from .base_core import InvokableApplicationCommand
from .cog import Cog
from .common_bot_base import CommonBotBase
from .context import Context
from .ctx_menus_core import (
    InvokableMessageCommand,
    InvokableUserCommand,
    message_command,
    user_command,
)
from .errors import CommandRegistrationError
from .slash_core import InvokableSlashCommand, SubCommand, SubCommandGroup, slash_command

if TYPE_CHECKING:

    from typing_extensions import Concatenate, ParamSpec

    from disnake.interactions import ApplicationCommandInteraction

    from ._types import Check, CoroFunc

    ApplicationCommandInteractionT = TypeVar(
        "ApplicationCommandInteractionT", bound=ApplicationCommandInteraction, covariant=True
    )
    AnyMessageCommandInter = Any  # Union[ApplicationCommandInteraction, UserCommandInteraction]
    AnyUserCommandInter = Any  # Union[ApplicationCommandInteraction, UserCommandInteraction]

    P = ParamSpec("P")

__all__ = ("InteractionBotBase",)

MISSING: Any = disnake.utils.MISSING

T = TypeVar("T")
CFT = TypeVar("CFT", bound="CoroFunc")
CXT = TypeVar("CXT", bound="Context")


def _app_commands_diff(
    new_commands: Iterable[ApplicationCommand],
    old_commands: Iterable[ApplicationCommand],
) -> Dict[str, List[ApplicationCommand]]:
    new_cmds = {cmd.name: cmd for cmd in new_commands}
    old_cmds = {cmd.name: cmd for cmd in old_commands}

    diff = {
        "no_changes": [],
        "upsert": [],
        "edit": [],
        "delete": [],
        "change_type": [],
    }

    for name, new_cmd in new_cmds.items():
        old_cmd = old_cmds.get(name)
        if old_cmd is None:
            diff["upsert"].append(new_cmd)
        elif old_cmd.type != new_cmd.type:
            diff["change_type"].append(new_cmd)
        elif new_cmd._always_synced:
            diff["no_changes"].append(old_cmd)
            continue
        elif new_cmd != old_cmd:
            diff["edit"].append(new_cmd)
        else:
            diff["no_changes"].append(new_cmd)

    for name, old_cmd in old_cmds.items():
        if name not in new_cmds:
            diff["delete"].append(old_cmd)

    return diff


def _show_diff(diff: Dict[str, List[ApplicationCommand]], line_prefix: str = "") -> None:
    to_upsert = f",\n{line_prefix}    ".join(str(cmd) for cmd in diff["upsert"]) or "-"
    to_edit = f",\n{line_prefix}    ".join(str(cmd) for cmd in diff["edit"]) or "-"
    to_delete = f",\n{line_prefix}    ".join(str(cmd) for cmd in diff["delete"]) or "-"
    change_type = f",\n{line_prefix}    ".join(str(cmd) for cmd in diff["change_type"]) or "-"
    no_changes = f",\n{line_prefix}    ".join(str(cmd) for cmd in diff["no_changes"]) or "-"
    print(
        f"{line_prefix}To upsert:",
        f"    {to_upsert}",
        f"To edit:",
        f"    {to_edit}",
        f"To delete:",
        f"    {to_delete}",
        f"Type migration:",
        f"    {change_type}",
        f"No changes:",
        f"    {no_changes}",
        sep=f"\n{line_prefix}",
        end="\n\n",
    )


class InteractionBotBase(CommonBotBase):
    def __init__(
        self,
        *,
        sync_commands: bool = True,
        sync_commands_debug: bool = False,
        sync_commands_on_cog_unload: bool = True,
        sync_permissions: bool = False,
        test_guilds: Sequence[int] = None,
        **options: Any,
    ):
        super().__init__(**options)

        self._test_guilds: Optional[Sequence[int]] = test_guilds
        self._sync_commands: bool = sync_commands
        self._sync_commands_debug: bool = sync_commands_debug
        self._sync_commands_on_cog_unload = sync_commands_on_cog_unload
        self._sync_permissions: bool = sync_permissions
        self._sync_queued: bool = False

        self._slash_command_checks = []
        self._slash_command_check_once = []
        self._user_command_checks = []
        self._user_command_check_once = []
        self._message_command_checks = []
        self._message_command_check_once = []

        self._before_slash_command_invoke = None
        self._after_slash_command_invoke = None
        self._before_user_command_invoke = None
        self._after_user_command_invoke = None
        self._before_message_command_invoke = None
        self._after_message_command_invoke = None

        self.all_slash_commands: Dict[str, InvokableSlashCommand] = {}
        self.all_user_commands: Dict[str, InvokableUserCommand] = {}
        self.all_message_commands: Dict[str, InvokableMessageCommand] = {}

        self._schedule_app_command_preparation()

    @property
    def application_commands(self) -> Set[InvokableApplicationCommand]:
        result = set()
        for cmd in self.all_slash_commands.values():
            result.add(cmd)
        for cmd in self.all_user_commands.values():
            result.add(cmd)
        for cmd in self.all_message_commands.values():
            result.add(cmd)
        return result

    @property
    def slash_commands(self) -> Set[InvokableSlashCommand]:
        return set(self.all_slash_commands.values())

    @property
    def user_commands(self) -> Set[InvokableUserCommand]:
        return set(self.all_user_commands.values())

    @property
    def message_commands(self) -> Set[InvokableMessageCommand]:
        return set(self.all_message_commands.values())

    def add_slash_command(self, slash_command: InvokableSlashCommand) -> None:
        """Adds an :class:`.InvokableSlashCommand` into the internal list of slash commands.

        This is usually not called, instead the :meth:`.slash_command` or
        shortcut decorators are used.

        Parameters
        -----------
        slash_command: :class:`InvokableSlashCommand`
            The slash command to add.

        Raises
        -------
        :exc:`.CommandRegistrationError`
            If the slash command is already registered.
        TypeError
            If the slash command passed is not an instance of :class:`.InvokableSlashCommand`.
        """

        if not isinstance(slash_command, InvokableSlashCommand):
            raise TypeError("The slash_command passed must be an instance of InvokableSlashCommand")

        if slash_command.name in self.all_slash_commands:
            raise CommandRegistrationError(slash_command.name)

        self.all_slash_commands[slash_command.name] = slash_command

    def add_user_command(self, user_command: InvokableUserCommand) -> None:
        """Adds an :class:`.InvokableUserCommand` into the internal list of user commands.

        This is usually not called, instead the :meth:`.user_command` or
        shortcut decorators are used.

        Parameters
        -----------
        user_command: :class:`InvokableUserCommand`
            The user command to add.

        Raises
        -------
        :exc:`.CommandRegistrationError`
            If the user command is already registered.
        TypeError
            If the user command passed is not an instance of :class:`.InvokableUserCommand`.
        """

        if not isinstance(user_command, InvokableUserCommand):
            raise TypeError("The user_command passed must be an instance of InvokableUserCommand")

        if user_command.name in self.all_user_commands:
            raise CommandRegistrationError(user_command.name)

        self.all_user_commands[user_command.name] = user_command

    def add_message_command(self, message_command: InvokableMessageCommand) -> None:
        """Adds an :class:`.InvokableMessageCommand` into the internal list of message commands.

        This is usually not called, instead the :meth:`.message_command` or
        shortcut decorators are used.

        Parameters
        -----------
        message_command: :class:`InvokableMessageCommand`
            The message command to add.

        Raises
        -------
        :exc:`.CommandRegistrationError`
            If the message command is already registered.
        TypeError
            If the message command passed is not an instance of :class:`.InvokableMessageCommand`.
        """

        if not isinstance(message_command, InvokableMessageCommand):
            raise TypeError(
                "The message_command passed must be an instance of InvokableMessageCommand"
            )

        if message_command.name in self.all_message_commands:
            raise CommandRegistrationError(message_command.name)

        self.all_message_commands[message_command.name] = message_command

    def remove_slash_command(self, name: str) -> Optional[InvokableSlashCommand]:
        """Remove a :class:`.InvokableSlashCommand` from the internal list
        of slash commands.

        Parameters
        -----------
        name: :class:`str`
            The name of the command to remove.

        Returns
        --------
        Optional[:class:`.InvokableSlashCommand`]
            The command that was removed. If the name is not valid then
            ``None`` is returned instead.
        """
        command = self.all_slash_commands.pop(name, None)
        if command is None:
            return None
        return command

    def remove_user_command(self, name: str) -> Optional[InvokableUserCommand]:
        """Remove a :class:`.InvokableUserCommand` from the internal list
        of user commands.

        Parameters
        -----------
        name: :class:`str`
            The name of the command to remove.

        Returns
        --------
        Optional[:class:`.InvokableUserCommand`]
            The command that was removed. If the name is not valid then
            ``None`` is returned instead.
        """
        command = self.all_user_commands.pop(name, None)
        if command is None:
            return None
        return command

    def remove_message_command(self, name: str) -> Optional[InvokableMessageCommand]:
        """Remove a :class:`.InvokableMessageCommand` from the internal list
        of message commands.

        Parameters
        -----------
        name: :class:`str`
            The name of the command to remove.

        Returns
        --------
        Optional[:class:`.InvokableMessageCommand`]
            The command that was removed. If the name is not valid then
            ``None`` is returned instead.
        """
        command = self.all_message_commands.pop(name, None)
        if command is None:
            return None
        return command

    def get_slash_command(
        self, name: str
    ) -> Optional[Union[InvokableSlashCommand, SubCommandGroup, SubCommand]]:
        """Works like ``Bot.get_command``, but for slash commands.

        If the name contains spaces, then it will assume that you are looking for a :class:`.SubCommand` or
        a :class:`.SubCommandGroup`.
        e.g: ``'foo bar'`` will get the sub command group, or the sub command ``bar`` of the top-level slash command
        ``foo`` if found, otherwise ``None``.

        Parameters
        -----------
        name: :class:`str`
            The name of the slash command to get.

        Returns
        --------
        Optional[Union[:class:`InvokableSlashCommand`, :class:`SubCommandGroup`, :class:`SubCommand`]]
            The slash command that was requested. If not found, returns ``None``.
        """

        if not isinstance(name, str):
            raise TypeError(f"Expected name to be str, not {name.__class__}")

        chain = name.split()
        slash = self.all_slash_commands.get(chain[0])
        if slash is None:
            return None

        if len(chain) == 1:
            return slash
        elif len(chain) == 2:
            return slash.children.get(chain[1])
        elif len(chain) == 3:
            group = slash.children.get(chain[1])
            if isinstance(group, SubCommandGroup):
                return group.children.get(chain[2])

    def get_user_command(self, name: str) -> Optional[InvokableUserCommand]:
        """Get a :class:`.InvokableUserCommand` from the internal list
        of commands.

        Parameters
        -----------
        name: :class:`str`
            The name of the user command to get.

        Returns
        --------
        Optional[:class:`InvokableUserCommand`]
            The user command that was requested. If not found, returns ``None``.
        """
        return self.all_user_commands.get(name)

    def get_message_command(self, name: str) -> Optional[InvokableMessageCommand]:
        """Get a :class:`.InvokableMessageCommand` from the internal list
        of commands.

        Parameters
        -----------
        name: :class:`str`
            The name of the message command to get.

        Returns
        --------
        Optional[:class:`InvokableMessageCommand`]
            The message command that was requested. If not found, returns ``None``.
        """
        return self.all_message_commands.get(name)

    def slash_command(
        self,
        *,
        name: str = None,
        description: str = None,
        options: List[Option] = None,
        default_permission: bool = True,
        guild_ids: Sequence[int] = None,
        connectors: Dict[str, str] = None,
        auto_sync: bool = True,
        **kwargs,
    ) -> Callable[
        [
            Union[
                Callable[Concatenate[Cog, ApplicationCommandInteractionT, P], Coroutine],
                Callable[Concatenate[ApplicationCommandInteractionT, P], Coroutine],
            ]
        ],
        InvokableSlashCommand,
    ]:
        """
        A shortcut decorator that invokes :func:`.slash_command` and adds it to
        the internal command list.

        Parameters
        ----------
        auto_sync: :class:`bool`
            whether to automatically register the command or not. Defaults to ``True``
        name: :class:`str`
            name of the slash command you want to respond to (equals to function name by default).
        description: :class:`str`
            the description of the slash command. It will be visible in Discord.
        options: List[:class:`.Option`]
            the list of slash command options. The options will be visible in Discord.
            This is the old way of specifying options. Consider using :ref:`param_syntax` instead.
        default_permission: :class:`bool`
            whether the command is enabled by default when the app is added to a guild.
        guild_ids: List[:class:`int`]
            if specified, the client will register a command in these guilds.
            Otherwise this command will be registered globally in ~1 hour.
        connectors: Dict[:class:`str`, :class:`str`]
            binds function names to option names. If the name
            of an option already matches the corresponding function param,
            you don't have to specify the connectors. Connectors template:
            ``{"option-name": "param_name", ...}``.
            If you're using :ref:`param_syntax`, you don't need to specify this.

        Returns
        --------
        Callable[..., :class:`InvokableSlashCommand`]
            A decorator that converts the provided method into a InvokableSlashCommand, adds it to the bot, then returns it.
        """

        def decorator(
            func: Union[
                Callable[Concatenate[Cog, ApplicationCommandInteractionT, P], Coroutine],
                Callable[Concatenate[ApplicationCommandInteractionT, P], Coroutine],
            ]
        ) -> InvokableSlashCommand:
            result = slash_command(
                name=name,
                description=description,
                options=options,
                default_permission=default_permission,
                guild_ids=guild_ids,
                connectors=connectors,
                auto_sync=auto_sync,
                **kwargs,
            )(func)
            self.add_slash_command(result)
            return result

        return decorator

    def user_command(
        self,
        *,
        name: str = None,
        default_permission: bool = True,
        guild_ids: Sequence[int] = None,
        auto_sync: bool = True,
        **kwargs,
    ) -> Callable[
        [
            Union[
                Callable[Concatenate[Cog, ApplicationCommandInteractionT, P], Coroutine],
                Callable[Concatenate[ApplicationCommandInteractionT, P], Coroutine],
            ]
        ],
        InvokableUserCommand,
    ]:
        """
        A shortcut decorator that invokes :func:`.user_command` and adds it to
        the internal command list.

        Parameters
        ----------
        auto_sync: :class:`bool`
            whether to automatically register the command or not. Defaults to ``True``.
        name: :class:`str`
            name of the user command you want to respond to (equals to function name by default).
        default_permission: :class:`bool`
            whether the command is enabled by default when the app is added to a guild.
        guild_ids: List[:class:`int`]
            if specified, the client will register the command in these guilds.
            Otherwise this command will be registered globally in ~1 hour.

        Returns
        --------
        Callable[..., :class:`InvokableUserCommand`]
            A decorator that converts the provided method into a InvokableUserCommand, adds it to the bot, then returns it.
        """

        def decorator(
            func: Union[
                Callable[Concatenate[Cog, ApplicationCommandInteractionT, P], Coroutine],
                Callable[Concatenate[ApplicationCommandInteractionT, P], Coroutine],
            ]
        ) -> InvokableUserCommand:
            result = user_command(
                name=name,
                default_permission=default_permission,
                guild_ids=guild_ids,
                auto_sync=auto_sync,
                **kwargs,
            )(func)
            self.add_user_command(result)
            return result

        return decorator

    def message_command(
        self,
        *,
        name: str = None,
        default_permission: bool = True,
        guild_ids: Sequence[int] = None,
        auto_sync: bool = True,
        **kwargs,
    ) -> Callable[
        [
            Union[
                Callable[Concatenate[Cog, AnyMessageCommandInter, P], Coroutine],
                Callable[Concatenate[AnyMessageCommandInter, P], Coroutine],
            ]
        ],
        InvokableMessageCommand,
    ]:
        """
        A shortcut decorator that invokes :func:`.message_command` and adds it to
        the internal command list.

        Parameters
        ----------
        auto_sync: :class:`bool`
            whether to automatically register the command or not. Defaults to ``True``
        name: :class:`str`
            name of the message command you want to respond to (equals to function name by default).
        default_permission: :class:`bool`
            whether the command is enabled by default when the app is added to a guild.
        guild_ids: List[:class:`int`]
            if specified, the client will register the command in these guilds.
            Otherwise this command will be registered globally in ~1 hour.

        Returns
        --------
        Callable[..., :class:`InvokableUserCommand`]
            A decorator that converts the provided method into a InvokableUserCommand, adds it to the bot, then returns it.
        """

        def decorator(
            func: Union[
                Callable[Concatenate[Cog, ApplicationCommandInteractionT, P], Coroutine],
                Callable[Concatenate[ApplicationCommandInteractionT, P], Coroutine],
            ]
        ) -> InvokableMessageCommand:
            result = message_command(
                name=name,
                default_permission=default_permission,
                guild_ids=guild_ids,
                auto_sync=auto_sync,
                **kwargs,
            )(func)
            self.add_message_command(result)
            return result

        return decorator

    # command synchronisation

    def _ordered_unsynced_commands(
        self, test_guilds: Sequence[int] = None
    ) -> Tuple[List[ApplicationCommand], Dict[int, List[ApplicationCommand]]]:
        global_cmds = []
        guilds = {}
        for cmd in self.application_commands:
            if not cmd.auto_sync:
                cmd.body._always_synced = True
            guild_ids = cmd.guild_ids or test_guilds
            if guild_ids is None:
                global_cmds.append(cmd.body)
            else:
                for guild_id in guild_ids:
                    if guild_id not in guilds:
                        guilds[guild_id] = [cmd.body]
                    else:
                        guilds[guild_id].append(cmd.body)
        return global_cmds, guilds

    async def _cache_application_commands(self) -> None:
        if not isinstance(self, disnake.Client):
            raise NotImplementedError(f"This method is only usable in disnake.Client subclasses")

        _, guilds = self._ordered_unsynced_commands(self._test_guilds)

        # Here we only cache global commands and commands from guilds that are spcified in the code.
        # They're collected from the "test_guilds" kwarg of commands.InteractionBotBase
        # and the "guild_ids" kwarg of the decorators. This is the only way to avoid rate limits.
        # If we cache guild commands from everywhere, the limit of invalid requests gets exhausted.
        # This is because we don't know the scopes of the app in all guilds in advance, so we'll have to
        # catch a lot of "Forbidden" errors, exceeding the limit of 10k invalid requests in 10 minutes (for large bots).
        # However, our approach has blind spots. We deal with them in :meth:`process_application_commands`.

        try:
            commands = await self.fetch_global_commands()
            self._connection._global_application_commands = {  # type: ignore
                command.id: command for command in commands
            }
        except Exception:
            pass
        for guild_id in guilds:
            try:
                commands = await self.fetch_guild_commands(guild_id)
                if commands:
                    self._connection._guild_application_commands[guild_id] = {  # type: ignore
                        command.id: command for command in commands
                    }
            except Exception:
                pass

    async def _sync_application_commands(self) -> None:
        if not isinstance(self, disnake.Client):
            raise NotImplementedError(f"This method is only usable in disnake.Client subclasses")

        if not self._sync_commands or self._is_closed or self.loop.is_closed():
            return

        # We assume that all commands are already cached.
        # Sort all invokable commands between guild IDs:
        global_cmds, guild_cmds = self._ordered_unsynced_commands(self._test_guilds)
        if global_cmds is None:
            return

        # Update global commands first
        diff = _app_commands_diff(
            global_cmds, self._connection._global_application_commands.values()
        )
        update_required = (
            bool(diff["upsert"])
            or bool(diff["edit"])
            or bool(diff["change_type"])
            or bool(diff["delete"])
        )

        if self._sync_commands_debug:
            # Show the difference
            print(
                "GLOBAL COMMANDS\n===============",
                "| NOTE: global commands can take up to 1 hour to show up after registration.",
                "|",
                f"| Update is required: {update_required}",
                sep="\n",
            )
            _show_diff(diff, "| ")

        if update_required:
            # Notice that we don't do any API requests if there're no changes.
            try:
                to_send = diff["no_changes"] + diff["edit"]
                if bool(diff["change_type"]):
                    # We can't just "edit" the command type, so we bulk delete the commands with old type first.
                    await self.bulk_overwrite_global_commands(to_send)
                # Finally, we make an API call that applies all changes from the code.
                to_send.extend(diff["upsert"])
                to_send.extend(diff["change_type"])
                await self.bulk_overwrite_global_commands(to_send)
            except Exception as e:
                warnings.warn(f"Failed to overwrite global commands due to {e}", SyncWarning)
        # Same process but for each specified guild individually.
        # Notice that we're not doing this for every single guild for optimisation purposes.
        # See the note in :meth:`_cache_application_commands` about guild app commands.
        for guild_id, cmds in guild_cmds.items():
            current_guild_cmds = self._connection._guild_application_commands.get(guild_id, {})
            diff = _app_commands_diff(cmds, current_guild_cmds.values())
            update_required = (
                bool(diff["upsert"])
                or bool(diff["edit"])
                or bool(diff["change_type"])
                or bool(diff["delete"])
            )
            # Show diff
            if self._sync_commands_debug:
                print(
                    f'COMMANDS IN {guild_id}\n============{"=" * 18}',
                    f"| Update is required: {update_required}",
                    sep="\n",
                )
                _show_diff(diff, "| ")
            # Do API requests and cache
            if update_required:
                try:
                    to_send = diff["no_changes"] + diff["edit"]
                    if bool(diff["change_type"]):
                        await self.bulk_overwrite_guild_commands(guild_id, to_send)
                    to_send.extend(diff["upsert"])
                    to_send.extend(diff["change_type"])
                    await self.bulk_overwrite_guild_commands(guild_id, to_send)
                except Exception as e:
                    warnings.warn(
                        f"Failed to overwrite commands in <Guild id={guild_id}> due to {e}",
                        SyncWarning,
                    )
        # Last debug message
        if self._sync_commands_debug:
            print("DEBUG: Command synchronization task has been finished", end="\n\n")

    async def _cache_application_command_permissions(self) -> None:
        # This method is usually called once per bot start
        if not isinstance(self, disnake.Client):
            raise NotImplementedError(f"This method is only usable in disnake.Client subclasses")

        guilds_to_cache = set()
        for cmd in self.application_commands:
            if not cmd.auto_sync:
                continue
            for guild_id in cmd.permissions:
                guilds_to_cache.add(guild_id)

        if not self._sync_permissions:
            if guilds_to_cache:
                warnings.warn(
                    "You're using the @commands.guild_permissions decorator, however, the"
                    f" 'sync_permissions' kwarg of '{self.__class__.__name__}' is set to 'False'.",
                    ConfigWarning,
                )
            return

        for guild_id in guilds_to_cache:
            try:
                perms = await self.bulk_fetch_command_permissions(guild_id)
                self._connection._application_command_permissions[guild_id] = {
                    perm.id: perm for perm in perms
                }
            except Exception:
                pass

    async def _sync_application_command_permissions(self) -> None:
        # Assuming that permissions and commands are cached
        if not isinstance(self, disnake.Client):
            raise NotImplementedError(f"This method is only usable in disnake.Client subclasses")

        if not self._sync_permissions or self._is_closed or self.loop.is_closed():
            return

        guilds_to_compare: Dict[
            int, List[PartialGuildApplicationCommandPermissions]
        ] = {}  # {guild_id: [partial_perms, ...], ...}

        for cmd_wrapper in self.application_commands:
            if not cmd_wrapper.auto_sync:
                continue

            for guild_id, perms in cmd_wrapper.permissions.items():
                # Here we need to get the ID of the relevant API object
                # representing the application command from the user's code
                guild_ids_for_sync = cmd_wrapper.guild_ids or self._test_guilds
                if guild_ids_for_sync is None:
                    cmd = self.get_global_command_named(cmd_wrapper.name, cmd_wrapper.body.type)
                else:
                    cmd = self.get_guild_command_named(
                        guild_id, cmd_wrapper.name, cmd_wrapper.body.type
                    )
                if cmd is None:
                    continue
                # If we got here, we know the ID of the application command

                if not self.owner_id and not self.owner_ids:
                    await self._fill_owners()
                resolved_perms = perms.resolve(
                    command_id=cmd.id,  # type: ignore
                    owners=[self.owner_id] if self.owner_id else self.owner_ids,
                )

                if guild_id not in guilds_to_compare:
                    guilds_to_compare[guild_id] = []
                guilds_to_compare[guild_id].append(resolved_perms)

        # Once per-guild permissions are collected from the code,
        # we can compare them to the cached permissions
        for guild_id, new_array in guilds_to_compare.items():
            old_perms = self._connection._application_command_permissions.get(guild_id, {})
            if len(new_array) == len(old_perms) and all(
                new_cmd_perms.id in old_perms
                and old_perms[new_cmd_perms.id].permissions == new_cmd_perms.permissions
                for new_cmd_perms in new_array
            ):
                if self._sync_commands_debug:
                    print(f"DEBUG: Command permissions in <Guild id={guild_id}>: no changes")
                continue
            # If we got here, the permissions require an update
            try:
                await self.bulk_edit_command_permissions(guild_id, new_array)
            except Exception as err:
                warnings.warn(
                    f"Failed to overwrite permissions in <Guild id={guild_id}> due to {err}",
                    SyncWarning,
                )
            finally:
                if self._sync_commands_debug:
                    print(f"DEBUG: Command permissions in <Guild id={guild_id}>: edited")

    async def _prepare_application_commands(self) -> None:
        if not isinstance(self, disnake.Client):
            raise NotImplementedError(f"Command sync is only possible in disnake.Client subclasses")

        self._sync_queued = True
        await self.wait_until_first_connect()
        await self._cache_application_commands()
        await self._sync_application_commands()
        await self._cache_application_command_permissions()
        await self._sync_application_command_permissions()
        self._sync_queued = False

    async def _delayed_command_sync(self) -> None:
        if not isinstance(self, disnake.Client):
            raise NotImplementedError(f"This method is only usable in disnake.Client subclasses")

        if (
            not self._sync_commands
            or self._sync_queued
            or not self.is_ready()
            or self._is_closed
            or self.loop.is_closed()
        ):
            return
        # We don't do this task on login or in parallel with a similar task
        # Wait a little bit, maybe other cogs are loading
        self._sync_queued = True
        await asyncio.sleep(2)
        await self._sync_application_commands()
        await self._sync_application_command_permissions()
        self._sync_queued = False

    def _schedule_app_command_preparation(self) -> None:
        if not isinstance(self, disnake.Client):
            raise NotImplementedError(f"Command sync is only possible in disnake.Client subclasses")

        self.loop.create_task(
            self._prepare_application_commands(), name="disnake: app_command_preparation"
        )

    def _schedule_delayed_command_sync(self) -> None:
        if not isinstance(self, disnake.Client):
            raise NotImplementedError(f"This method is only usable in disnake.Client subclasses")

        self.loop.create_task(self._delayed_command_sync(), name="disnake: delayed_command_sync")

    # Error handlers

    async def on_slash_command_error(
        self, interaction: ApplicationCommandInteraction, exception: errors.CommandError
    ) -> None:
        """|coro|

        The default slash command error handler provided by the bot.

        By default this prints to :data:`sys.stderr` however it could be
        overridden to have a different implementation.

        This only fires if you do not specify any listeners for slash command error.
        """
        if self.extra_events.get("on_slash_command_error", None):
            return

        command = interaction.application_command
        if command and command.has_error_handler():
            return

        cog = command.cog
        if cog and cog.has_slash_error_handler():
            return

        print(f"Ignoring exception in slash command {command.name!r}:", file=sys.stderr)
        traceback.print_exception(
            type(exception), exception, exception.__traceback__, file=sys.stderr
        )

    async def on_user_command_error(
        self, interaction: ApplicationCommandInteraction, exception: errors.CommandError
    ) -> None:
        """|coro|

        Similar to :meth:`on_slash_command_error` but for user commands.
        """
        if self.extra_events.get("on_user_command_error", None):
            return
        command = interaction.application_command
        if command and command.has_error_handler():
            return
        cog = command.cog
        if cog and cog.has_user_error_handler():
            return
        print(f"Ignoring exception in user command {command.name!r}:", file=sys.stderr)
        traceback.print_exception(
            type(exception), exception, exception.__traceback__, file=sys.stderr
        )

    async def on_message_command_error(
        self, interaction: ApplicationCommandInteraction, exception: errors.CommandError
    ) -> None:
        """|coro|

        Similar to :meth:`on_slash_command_error` but for message commands.
        """
        if self.extra_events.get("on_message_command_error", None):
            return
        command = interaction.application_command
        if command and command.has_error_handler():
            return
        cog = command.cog
        if cog and cog.has_message_error_handler():
            return
        print(f"Ignoring exception in message command {command.name!r}:", file=sys.stderr)
        traceback.print_exception(
            type(exception), exception, exception.__traceback__, file=sys.stderr
        )

    # global check registration

    def add_app_command_check(
        self,
        func: Check,
        *,
        call_once: bool = False,
        slash_commands: bool = False,
        user_commands: bool = False,
        message_commands: bool = False,
    ) -> None:
        """Adds a global check to the bot.

        This is the non-decorator interface to :meth:`.check`,
        :meth:`.check_once`, :meth:`.slash_command_check` and etc.

        If none of bool params are specified, the check is for
        text commands only.

        Parameters
        -----------
        func
            The function that was used as a global check.
        call_once: :class:`bool`
            If the function should only be called once per
            :meth:`invoke` call.
        slash_commands: :class:`bool`
            If this check is for slash commands.
        user_commands: :class:`bool`
            If this check is for user commands.
        message_commands: :class:`bool`
            If this check is for message commands.
        """

        if slash_commands:
            if call_once:
                self._slash_command_check_once.append(func)
            else:
                self._slash_command_checks.append(func)

        if user_commands:
            if call_once:
                self._user_command_check_once.append(func)
            else:
                self._user_command_checks.append(func)

        if message_commands:
            if call_once:
                self._message_command_check_once.append(func)
            else:
                self._message_command_checks.append(func)

    def remove_app_command_check(
        self,
        func: Check,
        *,
        call_once: bool = False,
        slash_commands: bool = False,
        user_commands: bool = False,
        message_commands: bool = False,
    ) -> None:
        """Removes a global check from the bot.

        This function is idempotent and will not raise an exception
        if the function is not in the global checks.

        If none of bool params are specified, the check is for
        text commands only.

        Parameters
        -----------
        func
            The function to remove from the global checks.
        call_once: :class:`bool`
            If the function was added with ``call_once=True`` in
            the :meth:`.Bot.add_check` call or using :meth:`.check_once`.
        slash_commands: :class:`bool`
            If this check was for slash commands.
        user_commands: :class:`bool`
            If this check was for user commands.
        message_commands: :class:`bool`
            If this check was for message commands.
        """

        if slash_commands:
            l = self._slash_command_check_once if call_once else self._slash_command_checks
            try:
                l.remove(func)
            except ValueError:
                pass

        if user_commands:
            l = self._user_command_check_once if call_once else self._user_command_checks
            try:
                l.remove(func)
            except ValueError:
                pass

        if message_commands:
            l = self._message_command_check_once if call_once else self._message_command_checks
            try:
                l.remove(func)
            except ValueError:
                pass

    def slash_command_check(self, func: T) -> T:
        """Similar to :meth:`.check` but for slash commands."""
        # T was used instead of Check to ensure the type matches on return
        self.add_app_command_check(func, slash_commands=True)  # type: ignore
        return func

    def slash_command_check_once(self, func: CFT) -> CFT:
        """Similar to :meth:`.check_once` but for slash commands."""
        self.add_app_command_check(func, call_once=True, slash_commands=True)
        return func

    def user_command_check(self, func: T) -> T:
        """Similar to :meth:`.check` but for user commands."""
        # T was used instead of Check to ensure the type matches on return
        self.add_app_command_check(func, user_commands=True)  # type: ignore
        return func

    def user_command_check_once(self, func: CFT) -> CFT:
        """Similar to :meth:`.check_once` but for user commands."""
        self.add_app_command_check(func, call_once=True, user_commands=True)
        return func

    def message_command_check(self, func: T) -> T:
        """Similar to :meth:`.check` but for message commands."""
        # T was used instead of Check to ensure the type matches on return
        self.add_app_command_check(func, message_commands=True)  # type: ignore
        return func

    def message_command_check_once(self, func: CFT) -> CFT:
        """Similar to :meth:`.check_once` but for message commands."""
        self.add_app_command_check(func, call_once=True, message_commands=True)
        return func

    def application_command_check(
        self,
        *,
        call_once: bool = False,
        slash_commands: bool = False,
        user_commands: bool = False,
        message_commands: bool = False,
    ) -> Callable[
        [Callable[[ApplicationCommandInteraction], Any]],
        Callable[[ApplicationCommandInteraction], Any],
    ]:
        r"""A decorator that adds a global check to the bot.

        A global check is similar to a :func:`.check` that is applied
        on a per command basis except it is run before any application command checks
        have been verified and applies to every application command the bot has.

        .. note::

            This function can either be a regular function or a coroutine.

        Similar to a command :func:`.check`\, this takes a single parameter
        of type :class:`.ApplicationCommandInteraction` and can only raise exceptions inherited from
        :exc:`.CommandError`.

        Example
        -------

        .. code-block:: python3

            @bot.application_command_check()
            def check_app_commands(inter):
                return inter.channel_id in whitelisted_channels

        Parameters
        ----------
        call_once: :class:`bool`
            If the function should only be called once per
            :meth:`invoke` call.
        text_commands: :class:`bool`
            If this check is for text commands.
        slash_commands: :class:`bool`
            If this check is for slash commands.
        user_commands: :class:`bool`
            If this check is for user commands.
        message_commands: :class:`bool`
            If this check is for message commands.
        """
        if not (slash_commands or user_commands or message_commands):
            slash_commands = True
            user_commands = True
            message_commands = True

        def decorator(
            func: Callable[[ApplicationCommandInteraction], Any]
        ) -> Callable[[ApplicationCommandInteraction], Any]:
            # T was used instead of Check to ensure the type matches on return
            self.add_app_command_check(
                func,  # type: ignore
                call_once=call_once,
                slash_commands=slash_commands,
                user_commands=user_commands,
                message_commands=message_commands,
            )
            return func

        return decorator

    async def application_command_can_run(
        self, inter: ApplicationCommandInteraction, *, call_once: bool = False
    ) -> bool:

        if inter.data.type is ApplicationCommandType.chat_input:
            checks = self._slash_command_check_once if call_once else self._slash_command_checks

        elif inter.data.type is ApplicationCommandType.user:
            checks = self._user_command_check_once if call_once else self._user_command_checks

        elif inter.data.type is ApplicationCommandType.message:
            checks = self._message_command_check_once if call_once else self._message_command_checks

        else:
            return True

        if len(checks) == 0:
            return True

        # type-checker doesn't distinguish between functions and methods
        return await disnake.utils.async_all(f(inter) for f in checks)  # type: ignore

    def before_slash_command_invoke(self, coro: CFT) -> CFT:
        """Similar to :meth:`Bot.before_invoke` but for slash commands."""

        if not asyncio.iscoroutinefunction(coro):
            raise TypeError("The pre-invoke hook must be a coroutine.")

        self._before_slash_command_invoke = coro
        return coro

    def after_slash_command_invoke(self, coro: CFT) -> CFT:
        """Similar to :meth:`Bot.after_invoke` but for slash commands."""

        if not asyncio.iscoroutinefunction(coro):
            raise TypeError("The post-invoke hook must be a coroutine.")

        self._after_slash_command_invoke = coro
        return coro

    def before_user_command_invoke(self, coro: CFT) -> CFT:
        """Similar to :meth:`Bot.before_invoke` but for user commands."""

        if not asyncio.iscoroutinefunction(coro):
            raise TypeError("The pre-invoke hook must be a coroutine.")

        self._before_user_command_invoke = coro
        return coro

    def after_user_command_invoke(self, coro: CFT) -> CFT:
        """Similar to :meth:`Bot.after_invoke` but for user commands."""

        if not asyncio.iscoroutinefunction(coro):
            raise TypeError("The post-invoke hook must be a coroutine.")

        self._after_user_command_invoke = coro
        return coro

    def before_message_command_invoke(self, coro: CFT) -> CFT:
        """Similar to :meth:`Bot.before_invoke` but for message commands."""

        if not asyncio.iscoroutinefunction(coro):
            raise TypeError("The pre-invoke hook must be a coroutine.")

        self._before_message_command_invoke = coro
        return coro

    def after_message_command_invoke(self, coro: CFT) -> CFT:
        """Similar to :meth:`Bot.after_invoke` but for message commands."""

        if not asyncio.iscoroutinefunction(coro):
            raise TypeError("The post-invoke hook must be a coroutine.")

        self._after_message_command_invoke = coro
        return coro

    # command processing

    async def process_app_command_autocompletion(
        self, inter: ApplicationCommandInteraction
    ) -> None:
        """|coro|

        This function processes the application command autocompletions.
        Without this coroutine, none of the autocompletions will be performed.

        By default, this coroutine is called inside the :func:`.on_application_command_autocompletion`
        event. If you choose to override the :func:`.on_application_command_autocompletion` event, then
        you should invoke this coroutine as well.

        Parameters
        -----------
        inter: :class:`disnake.ApplicationCommandInteraction`
            The interaction to process.
        """
        slash_command = self.all_slash_commands.get(inter.data.name)

        if slash_command is None:
            return

        inter.bot = self  # type: ignore
        inter.application_command = slash_command
        if slash_command.guild_ids is None or inter.guild_id in slash_command.guild_ids:
            await slash_command._call_relevant_autocompleter(inter)

    async def process_application_commands(
        self, interaction: ApplicationCommandInteraction
    ) -> None:
        """|coro|

        This function processes the application commands that have been registered
        to the bot and other groups. Without this coroutine, none of the
        application commands will be triggered.

        By default, this coroutine is called inside the :func:`.on_application_command`
        event. If you choose to override the :func:`.on_application_command` event, then
        you should invoke this coroutine as well.

        Parameters
        -----------
        interaction: :class:`disnake.ApplicationCommandInteraction`
            The interaction to process commands for.
        """
        if self._sync_commands and not self._sync_queued:
            known_command = self.get_global_command(interaction.data.id)  # type: ignore

            if known_command is None:
                known_command = self.get_guild_command(interaction.guild_id, interaction.data.id)  # type: ignore

            if known_command is None:
                # This usually comes from the blind spots of the sync algorithm.
                # Since not all guild commands are cached, it is possible to experience such issues.
                # In this case, the blind spot is the interaction guild, let's fix it:
                try:
                    await self.bulk_overwrite_guild_commands(interaction.guild_id, [])  # type: ignore
                except disnake.HTTPException:
                    pass
                try:
                    # This part is in a separate try-except because we still should respond to the interaction
                    await interaction.response.send_message(
                        "This command has just been synced. More information about this: "
                        "https://docs.disnake.dev/en/latest/ext/commands/additional_info.html"
                        "#app-command-sync.",
                        ephemeral=True,
                    )
                except disnake.HTTPException:
                    pass
                return

        interaction.bot = self  # type: ignore
        command_type = interaction.data.type
        command_name = interaction.data.name
        app_command = None
        event_name = None

        if command_type is ApplicationCommandType.chat_input:
            app_command = self.all_slash_commands.get(command_name)
            event_name = "slash_command"

        elif command_type is ApplicationCommandType.user:
            app_command = self.all_user_commands.get(command_name)
            event_name = "user_command"

        elif command_type is ApplicationCommandType.message:
            app_command = self.all_message_commands.get(command_name)
            event_name = "message_command"

        if event_name is None or app_command is None:
            # If we are here, the command being invoked is either unknown or has an unknonw type.
            # This usually happens if the auto sync is disabled, so let's just ignore this.
            return

        self.dispatch(event_name, interaction)
        try:
            if await self.application_command_can_run(interaction, call_once=True):
                await app_command.invoke(interaction)
                self.dispatch(f"{event_name}_completion", interaction)
            else:
                raise errors.CheckFailure("The global check_once functions failed.")
        except errors.CommandError as exc:
            await app_command.dispatch_error(interaction, exc)

    async def on_application_command(self, interaction: ApplicationCommandInteraction):
        await self.process_application_commands(interaction)

    async def on_application_command_autocomplete(self, interaction: ApplicationCommandInteraction):
        await self.process_app_command_autocompletion(interaction)
