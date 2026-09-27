import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import worker
from auth_input import normalize_token


class AuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def test_quotes_are_removed_before_login(self):
        client = SimpleNamespace(login=AsyncMock(), user=SimpleNamespace(id=123))
        self.assertTrue(await worker.authenticate(client, ' "example-secret" ', 123))
        client.login.assert_awaited_once_with('example-secret')

    async def test_other_account_is_rejected(self):
        client = SimpleNamespace(login=AsyncMock(), user=SimpleNamespace(id=456))
        self.assertFalse(await worker.authenticate(client, 'example-secret', 123))

    async def test_login_failure_is_not_treated_as_success(self):
        client = SimpleNamespace(login=AsyncMock(side_effect=discord.LoginFailure('secret-in-exception')))
        with self.assertRaises(discord.LoginFailure) as caught:
            await worker.authenticate(client, 'example-secret', 123)
        result = worker.connection_error(caught.exception, 'authentification')
        self.assertEqual(result['code'], 'AUTH_REJECTED')
        self.assertNotIn('secret-in-exception', str(result))

    async def test_malformed_input_never_reaches_login(self):
        for token in ('', 'abc def', 'abc\u200bdef', 'Bot abc', 'Bearer abc'):
            client = SimpleNamespace(login=AsyncMock())
            with self.assertRaises(ValueError):
                await worker.authenticate(client, token, 123)
            client.login.assert_not_awaited()

    async def test_network_failure_is_distinct_and_redacted(self):
        result = worker.connection_error(OSError('secret-in-exception'), 'authentification')
        self.assertEqual(result['code'], 'CONNECTION_ERROR')
        self.assertNotIn('secret-in-exception', str(result))
        self.assertEqual(worker.connection_error(TimeoutError(), 'Gateway')['code'], 'TIMEOUT')


if __name__ == '__main__':
    unittest.main()
