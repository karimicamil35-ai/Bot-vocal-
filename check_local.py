"""Verification locale du chargement et de la serialisation, sans token ni reseau."""
import asyncio
import bot


async def main():
    view = bot.member_container('Classement vocal', '1. Membre : 1h 00m')
    data = view.to_components()
    assert data[0]['type'] == 17
    assert all(child['type'] == 10 for child in data[0]['components'])
    help_embed = bot.embed('Help', bot.HELP).to_dict()
    assert help_embed['color'] == bot.COLOR
    print('Chargement du bot et serialisation Discord : OK')


asyncio.run(main())
