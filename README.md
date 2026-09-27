# Vocal — bot de controle et sessions personnelles

Projet Python multiutilisateur : le bot officiel recoit les commandes en MP ;
un processus selfbot distinct connecte le compte de chaque membre en vocal.
Le token du bot officiel et les tokens personnels sont differents.
Le compte associe au token doit correspondre a l'auteur du MP.

## Installation Windows

Python 3.10 minimum, Python 3.12 ou 3.13 recommande pour la disponibilite des extensions natives.

```powershell
.\setup.ps1
```

Ouvre `.env` et renseigne `BOT_TOKEN` avec le token de ton application bot Discord.
Invite ce bot sur un serveur commun aux utilisateurs pour permettre les MP.
Les commandes sont uniquement en MP ; aucun intent privilegie n'est necessaire.
Les deux environnements sont obligatoires : les deux bibliotheques utilisent le nom `discord`.

```powershell
.\.venv-bot\Scripts\python.exe bot.py
```

Dans les MP du bot, commence par `!help`, puis `!connect TON_TOKEN_PERSONNEL`.
Ne communique aucun token dans une conversation avec un assistant ou un salon public.
L'application tente de supprimer le MP contenant le token apres verification du compte.
Si cela echoue, l'utilisateur doit supprimer le message lui-meme. Cette suppression
ne garantit pas l'effacement des copies ou de l'historique cote Discord.

## Commandes

| Commande | Effet |
|---|---|
| `!connect TOKEN` | Ouvre la session de ton propre compte |
| `!join ID_VOC` | Rejoint le salon autorise, sans maintien periodique |
| `!auto ID_VOC` | Rejoint et retente les coupures, avec delai progressif de 30 a 300 secondes |
| `!mute on/off` | Regle le micro du compte |
| `!deaf on/off` | Regle le casque du compte |
| `!disconnect` | Quitte le vocal et desactive auto |
| `!info` | Affiche le salon, les reglages et la connexion |
| `!users` | Liste les sessions inscrites actuellement actives |
| `!top` | Classement des sessions actives, jusqu'a 40 personnes |
| `!logout` | Ferme la session et libere son token |
| `!forget` | Ferme la session et supprime ses statistiques |
| `!help` | Aide en embed sombre |

L'aide utilise un embed gris avec des traits devant les commandes. Le classement
et la liste des membres utilisent des conteneurs Discord simples, sans citations
ni traits devant les lignes. La couleur de fond exacte
depend du theme Discord. Seuls les utilisateurs du service apparaissent dans les listes,
accessibles aux autres inscrits. Le bot officiel est exclu. Les listes sont generees
a la demande ; les statistiques sont echantillonnees toutes les 30 secondes.
Le temps est approximatif, mesure uniquement pendant l'execution du service ; ce n'est
pas un historique Discord. Les identifiants et durees sont conserves dans `stats.sqlite3`.

## Fonctionnement continu et limites

- Laisse le programme tourner sur un ordinateur sans mise en veille ou sur un serveur.
  Ce projet ne fournit ni hebergement, ni garantie de disponibilite 24 h/24.
- Le mode auto gere les pertes de connexion dans la session courante. Un redemarrage
  du programme exige que chacun soumette a nouveau son token et sa commande auto.
  Il garde le salon choisi avec `!auto`, y compris si le compte est deplace depuis
  l'application. La verification periodique se fait toutes les 30 secondes, avec
  un delai pouvant monter a 300 secondes en cas d'erreurs reseau. Les reglages micro
  et casque demandes sont reappliques ; `!info` signale une confirmation encore en attente.
- Les tokens personnels restent en memoire du processus ; ils ne sont ni enregistres
  dans SQLite, ni passes sur la ligne de commande, ni affiches dans les journaux.
  Ce n'est pas un coffre-fort : l'operateur de la machine peut lire cette memoire.
- Le token personnel donne un acces etendu au compte. Utilise uniquement un service
  dont tu controles l'hebergement ou dont tu acceptes explicitement l'operateur.
- Un ID ne donne pas acces a un serveur : le compte doit en etre membre et avoir
  les permissions vocales. Les restrictions imposees par le serveur restent applicables.
- Les comptes restent visibles dans le salon vocal. Aucun mecanisme de dissimulation
  ou de contournement de detection n'est implemente.
- Le micro et le casque sont coupes au depart. `off` change les indicateurs Discord ;
  ce programme ne capture pas le micro du PC et ne joue pas de son.
- Discord interdit les selfbots et peut supprimer les comptes concernes :
  https://support.discord.com/hc/fr/articles/115002192352
- Le transport vocal utilise `discord.py-self[voice]` et ses dependances de chiffrement :
  https://discordpy-self.readthedocs.io/en/latest/api.html
  La version de developpement officielle est utilisee pour les dependances vocales
  recentes ; une nouvelle installation peut donc recuperer une version differente.
  La compatibilite avec le service Discord doit etre verifiee par une connexion reelle.

## Validation

La verification locale de syntaxe ne remplace pas un essai reel avec des comptes autorises.
Aucun token n'est fourni dans le projet. La connexion reelle, le transport vocal et la
tenue sur 24 heures doivent etre verifies sur l'hebergement choisi.
