from abc import ABC, abstractmethod

class BaseGame(ABC):
    def __init__(self, room_id, players_sids, socketio_instance, options=None):
        """
        初始化遊戲實例。
        Args:
            room_id (str): 遊戲房間的唯一ID。
            players_sids (list): 初始玩家的 session ID 列表。
            socketio_instance: Flask-SocketIO 的實例，用於廣播。
            options (dict, optional): 遊戲的特定選項 (例如，賭注大小、牌組數量等)。
        """
        self.room_id = room_id
        self.players = {} # sid: player_data (例如 {'name': 'Alice', 'chips': 1000, ...})
        self.socketio = socketio_instance
        self.game_state = {} # 存放遊戲內部狀態，例如牌堆、當前回合等
        self.is_game_in_progress = False
        self.options = options if options is not None else {}

        # 可以在這裡初始化初始玩家
        # for sid in players_sids:
        #     self.add_player(sid, {"name": f"Player_{sid[:4]}"}) # 初始名稱

    @abstractmethod
    def add_player(self, player_sid, player_info):
        """添加玩家到遊戲中。 player_info 可能包含 'name' 等。"""
        pass

    @abstractmethod
    def remove_player(self, player_sid):
        """從遊戲中移除玩家。"""
        pass

    @abstractmethod
    def handle_action(self, player_sid, action_type, data):
        """
        處理來自玩家的遊戲動作。
        Args:
            player_sid (str): 執行動作的玩家的 SID。
            action_type (str): 動作的類型 (例如 'bet', 'hit', 'fold')。
            data (dict): 動作附帶的數據 (例如下注金額)。
        Returns:
            dict: 動作的結果，或 None。
        """
        pass

    @abstractmethod
    def start_game(self, triggering_player_sid=None):
        """開始一局新遊戲。"""
        pass

    @abstractmethod
    def get_state_for_player(self, player_sid):
        """
        獲取特定玩家視角的遊戲狀態。
        這很重要，因為不同玩家看到的資訊可能不同 (例如手牌)。
        """
        pass

    def broadcast_state(self, message=None, event_name=None, specific_sid=None):
        """
        向房間內的玩家廣播遊戲狀態。
        可以被所有遊戲子類別使用。
        """
        if event_name is None:
            event_name = f"{self.get_game_type()}_update" # 例如 "texas_holdem_update"

        if specific_sid: # 只發送給特定玩家
            player_state = self.get_state_for_player(specific_sid)
            if message:
                player_state['message'] = message
            self.socketio.emit(event_name, player_state, room=specific_sid)
        else: # 廣播給房間內所有玩家
            # 確保每個玩家都收到他們應該看到的狀態
            for sid in self.players.keys():
                player_state = self.get_state_for_player(sid)
                if message: # 可以附加一個通用訊息
                    player_state['message'] = message
                self.socketio.emit(event_name, player_state, room=sid)
        print(f"Game '{self.get_game_type()}' Room '{self.room_id}': State broadcasted via {event_name}.")

    def send_error_to_player(self, player_sid, error_message):
        """向特定玩家發送錯誤訊息"""
        error_event_name = f"{self.get_game_type()}_error"
        self.socketio.emit(error_event_name, {'message': error_message}, room=player_sid)
        print(f"Game '{self.get_game_type()}' Room '{self.room_id}': Error sent to {player_sid}: {error_message}")

    @abstractmethod
    def get_game_type(self):
        """返回遊戲的類型字串，例如 'texas_holdem'"""
        pass

    def get_player_count(self):
        return len(self.players)

    def end_game(self, results):
        """結束遊戲並廣播結果"""
        self.is_game_in_progress = False
        event_name = f"{self.get_game_type()}_game_over"
        self.socketio.emit(event_name, results, room=self.room_id)
        print(f"Game '{self.get_game_type()}' Room '{self.room_id}': Game over. Results: {results}")