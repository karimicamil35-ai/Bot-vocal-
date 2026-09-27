"""Bot de commandes en MP. Les tokens personnels ne sont jamais stockes sur disque."""
import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import time

import discord
from dotenv import load_dotenv
from auth_input import normalize_token

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
WORKER_PYTHON = os.getenv('SELF_PYTHON') or str(
    ROOT / '.venv-self' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python'))
MAX_SESSIONS = max(1, int(os.getenv('MAX_SESSIONS', '60')))
COLOR = 0x2B2D31
HELP = (
    '**Compte**\n'
    '> `!connect TON_TOKEN` — connecter ton propre compte\n'
    '> `!logout` — fermer ta session et oublier le token\n'
    '> `!forget` — fermer ta session et supprimer tes statistiques\n\n'
    '**Vocal**\n'
    '> `!join ID_VOC` — rejoindre un salon\n'
    '> `!auto ID_VOC` — rejoindre et retenter apres une coupure\n'
    '> `!mute on/off` — couper / activer le micro\n'
    '> `!deaf on/off` — couper / activer le casque\n'
    '> `!disconnect` — quitter et arreter le mode auto\n'
    '> `!info` — voir ta connexion et tes reglages\n\n'
    '**Communaute**\n'
    '> `!users` — comptes actuellement inscrits et connectes au service\n'
    '> `!top` — temps vocal mesure des sessions actives\n'
    '> `!help` — afficher cette aide\n\n'
    'En te connectant, tu apparais dans `!users` et `!top` pour les autres inscrits. '
    'Un token donne acces a ton compte : l\'hebergeur peut y acceder en memoire. '
    'Supprime le MP contenant ton token si la suppression automatique echoue.'
)


def embed(title, description):
    result = discord.Embed(title=title, description=description, color=COLOR,
                           timestamp=discord.utils.utcnow())
    result.set_footer(text='Vocal • Espace membres')
    return result


def member_container(title, description):
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(
        discord.ui.TextDisplay('### ' + title),
        discord.ui.TextDisplay(description),
        discord.ui.TextDisplay('-# Mis a jour • <t:' + str(int(time.time())) + ':t>'),
    ))
    return view


class Worker:
    def __init__(self, process):
        self.process = process
        self.lock = asyncio.Lock()
        self.last = time.monotonic()
        self.connected = False

    async def call(self, data, timeout=100):
        async with self.lock:
            if self.process.returncode is not None:
                raise RuntimeError('Session fermee. Reconnecte ton compte avec !connect.')
            self.process.stdin.write((json.dumps(data) + '\n').encode())
            await self.process.stdin.drain()
            try:
                line = await asyncio.wait_for(self.process.stdout.readline(), timeout)
                if not line:
                    raise RuntimeError('Session interrompue. Reconnecte ton compte.')
                return json.loads(line)
            except (TimeoutError, json.JSONDecodeError):
                await self.close()
                raise RuntimeError('Session interrompue ou trop lente. Reconnecte ton compte.')

    async def close(self):
        if self.process.returncode is None:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 8)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()


class Control(discord.Client):
    def __init__(self):
        intents = discord.Intents.none()
        intents.dm_messages = True
        super().__init__(intents=intents, max_messages=None,
                         allowed_mentions=discord.AllowedMentions.none())
        self.sessions = {}
        self.busy = set()
        self.pending = set()
        self.monitor = None
        self.db = sqlite3.connect(ROOT / 'stats.sqlite3')
        self.db.execute('CREATE TABLE IF NOT EXISTS stats (id INTEGER PRIMARY KEY, seconds REAL NOT NULL DEFAULT 0)')
        self.db.commit()

    async def setup_hook(self):
        self.monitor = asyncio.create_task(self.measure())

    async def on_ready(self):
        print('Bot pret : commandes en MP. Aucun token personnel ne sera journalise.', flush=True)
        print(f'Compte bot : {self.user} | ID : {self.user.id}', flush=True)

    async def on_error(self, event_method, *args, **kwargs):
        # Ne pas imprimer les arguments, les messages ou le texte des exceptions.
        import sys
        error_type = sys.exc_info()[0]
        print(f'Erreur evenement {event_method} : {error_type.__name__ if error_type else "inconnue"}', flush=True)

    def record(self, user_id, worker, state):
        now = time.monotonic()
        # Approximation conservative : compte uniquement deux observations connectees.
        if worker.connected and state.get('connected'):
            delta = min(now - worker.last, 60)
            self.db.execute('UPDATE stats SET seconds = seconds + ? WHERE id = ?', (delta, user_id))
            self.db.commit()
        worker.last = now
        worker.connected = state.get('connected', False)

    async def measure_one(self, user_id, worker):
        if user_id in self.busy:
            return
        self.busy.add(user_id)
        try:
            result = await worker.call({'command': 'info'}, timeout=10)
            if result.get('ok'):
                self.record(user_id, worker, result['state'])
        except Exception:
            if self.sessions.get(user_id) is worker:
                self.sessions.pop(user_id, None)
            await worker.close()
        finally:
            self.busy.discard(user_id)

    async def measure(self):
        await self.wait_until_ready()
        while not self.is_closed():
            await asyncio.sleep(30)
            await asyncio.gather(*(self.measure_one(uid, worker)
                                   for uid, worker in list(self.sessions.items())))

    async def connect_account(self, message, token):
        uid = message.author.id
        if uid in self.sessions:
            return embed('Compte', 'Une session existe deja. Utilise `!logout` avant de changer de token.')
        try:
            token = normalize_token(token)
        except ValueError as error:
            return embed('Connexion', str(error) + '\nSupprime le MP contenant le token.')
        if len(self.sessions) + len(self.pending) >= MAX_SESSIONS:
            return embed('Connexion', 'Le service est complet. Reessaie plus tard.')
        self.pending.add(uid)
        worker = None
        try:
            await message.channel.send(embed=embed('Connexion en cours',
                'Verification de ton compte. Cela peut prendre jusqu\'a 100 secondes.'))
            # Aucune information secrete dans les arguments du processus ni dans son environnement.
            env = dict(os.environ)
            env.pop('BOT_TOKEN', None)
            process = await asyncio.create_subprocess_exec(
                WORKER_PYTHON, '-u', str(ROOT / 'worker.py'),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, cwd=ROOT, env=env)
            worker = Worker(process)
            result = await worker.call({'token': token, 'owner': uid,
                                        'dm_channel': message.channel.id, 'message': message.id}, timeout=100)
            if not result.get('ok'):
                await worker.close()
                return embed('Connexion refusee', result.get('error', 'Connexion impossible.') +
                             '\nSupprime ton message contenant le token.')
            self.sessions[uid] = worker
            self.db.execute('INSERT OR IGNORE INTO stats(id) VALUES (?)', (uid,))
            self.db.commit()
            note = ('Le message contenant le token a ete supprime.' if result.get('deleted') else
                    '**Supprime manuellement ton message contenant le token.**')
            return embed('Compte connecte', 'Ta session est prete. Utilise `!join ID_VOC` ou `!auto ID_VOC`.\n' + note)
        except Exception:
            if worker:
                await worker.close()
            return embed('Connexion impossible', 'Verifie les dependances et la configuration du service. '
                         'Supprime ton message contenant le token.')
        finally:
            self.pending.discard(uid)

    async def dispatch_command(self, message, command, argument):
        uid = message.author.id
        if command == 'help':
            return embed('Help', HELP)
        if command == 'ping':
            return embed('Pong', 'Le bot recoit bien tes commandes en MP.')
        if command == 'connect':
            return await self.connect_account(message, argument)
        if command in ('logout', 'forget'):
            worker = self.sessions.pop(uid, None)
            if worker:
                await worker.close()
            if command == 'forget':
                self.db.execute('DELETE FROM stats WHERE id = ?', (uid,))
                self.db.commit()
            return embed('Compte', 'Session fermee.' + (' Statistiques supprimees.' if command == 'forget' else ''))
        worker = self.sessions.get(uid)
        if worker is None:
            return embed('Compte', 'Connecte ton propre compte avec `!connect TON_TOKEN`. Lis `!help` avant.')
        if command in ('top', 'users'):
            rows = self.db.execute('SELECT id, seconds FROM stats ORDER BY seconds DESC').fetchall()
            active = [(member, seconds) for member, seconds in rows if member in self.sessions]
            lines = []
            for rank, (member, seconds) in enumerate(active[:40], 1):
                hours, minutes = divmod(int(seconds) // 60, 60)
                duration = f' : **{hours}h {minutes:02d}m**' if command == 'top' else ''
                lines.append(f'{rank}. <@{member}>{duration}')
            return member_container('Classement vocal' if command == 'top' else 'Membres connectes',
                                    '\n'.join(lines) or 'Aucun membre connecte.')
        if command not in ('join', 'auto', 'mute', 'deaf', 'disconnect', 'info'):
            return embed('Commande inconnue', 'Consulte `!help`.')
        if command in ('join', 'auto') and (not argument.isascii() or not argument.isdigit() or not 15 <= len(argument) <= 22):
            return embed('Salon vocal', 'Utilise un ID de salon vocal : `!' + command + ' ID_VOC`.')
        if command in ('mute', 'deaf') and argument not in ('on', 'off'):
            return embed('Reglage', 'Utilise `!' + command + ' on` ou `!' + command + ' off`.')
        # Seuls les changements de salon necessitent un echantillon avant l'action.
        if command in ('join', 'auto', 'disconnect'):
            before = await worker.call({'command': 'info'})
            if before.get('ok'):
                self.record(uid, worker, before['state'])
        result = await worker.call({'command': command, 'argument': argument})
        if not result.get('ok'):
            return embed('Operation impossible', result.get('error', 'Reessaie plus tard.'))
        state = result['state']
        self.record(uid, worker, state)
        channel = '<#' + state['channel'] + '>' if state['connected'] else 'Deconnecte'
        yes = lambda value: 'Inconnu' if value is None else ('Coupe' if value else 'Actif')
        description = (f'**Salon :** {channel}\n'
                       f'**Micro :** {yes(state["mute"])}\n'
                       f'**Casque :** {yes(state["deaf"])}\n'
                       f'**Reconnexion auto :** {"Oui" if state["auto"] else "Non"}')
        if state.get('server_mute') or state.get('server_deaf'):
            description += '\nLe serveur impose aussi une restriction audio.'
        if state.get('problem'):
            description += '\n' + state['problem']
        if state.get('auto') and state.get('target'):
            description += '\n**Salon maintenu :** <#' + state['target'] + '>'
        if state.get('audio_pending'):
            description += ('\n**Modification en attente :** '
                            f'micro {yes(state["desired_mute"])}, casque {yes(state["desired_deaf"])}. '
                            'Utilise `!info` pour relire l\'etat recu de Discord.')
        return embed('Ta session vocale', description)

    async def on_message(self, message):
        if message.guild is not None or message.author.bot:
            return
        content = message.content.strip()
        message.content = ''
        print('MP recu (contenu masque).', flush=True)
        if not content.startswith('!'):
            await message.channel.send(embed=embed(
                'Commandes en MP',
                'Envoie `!help` pour voir les commandes ou `!ping` pour tester.\n'
                'Un token envoye seul ne lance aucune connexion. '
                'Supprime ce message si tu y as colle un token.'))
            return
        parts = content[1:].split(maxsplit=1)
        if not parts:
            await message.channel.send(embed=embed('Aide', 'Envoie `!help` pour voir les commandes.'))
            return
        command = parts[0].lower()
        argument = parts[1].strip() if len(parts) > 1 else ''
        # Pas de cache des messages ; retire aussi le contenu de l'objet traite.
        message.content = ''
        uid = message.author.id
        if uid in self.busy:
            await message.channel.send(embed=embed('Patiente', 'Une operation est deja en cours.'))
            return
        self.busy.add(uid)
        try:
            answer = await self.dispatch_command(message, command, argument)
            if isinstance(answer, discord.ui.LayoutView):
                await message.channel.send(view=answer)
            else:
                await message.channel.send(embed=answer)
        except Exception as error:
            print(f'Echec de traitement du MP : {type(error).__name__}', flush=True)
            with contextlib.suppress(discord.HTTPException):
                await message.channel.send(embed=embed('Erreur', 'Session indisponible. Essaie `!logout`, puis reconnecte ton compte.'))
        finally:
            self.busy.discard(uid)

    async def close(self):
        if self.monitor:
            self.monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.monitor
        await asyncio.gather(*(worker.close() for worker in list(self.sessions.values())), return_exceptions=True)
        self.sessions.clear()
        self.db.close()
        await super().close()


if __name__ == '__main__':
    token = os.getenv('BOT_TOKEN', '')
    if not token or token.startswith('REMPLACER'):
        raise SystemExit('Configure BOT_TOKEN dans .env avant de lancer le bot.')
    if not Path(WORKER_PYTHON).is_file():
        raise SystemExit('Execute setup.ps1 ou configure SELF_PYTHON dans .env.')
    logging.disable(logging.CRITICAL)
    Control().run(token, log_handler=None)
