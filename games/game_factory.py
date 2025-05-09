# games/game_factory.py
from games.texas_holdem.logic import TexasHoldemGame
# from games.blackjack.logic import BlackjackGame # 導入其他遊戲

GAME_CLASSES = {
    "texas_holdem": TexasHoldemGame,
    # "blackjack": BlackjackGame,
}

def create_game_instance(game_type, room_id, players_sids, socketio_instance, options=None):
    game_class = GAME_CLASSES.get(game_type)
    if game_class:
        return game_class(room_id, players_sids, socketio_instance, options)
    else:
        raise ValueError(f"Unsupported game type: {game_type}")