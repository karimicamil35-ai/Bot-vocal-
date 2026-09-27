"""Traitement local des secrets, sans affichage ni enregistrement."""


def normalize_token(value):
    if not isinstance(value, str):
        raise ValueError('Le token doit etre du texte.')
    value = value.strip()
    for _ in range(3):
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'", '`'):
            value = value[1:-1].strip()
        else:
            break
    if value.lower().startswith(('bot ', 'bearer ')):
        raise ValueError('Colle uniquement le token personnel, sans prefixe Bot ou Bearer.')
    if not value or len(value) > 512 or not value.isascii() or any(c.isspace() for c in value):
        raise ValueError('Token mal colle : retire les espaces, retours a la ligne et caracteres invisibles.')
    return value
