import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
from worker import Session


class VoiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = Session()
        self.channel = Mock(spec=discord.VoiceChannel)
        self.channel.id = 123
        self.observed = SimpleNamespace(channel=self.channel, self_mute=False,
                                        self_deaf=False, mute=False, deaf=False)
        self.channel.guild = SimpleNamespace(id=456, me=SimpleNamespace(voice=self.observed))
        self.channel.permissions_for.return_value = SimpleNamespace(view_channel=True, connect=True)

        async def update(**kwargs):
            self.observed.channel = kwargs['channel']
            self.observed.self_mute = kwargs['self_mute']
            self.observed.self_deaf = kwargs['self_deaf']

        self.channel.guild.change_voice_state = AsyncMock(side_effect=update)
        self.voice = SimpleNamespace(channel=self.channel, is_connected=lambda: True)
        self.client.voice = lambda: self.voice
        self.client.get_channel = lambda channel_id: self.channel

    async def asyncTearDown(self):
        await self.client.close()

    async def test_auto_reapplies_audio_in_same_channel(self):
        await self.client.join(123)
        self.assertTrue(self.observed.self_mute)
        self.assertTrue(self.observed.self_deaf)

    async def test_mute_and_deaf_are_independent_and_confirmed(self):
        result = await self.client.execute({'command': 'mute', 'argument': 'on'})
        self.assertTrue(result['mute'])
        result = await self.client.execute({'command': 'deaf', 'argument': 'off'})
        self.assertTrue(result['mute'])
        self.assertFalse(result['deaf'])
        self.assertFalse(result['audio_pending'])

    async def test_auto_survives_initial_network_failure(self):
        self.client.join = AsyncMock(side_effect=TimeoutError())
        result = await self.client.execute({'command': 'auto', 'argument': '123'})
        self.assertTrue(result['auto'])
        self.assertEqual(result['target'], '123')

    async def test_moved_account_reconnects_to_target(self):
        self.observed.channel = SimpleNamespace(id=999)
        self.client.leave = AsyncMock()
        self.channel.connect = AsyncMock()
        await self.client.join(123)
        self.client.leave.assert_awaited_once()
        self.channel.connect.assert_awaited_once()
        self.assertEqual(self.observed.channel.id, 123)

    async def test_disconnect_cancels_auto(self):
        self.client.auto, self.client.target = True, 123
        self.client.leave = AsyncMock()
        await self.client.execute({'command': 'disconnect'})
        self.assertFalse(self.client.auto)
        self.assertIsNone(self.client.target)

    async def test_explicit_command_sends_even_when_cache_matches(self):
        self.observed.self_mute = self.observed.self_deaf = True
        await self.client.execute({'command': 'mute', 'argument': 'on'})
        self.channel.guild.change_voice_state.assert_awaited_once()

    async def test_unchanged_observed_state_needs_no_new_event(self):
        self.observed.self_mute = self.observed.self_deaf = True
        self.channel.guild.change_voice_state = AsyncMock()
        result = await asyncio.wait_for(
            self.client.execute({'command': 'mute', 'argument': 'on'}), timeout=0.5)
        self.assertFalse(result['audio_pending'])

    async def test_unapplied_change_stays_pending(self):
        self.channel.guild.change_voice_state = AsyncMock()
        result = await self.client.execute({'command': 'mute', 'argument': 'on'})
        self.assertTrue(result['audio_pending'])
        self.assertFalse(result['mute'])

    async def test_late_update_clears_pending_without_another_command(self):
        self.channel.guild.change_voice_state = AsyncMock()
        await self.client.execute({'command': 'mute', 'argument': 'on'})
        self.observed.self_mute = self.observed.self_deaf = True
        self.assertFalse(self.client.state()['audio_pending'])

    async def test_missing_state_is_not_reported_as_muted(self):
        self.channel.guild.me.voice = None
        result = self.client.state()
        self.assertIsNone(result['mute'])
        self.assertIsNone(result['deaf'])
        self.assertTrue(result['audio_pending'])


if __name__ == '__main__':
    unittest.main()
