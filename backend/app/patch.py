import asyncio
import functools
from collections import OrderedDict, deque
from typing import Deque, Dict, Optional, Union
from pyrogram import handlers, types
from pyrogram import Client as PyroClient
from pyrogram import errors, raw, session, types
from pyrogram.filters import Filter



class ListenerCanceled(Exception):
    pass


class PatchedClient(PyroClient):
    def __init__(self, *args, **kwargs):
        self.listeners: Dict[str, Deque[dict]] = {}
        super().__init__(*args, **kwargs)

    async def load_session(self):
        """Fix storage.loop (captured at module level) before opening."""
        if hasattr(self, 'storage') and self.storage is not None:
            try:
                self.storage.loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
        await super().load_session()

    async def start(self, *args, **kwargs):
        await super().start(*args, **kwargs)

    async def stop(self, *args):
        await super().stop()

    """Custom methods for conversation support from pyromod && pyropatch"""

    async def check_cbd(self, buttons: types.InlineKeyboardMarkup):
        if not buttons:
            return False
        for button_row in buttons.inline_keyboard:
            for button in button_row:
                if button.callback_data:
                    return True
        return False

    async def wait_for_callback_query(
        self,
        chat_id: Optional[int] = None,
        message_id: Optional[int] = None,
        inline_message_id: Optional[str] = None,
        timeout: Optional[int] = None,
        filters: Optional[Filter] = None,
    ) -> types.CallbackQuery:
        if chat_id:
            if not message_id:
                raise TypeError("message_id is required")
            msg = await self.get_messages(chat_id=chat_id, message_ids=message_id)
            if msg.empty:  # type: ignore
                raise ValueError("message id is invalid")
            if not msg.from_user.is_self:  # type: ignore
                raise ValueError("cannot use self message")
            # if not await self.check_cbd(msg.reply_markup):  # type: ignore
            #     raise TypeError("message type invalid [no callback button]")
            key = f"{chat_id}:{message_id}"
        elif inline_message_id:
            key = inline_message_id
        else:
            raise TypeError("chat_id or inline_message_id is required")
        future = self.loop.create_future()
        entry = {"future": future, "filters": filters}
        self.listeners.setdefault(key, deque()).append(entry)
        future.add_done_callback(functools.partial(self._forget_listener, key, entry))
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            self._forget_listener(key, entry)
            raise

    async def wait_for_message(
        self,
        chat_id: Union[str, int],
        filters: Optional[Filter] = None,
        timeout: Optional[int] = None,
    ) -> types.Message:
        if not isinstance(chat_id, int):
            chat = await self.get_chat(chat_id)
            chat_id = chat.id  # type: ignore
        key = str(chat_id)
        future = self.loop.create_future()
        entry = {"future": future, "filters": filters}
        self.listeners.setdefault(key, deque()).append(entry)
        future.add_done_callback(functools.partial(self._forget_listener, key, entry))
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            self._forget_listener(key, entry)
            raise

    async def wait_for_inline_query(
        self, user_id: int, filters: Optional[Filter] = None, timeout: Optional[int] = None
    ):
        key = str(user_id)
        future = self.loop.create_future()
        entry = {"future": future, "filters": filters}
        self.listeners.setdefault(key, deque()).append(entry)
        future.add_done_callback(functools.partial(self._forget_listener, key, entry))
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            self._forget_listener(key, entry)
            raise

    async def wait_for_inline_result(
        self, user_id: int, filters: Optional[Filter] = None, timeout: Optional[int] = None
    ):
        key = str(user_id)
        future = self.loop.create_future()
        entry = {"future": future, "filters": filters}
        self.listeners.setdefault(key, deque()).append(entry)
        future.add_done_callback(functools.partial(self._forget_listener, key, entry))
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            self._forget_listener(key, entry)
            raise

    def _forget_listener(self, key: str, entry: dict, _future=None):
        """Remove a specific listener entry once its future resolves (or is
        canceled/hits a timeout). Done-callbacks pass the future as a trailing
        positional arg, hence the ignored ``_future`` slot."""
        queue = self.listeners.get(key)
        if not queue:
            return
        try:
            queue.remove(entry)
        except ValueError:
            pass
        if not queue:
            self.listeners.pop(key, None)

    def remove_listener(self, key: str, future=None):
        """Remove a pending listener by future identity (or all when future is None)."""
        queue = self.listeners.get(key)
        if not queue:
            return
        for entry in list(queue):
            if future is None or entry["future"] is future:
                self._forget_listener(key, entry)
                if future is not None:
                    return

    def cancel_listener(self, key: str):
        queue = self.listeners.get(key)
        if not queue:
            return
        for entry in list(queue):
            future = entry["future"]
            if not future.done():  # type: ignore
                future.set_exception(ListenerCanceled())  # type: ignore
        self.listeners.pop(key, None)

    async def invoke(
        self,
        query: raw.core.TLObject,
        retries: int = session.Session.MAX_RETRIES,
        timeout: float = session.Session.WAIT_TIMEOUT,
        sleep_threshold: float = None,  # type: ignore
        **kwargs,
    ):
        try:
            res = await super().invoke(
                query=query,
                retries=retries,
                timeout=timeout,
                sleep_threshold=sleep_threshold,
                **kwargs,
            )
            return res
        except errors.FloodWait as e:
            # Single retry after short wait — don't block workers indefinitely
            await asyncio.sleep(min(e.value, 5))  # type: ignore
            return await super().invoke(
                query=query,
                retries=retries,
                timeout=timeout,
                sleep_threshold=sleep_threshold,
                **kwargs,
            )
                    
async def resolve_listener(
    client: PatchedClient,
    update: Union[types.CallbackQuery, types.Message, types.InlineQuery, types.ChosenInlineResult],
):
    if isinstance(update, types.Message):
        # Never swallow bot commands into a pending flow: let /cancel and every
        # other command reach their real handlers instead of being consumed as
        # "user input" for rename / folder-creation / login flows.
        if getattr(update, "text", None) and update.text.startswith("/"):
            update.continue_propagation()
            return

    if isinstance(update, types.CallbackQuery):
        if update.message:
            key = f"{update.message.chat.id}:{update.message.id}"
        elif update.inline_message_id:
            key = update.inline_message_id
        else:
            return
    elif isinstance(update, (types.ChosenInlineResult, types.InlineQuery)):
        key = str(update.from_user.id)
    else:
        key = str(update.chat.id)  # type: ignore

    queue = client.listeners.get(key)
    if not queue:
        update.continue_propagation()
        return

    entry = queue[0]
    if entry["future"].done():  # type: ignore
        client._forget_listener(key, entry)
        update.continue_propagation()
        return
    if callable(entry["filters"]):
        if not await entry["filters"](client, update):
            update.continue_propagation()
            return
    entry["future"].set_result(update)  # type: ignore
    update.stop_propagation()


class Client(PatchedClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._listeners_registered = False

    def add_handler(self, handler, group: int = 0):
        if isinstance(handler, handlers.DisconnectHandler):
            self.disconnect_handler = handler.callback
        else:
            if group not in self.dispatcher.groups:
                self.dispatcher.groups[group] = []
                self.dispatcher.groups = OrderedDict(sorted(self.dispatcher.groups.items()))
            self.dispatcher.groups[group].append(handler)
        return handler, group

    async def start(self, *args, **kwargs):
        # Fix loop capture: Pyrogram's __init__ captures asyncio.get_event_loop()
        # at import time (wrong loop under uvicorn). Sync to the running loop.
        self.loop = asyncio.get_running_loop()
        self.dispatcher.loop = self.loop
        if not self._listeners_registered:
            self.add_handler(handlers.CallbackQueryHandler(resolve_listener), group=-1)
            self.add_handler(handlers.InlineQueryHandler(resolve_listener), group=-1)
            self.add_handler(handlers.ChosenInlineResultHandler(resolve_listener), group=-1)
            self.add_handler(handlers.MessageHandler(resolve_listener), group=-1)
            self._listeners_registered = True
        await super().start(*args, **kwargs)