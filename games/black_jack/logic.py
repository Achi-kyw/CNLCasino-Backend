# games/texas_holdem/logic.py
import random
from games.base_game import BaseGame
# 你可能需要從 .state.py 導入德州撲克特定的資料結構 (如果有的話)
# from .state import SUITS, RANKS, create_deck, shuffle_deck, deal_cards, evaluate_hand (範例)

# --- 假設德州撲克相關函式 (create_deck, deal_cards, evaluate_hand, etc.) 在此或被導入 ---
# 為了簡潔，這裡省略了完整的德州撲克邏輯實現細節，重點是類別結構
# 你需要把之前 game_logic.py 的 GAME_ROOM 相關邏輯移到 TexasHoldemGame 的實例變數中

# (範例) 假設這些函式已經定義
def create_deck(): return [{'rank': r, 'suit': s} for s in ['H','D','C','S'] for r in ['2','A']] #極簡
def shuffle_deck(deck): random.shuffle(deck); return deck
def deal_cards(deck, num): return [deck.pop() for _ in range(num)] if len(deck) >= num else []
def evaluate_hand(hand, community): return {'name': 'High Card', 'value': 0} #極簡

class TexasHoldemGame(BaseGame):
    def __init__(self, room_id, players_sids, socketio_instance, options=None):
        super().__init__(room_id, players_sids, socketio_instance, options)
        self.game_state['deck'] = []
        self.game_state['community_cards'] = []
        self.game_state['pot'] = 0
        self.game_state['current_turn_sid'] = None
        self.game_state['current_bet_to_match'] = 0
        self.game_state['game_phase'] = None # 'pre-flop', 'flop', 'turn', 'river', 'showdown'
        self.game_state['dealer_button_idx'] = 0 # 相對於 self.players 的順序
        self.game_state['small_blind'] = self.options.get('small_blind', 10)
        self.game_state['big_blind'] = self.options.get('big_blind', 20)
        self.game_state['min_raise'] = self.options.get('big_blind', 20) * 2
        self.game_state['last_raiser_sid'] = None
        # 初始化玩家資料結構
        initial_players_data = {}
        if players_sids: # 如果創建時就有玩家
            for sid in players_sids:
                initial_players_data[sid] = {
                    'name': f"Player_{sid[:4]}", # 初始名稱
                    'chips': self.options.get('buy_in', 1000),
                    'hand': [],
                    'current_bet': 0,
                    'is_active_in_round': False, # 是否參與本局
                    'has_acted_this_round': False
                }
        self.players = initial_players_data


    def get_game_type(self):
        return "texas_holdem"

    def add_player(self, player_sid, player_info):
        if player_sid not in self.players:
            self.players[player_sid] = {
                'name': player_info.get('name', f"Player_{player_sid[:4]}"),
                'chips': self.options.get('buy_in', 1000), # 玩家加入時的初始籌碼
                'hand': [],
                'current_bet': 0,
                'is_active_in_round': False,
                'has_acted_this_round': False
            }
            print(f"[TexasHoldem Room {self.room_id}] Player {self.players[player_sid]['name']} added.")
            self.broadcast_state(message=f"Player {self.players[player_sid]['name']} joined the table.")
            return True
        return False

    def remove_player(self, player_sid):
        if player_sid in self.players:
            player_name = self.players[player_sid]['name']
            del self.players[player_sid]
            print(f"[TexasHoldem Room {self.room_id}] Player {player_name} removed.")
            # 如果遊戲正在進行，需要處理該玩家的退出邏輯 (例如棄牌)
            if self.is_game_in_progress:
                # TODO: 處理玩家中途離開的邏輯，例如自動棄牌
                # 可能需要檢查是否只剩一個玩家，若是則該玩家獲勝
                pass
            self.broadcast_state(message=f"Player {player_name} left the table.")
            if self.get_player_count() == 0 and not self.is_game_in_progress: # 如果房間沒人了且遊戲沒在進行
                return "ROOM_EMPTY" # 特殊返回值，讓 app.py 知道可以清理房間
            return True
        return False

    def _get_active_players_in_order(self):
        # TODO: 實現德州撲克中正確的玩家行動順序邏輯 (基於按鈕位)
        # 這裡僅為示意，返回所有 is_active_in_round 的玩家 SID 列表
        player_sids_ingame = [sid for sid, data in self.players.items() if data['is_active_in_round']]
        # 這裡需要根據 self.game_state['dealer_button_idx'] 和 player_sids_ingame 來排序
        # 假設 player_sids_ingame 已經是某種基礎順序 (例如加入順序)
        if not player_sids_ingame: return []

        num_players = len(player_sids_ingame)
        # dealer_sid = player_sids_ingame[self.game_state['dealer_button_idx'] % num_players]
        # start_idx = (self.game_state['dealer_button_idx'] + 1) % num_players # 小盲注玩家索引
        # ordered_sids = [player_sids_ingame[(start_idx + i) % num_players] for i in range(num_players)]
        # return [sid for sid in ordered_sids if self.players[sid]['is_active_in_round'] and self.players[sid]['chips'] > 0]
        return player_sids_ingame # <<<< 待實現正確排序

    def start_game(self, triggering_player_sid=None):
        if self.is_game_in_progress:
            self.send_error_to_player(triggering_player_sid, "Game already in progress.")
            return False
        if len(self.players) < self.options.get('min_players', 2):
            msg = f"Not enough players. Need at least {self.options.get('min_players', 2)}."
            if triggering_player_sid: self.send_error_to_player(triggering_player_sid, msg)
            else: self.broadcast_state(message=msg) # 如果是系統自動嘗試開始
            return False

        self.is_game_in_progress = True
        self.game_state['game_phase'] = 'pre-flop'
        self.game_state['deck'] = shuffle_deck(create_deck())
        self.game_state['community_cards'] = []
        self.game_state['pot'] = 0
        self.game_state['current_bet_to_match'] = self.game_state['big_blind']
        self.game_state['min_raise'] = self.game_state['big_blind'] * 2
        self.game_state['last_raiser_sid'] = None


        # 重置玩家本局狀態
        player_sids_this_round = list(self.players.keys()) # 參與本局的玩家
        for sid in player_sids_this_round:
            self.players[sid]['hand'] = []
            self.players[sid]['current_bet'] = 0
            self.players[sid]['is_active_in_round'] = True # 假設所有加入的玩家都參與
            self.players[sid]['has_acted_this_round'] = False

        # TODO: 決定按鈕位 (dealer_button_idx)，大小盲注玩家並扣除盲注
        # 假設 player_sids_this_round[self.game_state['dealer_button_idx']] 是按鈕
        # sb_sid = ...; bb_sid = ...
        # self.players[sb_sid]['chips'] -= self.game_state['small_blind']; self.players[sb_sid]['current_bet'] = self.game_state['small_blind']
        # self.players[bb_sid]['chips'] -= self.game_state['big_blind']; self.players[bb_sid]['current_bet'] = self.game_state['big_blind']
        # self.game_state['pot'] = self.game_state['small_blind'] + self.game_state['big_blind']
        # self.game_state['last_raiser_sid'] = bb_sid # 大盲是第一個 "加注者"

        # 發底牌
        for sid in player_sids_this_round:
            if self.players[sid]['is_active_in_round']:
                self.players[sid]['hand'] = deal_cards(self.game_state['deck'], 2)

        # TODO: 決定第一個行動的玩家 (大盲後一位)
        # self.game_state['current_turn_sid'] = ...

        print(f"[TexasHoldem Room {self.room_id}] Game started.")
        self.broadcast_state(message="New round started!")
        return True

    def handle_action(self, player_sid, action_type, data):
        if not self.is_game_in_progress or self.game_state['current_turn_sid'] != player_sid:
            self.send_error_to_player(player_sid, "Not your turn or game not in progress.")
            return None

        player = self.players[player_sid]
        action_result = None
        # TODO: 根據 action_type ('fold', 'check', 'call', 'bet', 'raise') 和 data 更新遊戲狀態
        # 例如:
        # if action_type == 'fold':
        #     player['is_active_in_round'] = False
        #     action_result = {'player': player['name'], 'action': 'fold'}
        #     # 檢查是否只剩一人
        #     active_players = [p for p_sid, p in self.players.items() if p['is_active_in_round']]
        #     if len(active_players) == 1:
        #         winner_sid = active_players[0]['sid_placeholder'] # 需要存 sid
        #         # ...處理獲勝邏輯...
        #         self.end_game(...)
        #         return
        # ... 其他動作 ...

        # 處理完動作後，決定下一個玩家或進入下一階段
        # self._advance_to_next_player_or_phase()

        self.broadcast_state(message=f"{player['name']} {action_type} {data.get('amount','')}")
        return action_result # 可以返回動作的詳細結果，或由 broadcast_state 處理

    def _advance_to_next_player_or_phase(self):
        # TODO: 實現輪到下一個玩家或進入下一輪下注 (flop, turn, river, showdown) 的邏輯
        # 如果一輪下注結束:
        #   self.game_state['current_bet_to_match'] = 0
        #   self.game_state['min_raise'] = self.game_state['big_blind'] (通常)
        #   for p_sid in self.players: self.players[p_sid]['has_acted_this_round'] = False
        #   if self.game_state['game_phase'] == 'pre-flop':
        #       self.game_state['game_phase'] = 'flop'
        #       self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 3))
        #       # 設定新的 current_turn_sid (通常是按鈕位後第一個活躍玩家)
        #   elif ...
        #   elif self.game_state['game_phase'] == 'river':
        #       self._handle_showdown()
        #       return
        # 否則，找到下一個 current_turn_sid
        pass

    def _handle_showdown(self):
        # TODO: 實現攤牌比大小邏輯
        # active_showdown_players = ...
        # winning_sids = []
        # best_hand_eval = None
        # for sid in active_showdown_players:
        #    hand_eval = evaluate_hand(self.players[sid]['hand'], self.game_state['community_cards'])
        #    # ... 比較牌型 ...
        # # 分配底池
        # self.end_game({'winners': ..., 'pot_won': ...})
        pass


    def get_state_for_player(self, player_sid):
        """為特定玩家準備遊戲狀態，隱藏其他玩家的手牌等敏感資訊。"""
        if player_sid not in self.players: return None # 玩家已離開

        public_players_data = []
        for sid, p_data in self.players.items():
            player_view = {
                'sid': sid, # 前端可能不需要sid，用name或位置代替
                'name': p_data['name'],
                'chips': p_data['chips'],
                'current_bet': p_data['current_bet'],
                'is_active_in_round': p_data['is_active_in_round'],
                'has_acted_this_round': p_data['has_acted_this_round']
            }
            if sid == player_sid: # 當前玩家，可以看到自己的手牌
                player_view['hand'] = p_data.get('hand', [])
            elif self.game_state['game_phase'] == 'showdown' and p_data['is_active_in_round']: # 攤牌階段
                player_view['hand'] = p_data.get('hand', []) # 顯示所有參與攤牌玩家的手牌
            else:
                player_view['hand'] = [] # 其他情況不顯示手牌 (或只顯示牌背)
            public_players_data.append(player_view)

        state_for_player = {
            'room_id': self.room_id,
            'game_type': self.get_game_type(),
            'is_game_in_progress': self.is_game_in_progress,
            'players': public_players_data,
            'community_cards': self.game_state.get('community_cards', []),
            'pot': self.game_state.get('pot', 0),
            'current_turn_sid': self.game_state.get('current_turn_sid'),
            'current_bet_to_match': self.game_state.get('current_bet_to_match',0),
            'min_raise': self.game_state.get('min_raise',0),
            'game_phase': self.game_state.get('game_phase'),
            'dealer_sid': None, # TODO: 根據 dealer_button_idx 找出 dealer_sid
            'options': self.options # 遊戲選項也發送給客戶端
            # ... 其他德州撲克需要的公開狀態 ...
        }
        return state_for_player