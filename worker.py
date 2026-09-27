"""Une session personnelle par processus. Protocole JSON prive via stdin/stdout."""
import asyncio
import contextlib
import json
import logging
import sys

import discord
from discord import VoiceClient
from auth_input import normalize_token

logging.disable(logging.CRITICAL)


def reply(data):
    print(json.dumps(data, ensure_ascii=True), flush=True)


async def authenticate(client, token, owner):
    await asyncio.wait_for(client.login(normalize_token(token)), 30)
    return client.user.id == owner


def connection_error(error, stage):
    if isinstance(error, discord.LoginFailure):
        return {'ok': False, 'code': 'AUTH_REJECTED', 'error':
                'Discord a refuse le token personnel (HTTP 401). '
                'Le token transmis peut etre incomplet, expire ou revoque. '
                'Une session ouverte dans Discord ne garantit pas que ce token reste valide.'}
    if isinstance(error, ValueError):
        return {'ok': False, 'code': 'INVALID_INPUT', 'error': str(error)}
    if isinstance(error, TimeoutError):
        return {'ok': False, 'code': 'TIMEOUT', 'error':
                'Delai depasse pendant ' + stage + '. Verifie la connexion reseau et reessaie.'}
    if isinstance(error, discord.HTTPException):
        return {'ok': False, 'code': 'HTTP_ERROR', 'error':
                'Discord a refuse la requete pendant ' + stage + ' (HTTP ' + str(error.status) + ').'}
    return {'ok': False, 'code': 'CONNECTION_ERROR', 'error':
            'Echec pendant ' + stage + ' (' + type(error).__name__ + ').'}


class Session(discord.Client):
    def __init__(self):
        super().__init__()
        self.target = None
        self.auto = False
        self.muted = True
        self.deafened = True
        self.guard = asyncio.Lock()
        self.problem = None

    def voice(self):
        return next(iter(self.voice_clients), None)

    async def leave(self):
        for voice in list(self.voice_clients):
            await asyncio.wait_for(voice.disconnect(force=True), 10)

    def audio_matches(self, channel):
        member = channel.guild.me
        state = member.voice if member else None
        return bool(state and state.channel and state.channel.id == channel.id
                    and state.self_mute == self.muted and state.self_deaf == self.deafened)

    async def apply_audio(self, channel, *, force=False):
        if not force and self.audio_matches(channel):
            return
        await channel.guild.change_voice_state(
            channel=channel, self_mute=self.muted, self_deaf=self.deafened)
        # Discord peut ne pas emettre de nouvel evenement pour un etat inchange.
        # Lire l'etat observe ; ne jamais remplacer celui-ci par les valeurs demandees.
        for _ in range(10):
            if self.audio_matches(channel):
                return
            await asyncio.sleep(0.1)

    async def join(self, channel_id):
        channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            raise ValueError('Indique un ID de salon vocal classique, pas un ID de serveur.')
        member = channel.guild.me
        if member is None:
            raise ValueError('Ton compte doit appartenir au serveur.')
        permissions = channel.permissions_for(member)
        if not permissions.view_channel or not permissions.connect:
            raise ValueError('Ton compte ne peut pas acceder a ce salon.')
        voice = self.voice()
        observed = member.voice
        if (voice and voice.is_connected() and voice.channel.id == channel_id
                and observed and observed.channel and observed.channel.id == channel_id):
            await self.apply_audio(channel)
            self.problem = None
            return
        await self.leave()
        await channel.connect(cls=VoiceClient, timeout=30, reconnect=True,
                              self_mute=self.muted, self_deaf=self.deafened)
        await self.apply_audio(channel)
        self.problem = None

    def state(self):
        voice = self.voice()
        connected = bool(voice and voice.is_connected())
        member = voice.channel.guild.me if connected else None
        member_state = member.voice if member else None
        return {
            'connected': connected,
            'channel': str(voice.channel.id) if connected else None,
            'guild': str(voice.channel.guild.id) if connected else None,
            'mute': member_state.self_mute if member_state else None,
            'deaf': member_state.self_deaf if member_state else None,
            'server_mute': bool(member_state and member_state.mute),
            'server_deaf': bool(member_state and member_state.deaf),
            'auto': self.auto,
            'audio_pending': bool(connected and not self.audio_matches(voice.channel)),
            'desired_mute': self.muted,
            'desired_deaf': self.deafened,
            'target': str(self.target) if self.target else None,
            'problem': self.problem,
        }

    async def execute(self, request):
        command = request['command']
        if command == 'info':
            return self.state()
        if command in ('join', 'auto'):
            # Ne pas retenter une ancienne cible si le changement echoue.
            self.auto = False
            self.target = None
            self.target = int(request['argument'])
            self.auto = command == 'auto'
            try:
                await self.join(self.target)
            except (discord.Forbidden, discord.NotFound, ValueError):
                self.auto = False
                self.target = None
                raise
            except Exception:
                if not self.auto:
                    self.target = None
                    raise
                self.problem = 'Connexion en attente : le mode auto retentera ce salon.'
        elif command == 'disconnect':
            self.auto = False
            self.target = None
            await self.leave()
        elif command in ('mute', 'deaf'):
            value = request['argument']
            if value not in ('on', 'off'):
                raise ValueError('Utilise on ou off.')
            muted = value == 'on' if command == 'mute' else self.muted
            deafened = value == 'on' if command == 'deaf' else self.deafened
            self.muted, self.deafened = muted, deafened
            voice = self.voice()
            if voice and voice.is_connected():
                await self.apply_audio(voice.channel, force=True)
        else:
            raise ValueError('Commande inconnue.')
        return self.state()

    async def maintain(self):
        delay = 30
        while True:
            await asyncio.sleep(delay)
            async with self.guard:
                if not self.auto or not self.target or not self.is_ready():
                    continue
                try:
                    await self.join(self.target)
                    delay = 30
                except (discord.Forbidden, discord.NotFound, ValueError):
                    self.auto = False
                    self.problem = 'Salon inaccessible : mode auto arrete.'
                except Exception:
                    self.problem = 'Reconnexion en attente.'
                    delay = min(delay * 2, 300)


async def main():
    initial = json.loads(await asyncio.to_thread(sys.stdin.readline))
    client = Session()
    running = None
    maintain = None
    ready = None
    stage = 'l\'authentification'
    try:
        # Verifie l'identite AVANT de connecter le compte au Gateway.
        if not await authenticate(client, initial.pop('token'), initial['owner']):
            reply({'ok': False, 'error': 'Ce token ne correspond pas a ton compte Discord.'})
            return
        stage = 'la connexion au Gateway'
        running = asyncio.create_task(client.connect(reconnect=True))
        ready = asyncio.create_task(client.wait_until_ready())
        done, _ = await asyncio.wait([ready, running], timeout=60,
                                    return_when=asyncio.FIRST_COMPLETED)
        if ready not in done or running.done():
            ready.cancel()
            if running.done():
                await running
                raise RuntimeError('Connexion interrompue')
            raise TimeoutError()
        deleted = False
        try:
            channel = await client.fetch_channel(initial['dm_channel'])
            message = await channel.fetch_message(initial['message'])
            if message.author.id == client.user.id:
                await message.delete()
                deleted = True
        except Exception:
            pass
        reply({'ok': True, 'deleted': deleted})
        maintain = asyncio.create_task(client.maintain())
        while not running.done():
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                break
            request = json.loads(line)
            try:
                if request.get('command') == 'info':
                    result = client.state()
                else:
                    async with client.guard:
                        result = await client.execute(request)
                reply({'ok': True, 'state': result})
            except ValueError as error:
                reply({'ok': False, 'error': str(error)})
            except discord.Forbidden:
                reply({'ok': False, 'error': 'Discord refuse cet acces.'})
            except discord.NotFound:
                reply({'ok': False, 'error': 'Salon introuvable ou inaccessible.'})
            except Exception as error:
                # Jamais le texte d'une exception HTTP : il pourrait contenir des secrets.
                reply({'ok': False, 'error': 'Operation impossible (' + type(error).__name__ + ').'})
    except Exception as error:
        reply(connection_error(error, stage))
    finally:
        if ready:
            ready.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await ready
        if maintain:
            maintain.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await maintain
        with contextlib.suppress(Exception):
            await client.close()
        if running:
            running.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await running


if __name__ == '__main__':
    asyncio.run(main())
