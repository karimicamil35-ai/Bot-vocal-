import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import sqlite3

import bot


class DmTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        connection = sqlite3.connect(':memory:')
        with patch.object(bot.sqlite3, 'connect', return_value=connection):
            self.client = bot.Control()

    async def asyncTearDown(self):
        await self.client.close()

    def message(self, content):
        typing = SimpleNamespace()
        from unittest.mock import MagicMock
        typing = MagicMock()
        typing.__aenter__ = AsyncMock()
        typing.__aexit__ = AsyncMock(return_value=False)
        channel = SimpleNamespace(send=AsyncMock(), typing=lambda: typing)
        return SimpleNamespace(content=content, guild=None,
                               author=SimpleNamespace(id=123, bot=False), channel=channel)

    async def test_help_works_without_personal_session(self):
        message = self.message('  !help  ')
        await self.client.on_message(message)
        self.assertEqual(message.channel.send.call_args.kwargs['embed'].title, 'Help')
        self.assertEqual(message.content, '')

    async def test_bare_token_is_not_echoed_or_used(self):
        message = self.message('fake-secret-for-test')
        with patch.object(self.client, 'connect_account', new_callable=AsyncMock) as connect:
            await self.client.on_message(message)
            connect.assert_not_awaited()
        answer = message.channel.send.call_args.kwargs['embed']
        self.assertNotIn('fake-secret-for-test', str(answer.to_dict()))
        self.assertEqual(message.content, '')

    async def test_ping_works_without_personal_session(self):
        message = self.message('!ping')
        await self.client.on_message(message)
        self.assertEqual(message.channel.send.call_args.kwargs['embed'].title, 'Pong')


if __name__ == '__main__':
    unittest.main()
