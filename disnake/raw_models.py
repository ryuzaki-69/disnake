"""
The MIT License (MIT)

Copyright (c) 2015-2021 Rapptz
Copyright (c) 2021-present Disnake Development

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, List, Optional, Set

if TYPE_CHECKING:
    from .member import Member
    from .message import Message
    from .partial_emoji import PartialEmoji
    from .types.raw_models import (
        BulkMessageDeleteEvent,
        IntegrationDeleteEvent,
        MessageDeleteEvent,
        MessageUpdateEvent,
        ReactionActionEvent,
        ReactionClearEmojiEvent,
        ReactionClearEvent,
        TypingEvent,
    )


__all__ = (
    "RawMessageDeleteEvent",
    "RawBulkMessageDeleteEvent",
    "RawMessageUpdateEvent",
    "RawReactionActionEvent",
    "RawReactionClearEvent",
    "RawReactionClearEmojiEvent",
    "RawIntegrationDeleteEvent",
    "RawGuildScheduledEventUserActionEvent",
    "RawTypingEvent",
)


class _RawReprMixin:
    def __repr__(self) -> str:
        value = " ".join(f"{attr}={getattr(self, attr)!r}" for attr in self.__slots__)
        return f"<{self.__class__.__name__} {value}>"


class RawMessageDeleteEvent(_RawReprMixin):
    """Represents the event payload for a :func:`on_raw_message_delete` event.

    Attributes
    ------------
    channel_id: :class:`int`
        The channel ID where the deletion took place.
    guild_id: Optional[:class:`int`]
        The guild ID where the deletion took place, if applicable.
    message_id: :class:`int`
        The message ID that got deleted.
    cached_message: Optional[:class:`Message`]
        The cached message, if found in the internal message cache.
    """

    __slots__ = ("message_id", "channel_id", "guild_id", "cached_message")

    def __init__(self, data: MessageDeleteEvent) -> None:
        self.message_id: int = int(data["id"])
        self.channel_id: int = int(data["channel_id"])
        self.cached_message: Optional[Message] = None
        try:
            self.guild_id: Optional[int] = int(data["guild_id"])
        except KeyError:
            self.guild_id: Optional[int] = None


class RawBulkMessageDeleteEvent(_RawReprMixin):
    """Represents the event payload for a :func:`on_raw_bulk_message_delete` event.

    Attributes
    -----------
    message_ids: Set[:class:`int`]
        A :class:`set` of the message IDs that were deleted.
    channel_id: :class:`int`
        The channel ID where the message got deleted.
    guild_id: Optional[:class:`int`]
        The guild ID where the message got deleted, if applicable.
    cached_messages: List[:class:`Message`]
        The cached messages, if found in the internal message cache.
    """

    __slots__ = ("message_ids", "channel_id", "guild_id", "cached_messages")

    def __init__(self, data: BulkMessageDeleteEvent) -> None:
        self.message_ids: Set[int] = {int(x) for x in data.get("ids", [])}
        self.channel_id: int = int(data["channel_id"])
        self.cached_messages: List[Message] = []

        try:
            self.guild_id: Optional[int] = int(data["guild_id"])
        except KeyError:
            self.guild_id: Optional[int] = None


class RawMessageUpdateEvent(_RawReprMixin):
    """Represents the payload for a :func:`on_raw_message_edit` event.

    Attributes
    -----------
    message_id: :class:`int`
        The message ID that got updated.
    channel_id: :class:`int`
        The channel ID where the update took place.

        .. versionadded:: 1.3
    guild_id: Optional[:class:`int`]
        The guild ID where the message got updated, if applicable.

        .. versionadded:: 1.7

    data: :class:`dict`
        The raw data given by the `gateway <https://discord.com/developers/docs/topics/gateway#message-update>`_
    cached_message: Optional[:class:`Message`]
        The cached message, if found in the internal message cache. Represents the message before
        it is modified by the data in :attr:`RawMessageUpdateEvent.data`.
    """

    __slots__ = ("message_id", "channel_id", "guild_id", "data", "cached_message")

    def __init__(self, data: MessageUpdateEvent) -> None:
        self.message_id: int = int(data["id"])
        self.channel_id: int = int(data["channel_id"])
        self.data: MessageUpdateEvent = data
        self.cached_message: Optional[Message] = None

        try:
            self.guild_id: Optional[int] = int(data["guild_id"])
        except KeyError:
            self.guild_id: Optional[int] = None


class RawReactionActionEvent(_RawReprMixin):
    """Represents the payload for a :func:`on_raw_reaction_add` or
    :func:`on_raw_reaction_remove` event.

    Attributes
    -----------
    message_id: :class:`int`
        The message ID that got or lost a reaction.
    user_id: :class:`int`
        The user ID who added the reaction or whose reaction was removed.
    channel_id: :class:`int`
        The channel ID where the reaction got added or removed.
    guild_id: Optional[:class:`int`]
        The guild ID where the reaction got added or removed, if applicable.
    emoji: :class:`PartialEmoji`
        The custom or unicode emoji being used.
    member: Optional[:class:`Member`]
        The member who added the reaction. Only available if `event_type` is `REACTION_ADD` and the reaction is inside a guild.

        .. versionadded:: 1.3

    event_type: :class:`str`
        The event type that triggered this action. Can be
        ``REACTION_ADD`` for reaction addition or
        ``REACTION_REMOVE`` for reaction removal.

        .. versionadded:: 1.3
    """

    __slots__ = ("message_id", "user_id", "channel_id", "guild_id", "emoji", "event_type", "member")

    def __init__(self, data: ReactionActionEvent, emoji: PartialEmoji, event_type: str) -> None:
        self.message_id: int = int(data["message_id"])
        self.channel_id: int = int(data["channel_id"])
        self.user_id: int = int(data["user_id"])
        self.emoji: PartialEmoji = emoji
        self.event_type: str = event_type
        self.member: Optional[Member] = None

        try:
            self.guild_id: Optional[int] = int(data["guild_id"])
        except KeyError:
            self.guild_id: Optional[int] = None


class RawReactionClearEvent(_RawReprMixin):
    """Represents the payload for a :func:`on_raw_reaction_clear` event.

    Attributes
    -----------
    message_id: :class:`int`
        The message ID that got its reactions cleared.
    channel_id: :class:`int`
        The channel ID where the reactions got cleared.
    guild_id: Optional[:class:`int`]
        The guild ID where the reactions got cleared.
    """

    __slots__ = ("message_id", "channel_id", "guild_id")

    def __init__(self, data: ReactionClearEvent) -> None:
        self.message_id: int = int(data["message_id"])
        self.channel_id: int = int(data["channel_id"])

        try:
            self.guild_id: Optional[int] = int(data["guild_id"])
        except KeyError:
            self.guild_id: Optional[int] = None


class RawReactionClearEmojiEvent(_RawReprMixin):
    """Represents the payload for a :func:`on_raw_reaction_clear_emoji` event.

    .. versionadded:: 1.3

    Attributes
    -----------
    message_id: :class:`int`
        The message ID that got its reactions cleared.
    channel_id: :class:`int`
        The channel ID where the reactions got cleared.
    guild_id: Optional[:class:`int`]
        The guild ID where the reactions got cleared.
    emoji: :class:`PartialEmoji`
        The custom or unicode emoji being removed.
    """

    __slots__ = ("message_id", "channel_id", "guild_id", "emoji")

    def __init__(self, data: ReactionClearEmojiEvent, emoji: PartialEmoji) -> None:
        self.emoji: PartialEmoji = emoji
        self.message_id: int = int(data["message_id"])
        self.channel_id: int = int(data["channel_id"])

        try:
            self.guild_id: Optional[int] = int(data["guild_id"])
        except KeyError:
            self.guild_id: Optional[int] = None


class RawIntegrationDeleteEvent(_RawReprMixin):
    """Represents the payload for a :func:`on_raw_integration_delete` event.

    .. versionadded:: 2.0

    Attributes
    -----------
    integration_id: :class:`int`
        The ID of the integration that got deleted.
    application_id: Optional[:class:`int`]
        The ID of the bot/OAuth2 application for this deleted integration.
    guild_id: :class:`int`
        The guild ID where the integration got deleted.
    """

    __slots__ = ("integration_id", "application_id", "guild_id")

    def __init__(self, data: IntegrationDeleteEvent) -> None:
        self.integration_id: int = int(data["id"])
        self.guild_id: int = int(data["guild_id"])

        try:
            self.application_id: Optional[int] = int(data["application_id"])
        except KeyError:
            self.application_id: Optional[int] = None


class RawGuildScheduledEventUserActionEvent(_RawReprMixin):
    """Represents the payload for :func:`on_raw_guild_scheduled_event_subscribe`
    and :func:`on_raw_guild_scheduled_event_unsubscribe` event.

    .. versionadded:: 2.3

    Attributes
    -----------
    event_id: :class:`int`
        The ID of the guild scheduled event that the user subscribed to or unsubscribed from.
    user_id: :class:`int`
        The ID of the user doing the action.
    guild_id: :class:`int`
        The guild ID where the guild scheduled event is located.
    """

    __slots__ = ("guild_scheduled_event_id", "user_id", "guild_id")

    def __init__(self, data: dict):
        # TODO: typed dicts
        self.event_id: int = int(data["guild_scheduled_event_id"])
        self.user_id: int = int(data["user_id"])
        self.guild_id: int = int(data["guild_id"])


class RawTypingEvent(_RawReprMixin):
    """Represents the payload for :func:`on_raw_typing` event.

    Attributes
    -----------
    user_id: :class:`int`
        The ID of the user who started typing.
    channel_id: :class:`int`
        The ID of the channel where the user started typing.
    guild_id: Optional[:class:`int`]
        The ID of the guild where the user started typing or ``None`` if it was in a DM.
    member: Optional[:class:`Member`]
        The member object of the user who started typing or ``None`` if it was in a DM.
    timestamp: :class:`datetime.datetime`
        The timestamp when the user started typing.
    """

    __slots__ = ("user_id", "channel_id", "guild_id", "member", "timestamp")

    def __init__(self, data: TypingEvent) -> None:
        self.user_id: int = int(data["user_id"])
        self.channel_id: int = int(data["channel_id"])
        try:
            self.guild_id: Optional[int] = int(data["guild_id"])
        except KeyError:
            self.guild_id: Optional[int] = None
        self.member: Optional[Member] = None
        self.timestamp: datetime.datetime = datetime.datetime.utcfromtimestamp(data["timestamp"])
