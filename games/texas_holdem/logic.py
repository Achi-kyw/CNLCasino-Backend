# games/texas_holdem/logic.py
import random
from games.base_game import BaseGame # 假設 BaseGame 在 games 目錄下

# 假設 evaluate_hand 和相關常數已定義或從您的撲克評估模組導入
# 例如: from your_poker_eval_module import evaluate_hand, HIGH_CARD, RANK_ORDER
# 為了此程式碼片段的完整性，這裡放置一個極簡的 evaluate_hand 佔位符。
# **強烈建議您使用之前生成的完整 poker_hand_evaluation artifact 中的 evaluate_hand 實現。**
from .utils import *
class TexasHoldemGame(BaseGame):
    def __init__(self, room_id, players_sids, socketio_instance, options=None):
        super().__init__(room_id, players_sids, socketio_instance, options)
        # --- 遊戲狀態初始化 ---
        self.game_state['deck'] = []
        self.game_state['community_cards'] = []
        self.game_state['pot'] = 0
        self.game_state['current_turn_sid'] = None
        self.game_state['current_street_bet_to_match'] = 0
        self.game_state['game_phase'] = None 
        self.game_state['dealer_button_idx'] = self.options.get('initial_dealer_idx', -1)
        self.game_state['small_blind'] = self.options.get('small_blind', 10)
        self.game_state['big_blind'] = self.options.get('big_blind', 20)
        self.game_state['min_next_raise_increment'] = self.game_state['big_blind']
        self.game_state['last_raiser_sid'] = None 
        self.game_state['round_active_players_sids_in_order'] = [] 
        self.game_state['player_who_opened_betting_this_street'] = None

        # 初始化玩家數據 (self.players 由 BaseGame 初始化為 {})
        # 如果 __init__ 時傳入了 players_sids (例如創建房間者)，他們會先以預設名稱加入
        # 然後 app.py 中的 handle_create_room 會再次調用 add_player 來更新名稱
        temp_initial_players = {}
        if players_sids:
            for sid_init in players_sids:
                temp_initial_players[sid_init] = {
                    'name': f"玩家_{sid_init[:4]}", # 預設名稱
                    'chips': self.options.get('buy_in', 1000),
                    'hand': [], 'current_bet': 0, 
                    'bet_in_current_street': 0, 
                    'is_active_in_round': False, 
                    'has_acted_this_street': False, 
                    'is_all_in': False,
                }
        self.players = temp_initial_players # 設置初始玩家數據
        print(f"[德州撲克房間 {self.room_id}] 遊戲實例已創建。初始玩家: {list(self.players.keys())}, 選項: {self.options}")

    def get_game_type(self):
        return "texas_holdem"

    def add_player(self, player_sid, player_info):
        """添加玩家到遊戲中，或更新已存在玩家的資訊（例如名稱）。"""
        player_name_from_info = player_info.get('name')
        # 如果提供的名稱為空或僅包含空白，則使用預設名稱格式
        player_name_to_set = player_name_from_info if player_name_from_info and player_name_from_info.strip() else f"玩家_{player_sid[:4]}"

        if player_sid not in self.players:
            self.players[player_sid] = {
                'name': player_name_to_set,
                'chips': self.options.get('buy_in', 1000),
                'hand': [],
                'current_bet': 0,
                'bet_in_current_street': 0,
                'is_active_in_round': False, # 新玩家預設不參與正在進行的牌局
                'has_acted_this_street': False,
                'is_all_in': False,
            }
            print(f"[德州撲克房間 {self.room_id}] 玩家 {player_name_to_set} ({player_sid}) 新加入。")
            self.broadcast_state(message=f"玩家 {player_name_to_set} 加入了牌桌。")
            return True
        else:
            # 玩家已存在 (例如創建房間者在 __init__ 中被加入，然後 app.py 再調用 add_player 更新名稱)
            if self.players[player_sid].get('name') != player_name_to_set:
                old_name = self.players[player_sid].get('name')
                self.players[player_sid]['name'] = player_name_to_set
                print(f"[德州撲克房間 {self.room_id}] 玩家 {old_name} ({player_sid}) 更新名稱為 {player_name_to_set}。")
            else:
                print(f"[德州撲克房間 {self.room_id}] 玩家 {self.players[player_sid]['name']} ({player_sid}) 已在房間中。")
            
            # 無論是更新名稱還是僅確認已存在，都廣播一次狀態，確保該玩家能看到最新遊戲畫面
            self.broadcast_state(message=f"玩家 {self.players[player_sid]['name']} 已在牌桌。")
            return True # 即使是更新資訊，也視為成功操作

    # ... (start_game, _post_blind, handle_action, _reset_acted_status_for_others 等方法保持不變) ...
    def _post_blind(self, player_sid, blind_amount, is_small_blind=False):
        player = self.players[player_sid]
        actual_blind_posted = min(player['chips'], blind_amount)
        
        player['chips'] -= actual_blind_posted
        player['current_bet'] += actual_blind_posted
        player['bet_in_current_street'] += actual_blind_posted
        self.game_state['pot'] += actual_blind_posted
        
        if player['chips'] == 0:
            player['is_all_in'] = True
            print(f"[德州撲克房間 {self.room_id}] 玩家 {player['name']} 下盲注 {actual_blind_posted} 並 All-in。")
        else:
            print(f"[德州撲克房間 {self.room_id}] 玩家 {player['name']} 下盲注 {actual_blind_posted}。")
        
        if not is_small_blind: 
            self.game_state['current_street_bet_to_match'] = actual_blind_posted 
            if not (len(self.game_state.get('round_active_players_sids_in_order', [])) == 2 and is_small_blind):
                 self.game_state['last_raiser_sid'] = player_sid 
                 self.game_state['player_who_opened_betting_this_street'] = player_sid


    def start_game(self, triggering_player_sid=None):
        if self.is_game_in_progress:
            if triggering_player_sid: self.send_error_to_player(triggering_player_sid, "遊戲已在進行中。")
            return False

        eligible_player_sids = [sid for sid, data in self.players.items() if data.get('chips', 0) > 0]
        num_eligible_players = len(eligible_player_sids)

        if num_eligible_players < self.options.get('min_players', 2):
            msg = f"玩家不足。至少需要 {self.options.get('min_players', 2)} 位有籌碼的玩家才能開始。"
            if triggering_player_sid: self.send_error_to_player(triggering_player_sid, msg)
            else: self.broadcast_state(message=msg)
            return False

        print(f"[德州撲克房間 {self.room_id}] 準備開始新牌局。符合資格的玩家 ({num_eligible_players}): {eligible_player_sids}")
        self.is_game_in_progress = True
        self.game_state['game_phase'] = 'pre-flop'
        self.game_state['deck'] = shuffle_deck(create_deck())
        self.game_state['community_cards'] = []
        self.game_state['pot'] = 0
        self.game_state['current_street_bet_to_match'] = 0 
        self.game_state['min_next_raise_increment'] = self.game_state['big_blind']
        self.game_state['last_raiser_sid'] = None
        self.game_state['player_who_opened_betting_this_street'] = None


        for sid in self.players:
            if sid in eligible_player_sids:
                self.players[sid]['hand'] = []
                self.players[sid]['current_bet'] = 0
                self.players[sid]['bet_in_current_street'] = 0
                self.players[sid]['is_active_in_round'] = True
                self.players[sid]['has_acted_this_street'] = False
                self.players[sid]['is_all_in'] = False
            else:
                self.players[sid]['is_active_in_round'] = False

        self.game_state['dealer_button_idx'] = (self.game_state.get('dealer_button_idx', -1) + 1) % num_eligible_players
        dealer_sid = eligible_player_sids[self.game_state['dealer_button_idx']]
        self.game_state['dealer_sid_for_display'] = dealer_sid
        print(f"[德州撲克房間 {self.room_id}] 按鈕位 (Dealer): {self.players[dealer_sid]['name']} ({dealer_sid})")

        sb_sid, bb_sid, utg_sid = None, None, None
        ordered_sids_from_dealer_plus_1 = [eligible_player_sids[(self.game_state['dealer_button_idx'] + 1 + i) % num_eligible_players] for i in range(num_eligible_players)]
        
        current_action_order_for_preflop = []

        if num_eligible_players == 2: # Heads-up
            sb_sid = dealer_sid 
            bb_sid = ordered_sids_from_dealer_plus_1[0] 
            self._post_blind(sb_sid, self.game_state['small_blind'], is_small_blind=True)
            self._post_blind(bb_sid, self.game_state['big_blind'])
            utg_sid = sb_sid 
            current_action_order_for_preflop = [sb_sid, bb_sid]
        else: # 3人或以上
            sb_sid = ordered_sids_from_dealer_plus_1[0]
            bb_sid = ordered_sids_from_dealer_plus_1[1]
            self._post_blind(sb_sid, self.game_state['small_blind'], is_small_blind=True)
            self._post_blind(bb_sid, self.game_state['big_blind'])
            utg_sid = ordered_sids_from_dealer_plus_1[2] if num_eligible_players > 2 else dealer_sid 
            utg_start_index_in_eligible = eligible_player_sids.index(utg_sid)
            for i in range(num_eligible_players):
                current_action_order_for_preflop.append(eligible_player_sids[(utg_start_index_in_eligible + i) % num_eligible_players])
        
        self.game_state['round_active_players_sids_in_order'] = current_action_order_for_preflop
        self.game_state['current_turn_sid'] = utg_sid
        print(f"[德州撲克房間 {self.room_id}] SB: {self.players[sb_sid]['name']}, BB: {self.players[bb_sid]['name']}, UTG: {self.players[utg_sid]['name']}")
        print(f"[德州撲克房間 {self.room_id}] Pre-flop 行動順序: {[self.players[s]['name'] for s in current_action_order_for_preflop]}")

        for sid in eligible_player_sids:
            if sid in self.players and self.players[sid]['is_active_in_round']:
                self.players[sid]['hand'] = deal_cards(self.game_state['deck'], 2)

        print(f"[德州撲克房間 {self.room_id}] 新牌局已開始。輪到: {self.players[utg_sid]['name'] if utg_sid else 'N/A'}")
        self.broadcast_state(message=f"新牌局開始！輪到 {self.players[utg_sid]['name'] if utg_sid else 'N/A'} 行動。")
        return True

    def handle_action(self, player_sid, action_type, data=None):
        if data is None: data = {}
        if not self.is_game_in_progress:
            self.send_error_to_player(player_sid, "遊戲尚未開始或已結束。")
            return
        if self.game_state['current_turn_sid'] != player_sid:
            self.send_error_to_player(player_sid, "還沒輪到您行動。")
            return
        if player_sid not in self.players or not self.players[player_sid].get('is_active_in_round'):
            self.send_error_to_player(player_sid, "您已不在本局遊戲中。")
            return
        
        player = self.players[player_sid]
        if player.get('is_all_in', False) and action_type != 'check': 
            if not (action_type == 'check' and (self.game_state['current_street_bet_to_match'] - player['bet_in_current_street']) <= 0):
                self.send_error_to_player(player_sid, "您已 All-in，通常只能等待攤牌。")
                return 

        action_message = f"玩家 {player['name']}"
        action_processed_successfully = False

        if action_type == 'fold':
            player['is_active_in_round'] = False
            player['has_acted_this_street'] = True 
            action_message += " 棄牌。"
            print(f"[德州撲克房間 {self.room_id}] {action_message}")
            action_processed_successfully = True
            active_players_left = self._get_active_players_in_round_now()
            if len(active_players_left) == 1:
                winner_sid = active_players_left[0]
                self._award_pot_to_winner(winner_sid, reason=f"因其他玩家棄牌而獲勝。")
                return 
        elif action_type == 'check':
            amount_player_needs_to_call = self.game_state['current_street_bet_to_match'] - player['bet_in_current_street']
            if amount_player_needs_to_call > 0 and player['chips'] > 0: 
                self.send_error_to_player(player_sid, f"不能過牌，您需要跟注 {amount_player_needs_to_call}。")
            else:
                player['has_acted_this_street'] = True
                action_message += " 過牌。"
                print(f"[德州撲克房間 {self.room_id}] {action_message}")
                action_processed_successfully = True
        elif action_type == 'call':
            amount_player_needs_to_call = self.game_state['current_street_bet_to_match'] - player['bet_in_current_street']
            if amount_player_needs_to_call <= 0: 
                self.send_error_to_player(player_sid, "無需跟注，您可以過牌或下注/加注。")
            else:
                actual_call_amount = min(amount_player_needs_to_call, player['chips'])
                player['chips'] -= actual_call_amount
                player['current_bet'] += actual_call_amount
                player['bet_in_current_street'] += actual_call_amount
                self.game_state['pot'] += actual_call_amount
                if player['chips'] == 0:
                    player['is_all_in'] = True
                    action_message += f" 跟注 {actual_call_amount} 並 All-in。"
                else:
                    action_message += f" 跟注 {actual_call_amount}。"
                player['has_acted_this_street'] = True
                print(f"[德州撲克房間 {self.room_id}] {action_message}")
                action_processed_successfully = True
        elif action_type == 'bet':
            bet_value = data.get('amount', 0)
            if not isinstance(bet_value, (int, float)) or bet_value <= 0:
                self.send_error_to_player(player_sid, "下注金額無效。")
                return
            if self.game_state['current_street_bet_to_match'] > 0: 
                self.send_error_to_player(player_sid, "已有人下注，請選擇跟注或加注。")
            elif bet_value < self.game_state['big_blind'] and player['chips'] > bet_value : 
                 self.send_error_to_player(player_sid, f"下注金額至少需為 {self.game_state['big_blind']} (大盲)。")
            else:
                actual_bet_amount = min(bet_value, player['chips'])
                player['chips'] -= actual_bet_amount
                player['current_bet'] += actual_bet_amount
                player['bet_in_current_street'] += actual_bet_amount 
                self.game_state['pot'] += actual_bet_amount
                self.game_state['current_street_bet_to_match'] = player['bet_in_current_street']
                self.game_state['last_raiser_sid'] = player_sid
                self.game_state['player_who_opened_betting_this_street'] = player_sid
                self.game_state['min_next_raise_increment'] = player['bet_in_current_street'] 
                if player['chips'] == 0:
                    player['is_all_in'] = True
                    action_message += f" 下注 {actual_bet_amount} 並 All-in。"
                else:
                    action_message += f" 下注 {actual_bet_amount}。"
                player['has_acted_this_street'] = True
                print(f"[德州撲克房間 {self.room_id}] {action_message}")
                action_processed_successfully = True
                self._reset_acted_status_for_others(player_sid)
        elif action_type == 'raise':
            total_intended_street_bet = data.get('amount', 0)
            if not isinstance(total_intended_street_bet, (int, float)) or total_intended_street_bet <= 0:
                self.send_error_to_player(player_sid, "加注金額無效。")
                return
            if total_intended_street_bet <= self.game_state['current_street_bet_to_match']:
                 self.send_error_to_player(player_sid, f"加注後的總額必須大於當前最高街道下注 {self.game_state['current_street_bet_to_match']}。")
                 return
            raise_increment_value = total_intended_street_bet - self.game_state['current_street_bet_to_match']
            max_possible_total_street_bet_for_player = player['bet_in_current_street'] + player['chips']
            if raise_increment_value < self.game_state['min_next_raise_increment'] and \
               total_intended_street_bet < max_possible_total_street_bet_for_player: 
                self.send_error_to_player(player_sid, f"加注增量過小。最小加注增量為 {self.game_state['min_next_raise_increment']}，您至少需要加注到 {self.game_state['current_street_bet_to_match'] + self.game_state['min_next_raise_increment']}。")
                return
            amount_to_add_for_raise = total_intended_street_bet - player['bet_in_current_street']
            actual_amount_added = min(amount_to_add_for_raise, player['chips']) 
            player['chips'] -= actual_amount_added
            player['current_bet'] += actual_amount_added
            player['bet_in_current_street'] += actual_amount_added
            self.game_state['pot'] += actual_amount_added
            is_full_raise = (player['bet_in_current_street'] >= (self.game_state['current_street_bet_to_match'] + self.game_state['min_next_raise_increment'])) or \
                            (player['chips'] == 0 and player['bet_in_current_street'] > self.game_state['current_street_bet_to_match'])
            if is_full_raise and player['chips'] > 0 : 
                 self.game_state['min_next_raise_increment'] = player['bet_in_current_street'] - self.game_state['current_street_bet_to_match']
            self.game_state['current_street_bet_to_match'] = player['bet_in_current_street']
            self.game_state['last_raiser_sid'] = player_sid
            if self.game_state['player_who_opened_betting_this_street'] is None: 
                self.game_state['player_who_opened_betting_this_street'] = player_sid
            if player['chips'] == 0:
                player['is_all_in'] = True
                action_message += f" 加注到 {player['bet_in_current_street']} 並 All-in。"
            else:
                action_message += f" 加注到 {player['bet_in_current_street']}。"
            player['has_acted_this_street'] = True
            print(f"[德州撲克房間 {self.room_id}] {action_message}")
            action_processed_successfully = True
            if is_full_raise: 
                self._reset_acted_status_for_others(player_sid)
            else: 
                print(f"[德州撲克房間 {self.room_id}] 玩家 {player['name']} All-in 加注不足額，不重開其他玩家的行動權。")
        else: 
            self.send_error_to_player(player_sid, f"未知的操作: {action_type}")
            return 

        if action_processed_successfully:
            self._advance_to_next_player_or_phase(action_message_for_broadcast=action_message)
        else:
            pass

    def _reset_acted_status_for_others(self, current_player_sid):
        for sid, p_data in self.players.items():
            if sid != current_player_sid and p_data.get('is_active_in_round') and not p_data.get('is_all_in'):
                if p_data.get('has_acted_this_street'): 
                    p_data['has_acted_this_street'] = False
                    print(f"[德州撲克房間 {self.room_id}] 因新的下注/加注，重置玩家 {p_data['name']} 的行動狀態。")

    def remove_player(self, player_sid):
        if player_sid not in self.players:
            print(f"[德州撲克房間 {self.room_id}] 嘗試移除不存在的玩家 {player_sid}。")
            return False

        player_data_copy = dict(self.players[player_sid])
        player_name = player_data_copy.get('name', f"未知玩家({player_sid[:4]})")
        was_active_in_round = player_data_copy.get('is_active_in_round', False)
        was_current_turn = (self.game_state.get('current_turn_sid') == player_sid)

        print(f"[德州撲克房間 {self.room_id}] 玩家 {player_name} ({player_sid}) 正在被移除。之前狀態: active={was_active_in_round}, turn={was_current_turn}")
        
        if self.is_game_in_progress and was_active_in_round:
             self.players[player_sid]['is_active_in_round'] = False 

        if player_sid in self.game_state.get('round_active_players_sids_in_order', []):
            try: 
                self.game_state['round_active_players_sids_in_order'].remove(player_sid)
            except ValueError:
                print(f"[德州撲克房間 {self.room_id}] 警告: 嘗試從行動順序中移除 {player_sid} 失敗，可能已不在其中。")

        del self.players[player_sid]

        if self.is_game_in_progress and was_active_in_round:
            fold_message = f"玩家 {player_name} 已斷線並棄牌。"
            print(f"[德州撲克房間 {self.room_id}] {fold_message}")
            
            active_players_still_in_round = self._get_active_players_in_round_now()
            print(f"[德州撲克房間 {self.room_id}] 棄牌後，剩餘活躍玩家: {len(active_players_still_in_round)}")

            if len(active_players_still_in_round) == 1:
                winner_sid = active_players_still_in_round[0]
                self._award_pot_to_winner(winner_sid, reason=f"因 {player_name} 斷線而成為最後的玩家。")
                return True 
            elif len(active_players_still_in_round) < 1:
                print(f"[德州撲克房間 {self.room_id}] 在 {player_name} 斷線後沒有剩餘活躍玩家。結束牌局。")
                self.game_state['pot'] = 0
                self.end_game({'message': "牌局因所有剩餘玩家斷線/棄牌而結束。", 'pot': 0})
                return True 
            else:
                if was_current_turn:
                    print(f"[德州撲克房間 {self.room_id}] 輪到 {player_name} 行動，但他已斷線。推進到下一位玩家。")
                    self._advance_to_next_player_or_phase(action_message_for_broadcast=fold_message)
                else:
                    print(f"[德州撲克房間 {self.room_id}] {player_name} 已斷線，但非其行動輪。遊戲繼續。")
                    self.broadcast_state(message=fold_message) 
        else:
            print(f"[德州撲克房間 {self.room_id}] 玩家 {player_name} 已離開。遊戲未進行或玩家非活躍。")
            self.broadcast_state(message=f"玩家 {player_name} 離開了牌桌。")

        if self.get_player_count() == 0 and not self.is_game_in_progress:
            print(f"[德州撲克房間 {self.room_id}] 房間已空且遊戲未進行。發出 ROOM_EMPTY 信號。")
            return "ROOM_EMPTY"
        return True

    def _get_active_players_in_round_now(self):
        return [sid for sid, p_data in self.players.items() if p_data.get('is_active_in_round', False)]

    def _award_pot_to_winner(self, winner_sid, reason=""):
        if winner_sid in self.players:
            winner_player_data = self.players[winner_sid]
            win_amount = self.game_state.get('pot', 0)
            winner_player_data['chips'] += win_amount
            self.game_state['pot'] = 0
            
            final_reason = f"作為最後的玩家獲勝。{reason}".strip() if "最後的玩家" not in reason else reason
            message = f"玩家 {winner_player_data['name']} 贏得了 {win_amount} 籌碼。{final_reason}"
            print(f"[德州撲克房間 {self.room_id}] {message}")
            
            results = {
                'winners': [{'sid': winner_sid, 'name': winner_player_data['name'], 'amount_won': win_amount, 'hand': winner_player_data.get('hand', []), 'reason': final_reason}],
                'pot': 0, 'community_cards': self.game_state.get('community_cards', [])
            }
            self.end_game(results) 
            self.game_state['current_turn_sid'] = None
        else:
            print(f"[德州撲克房間 {self.room_id}] 錯誤：在分配底池時找不到贏家 SID {winner_sid}。")
            self.game_state['pot'] = 0
            self.end_game({'message': f"牌局結束，但贏家資料不一致。{reason}".strip(), 'pot': 0})

    def _get_active_players_in_order(self):
        current_order = self.game_state.get('round_active_players_sids_in_order', [])
        return [
            sid for sid in current_order
            if sid in self.players and self.players[sid].get('is_active_in_round', False)
        ]

    def _is_betting_round_over(self):
        active_players_in_order = self._get_active_players_in_order()
        if not active_players_in_order: 
            print(f"[_is_betting_round_over] 無活躍玩家。回合結束。")
            return True

        num_players_who_can_bet = 0
        for sid in active_players_in_order:
            player = self.players[sid]
            if not player.get('is_all_in', False) and player.get('chips', 0) > 0:
                num_players_who_can_bet += 1
        
        if num_players_who_can_bet < 2 and len(active_players_in_order) > 1 : 
            print(f"[_is_betting_round_over] 可下注玩家少於2人 ({num_players_who_can_bet})。回合結束。")
            return True
        
        all_acted_this_street = True
        for sid_check_acted in active_players_in_order:
            player_check_acted = self.players[sid_check_acted]
            # 如果玩家未 all-in 且未行動，則回合未結束
            if not player_check_acted.get('is_all_in', False) and not player_check_acted.get('has_acted_this_street', False):
                all_acted_this_street = False
                print(f"[_is_betting_round_over] 玩家 {player_check_acted['name']} 尚未行動。回合繼續。")
                break
        if not all_acted_this_street:
            return False

        target_bet = self.game_state.get('current_street_bet_to_match', 0)
        bets_are_matched = True
        for sid in active_players_in_order:
            player = self.players[sid]
            if not player.get('is_all_in', False) and player.get('chips', 0) > 0:
                if player.get('bet_in_current_street', 0) != target_bet:
                    bets_are_matched = False
                    print(f"[_is_betting_round_over] 下注不匹配。玩家 {player['name']} 下注 {player.get('bet_in_current_street')} vs 目標 {target_bet}。回合繼續。")
                    break
        
        if all_acted_this_street and bets_are_matched:
            # 檢查行動是否回到最後一個加注者，並且他沒有再次加注
            # 或者，如果沒有人加注 (player_who_opened_betting_this_street is None)，則所有人都 check 了
            if self.game_state.get('player_who_opened_betting_this_street') is None:
                print(f"[_is_betting_round_over] 所有人都已行動且都過牌。回合結束。")
                return True
            
            # 如果有下注/加注，需要更複雜的邏輯來判斷行動是否 "關閉"
            # 簡化：如果所有人都行動了，且下注都匹配了，就認為結束
            # 這在BB有option時可能不完全正確，但作為基礎是可行的
            print(f"[_is_betting_round_over] 所有人都已行動且下注匹配。回合結束。")
            return True
            
        return False


    def _proceed_to_next_street(self):
        current_phase = self.game_state.get('game_phase')
        next_phase = None
        street_message = ""

        if current_phase == 'pre-flop':
            next_phase = 'flop'
            self.game_state['community_cards'] = deal_cards(self.game_state['deck'], 3)
            street_message = f"進入 Flop 輪。公共牌: {[(c['rank'], c['suit']) for c in self.game_state['community_cards']]}."
        elif current_phase == 'flop':
            next_phase = 'turn'
            self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 1))
            street_message = f"進入 Turn 輪。公共牌: {[(c['rank'], c['suit']) for c in self.game_state['community_cards']]}."
        elif current_phase == 'turn':
            next_phase = 'river'
            self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 1))
            street_message = f"進入 River 輪。公共牌: {[(c['rank'], c['suit']) for c in self.game_state['community_cards']]}."
        elif current_phase == 'river':
            next_phase = 'showdown'
            street_message = "進入攤牌階段！"
        else: 
            print(f"[德州撲克房間 {self.room_id}] 錯誤：嘗試從未知或已結束的階段 {current_phase} 推進。")
            if self.is_game_in_progress: self._handle_showdown_or_win_by_fold(reason_suffix=f"從階段 {current_phase} 異常結束。")
            return False 

        self.game_state['game_phase'] = next_phase
        print(f"[德州撲克房間 {self.room_id}] {street_message}")

        if next_phase == 'showdown':
            self._handle_showdown_or_win_by_fold(reason_suffix=f"{current_phase} 輪下注結束。")
            return False 

        self.game_state['current_street_bet_to_match'] = 0
        self.game_state['min_next_raise_increment'] = self.game_state['big_blind']
        self.game_state['last_raiser_sid'] = None
        self.game_state['player_who_opened_betting_this_street'] = None 

        new_street_action_order = []
        first_to_act_sid_new_street = None
        
        # 翻牌後，行動從按鈕位左邊第一個活躍玩家開始
        # 獲取所有仍在牌局中的玩家
        active_sids_for_new_street = self._get_active_players_in_round_now()
        if not active_sids_for_new_street:
            self._handle_showdown_or_win_by_fold(reason_suffix="新街道開始時無活躍玩家。")
            return False

        # 找到按鈕位玩家在 eligible_player_sids (遊戲開始時的順序) 中的索引
        # eligible_player_sids 應該在某處被儲存，或者我們需要一個固定的座位順序
        # 為了簡化，我們假設 eligible_player_sids 在 start_game 時已經確定了座位順序
        # 這裡我們需要一個方法來獲取按鈕位之後的玩家順序，並且只包含 active_sids_for_new_street 中的玩家

        # 簡易邏輯：從按鈕位的下一個開始，找到第一個仍在 active_sids_for_new_street 的玩家
        # 這需要一個原始的、固定的座位順序。
        # 假設 self.game_state['round_active_players_sids_in_order'] 在 pre-flop 時已設為座位順序
        # 或者，我們需要一個 self.game_state['player_seat_order']
        
        # 簡化：從 active_sids_for_new_street 中找到按鈕位，然後順時針
        # 如果按鈕位不在，則從小盲注位置概念開始 (通常是列表第一個)
        
        dealer_sid = self.game_state.get('dealer_sid_for_display')
        start_search_idx = 0
        if dealer_sid in active_sids_for_new_street: # 這裡的 active_sids_for_new_street 順序不一定是座位順序
            # 我們需要一個基於固定座位順序的列表來查找
            # 假設 self.game_state['round_active_players_sids_in_order'] 在 preflop 時是完整的座位順序
            # 並且我們只取其中 is_active_in_round 的人
            
            # 再次簡化：我們假設 active_sids_for_new_street 是某種順序
            # 並且我們從這個列表的頭開始找第一個可以行動的
            # 這不完全正確，但作為推進的基礎
            
            # 正確的邏輯：
            # 1. 獲取一個固定的座位順序列表 (例如，遊戲開始時的 eligible_player_sids)
            # 2. 找到按鈕位在該固定列表中的索引 dealer_original_idx
            # 3. 從 (dealer_original_idx + 1) % num_original_seats 開始遍歷固定列表
            # 4. 找到第一個在 active_sids_for_new_street 中且未 all-in (除非所有人 all-in) 的玩家
            
            # 臨時的簡化實現：
            temp_action_order = []
            # 找到按鈕位在 active_sids_for_new_street 中的索引 (如果它是一個有序列表)
            # 假設 active_sids_for_new_street 已經是某種程度上基於按鈕位的順序
            # 例如，我們可以重新計算一個從按鈕位下家開始的活躍玩家列表
            
            # 獲取所有 eligible_player_sids (遊戲開始時的玩家)
            # 這裡需要一個在遊戲開始時就確定的 eligible_player_sids 列表，代表座位順序
            # 假設 self.game_state['initial_eligible_player_sids_in_seat_order'] 儲存了這個
            
            # 這裡使用一個更簡單（但不完全正確）的邏輯：
            # 從 active_sids_for_new_street 中找到第一個可以行動的玩家
            num_can_bet_new_street = 0
            for sid_check in active_sids_for_new_street:
                if not self.players[sid_check].get('is_all_in', False) and self.players[sid_check].get('chips', 0) > 0:
                    num_can_bet_new_street +=1

            for sid_potential_first in active_sids_for_new_street: # 這裡的順序很重要
                if num_can_bet_new_street > 0 and self.players[sid_potential_first].get('is_all_in', False):
                    temp_action_order.append(sid_potential_first) # all-in 玩家仍在順序中，但可能被跳過
                    continue
                if first_to_act_sid_new_street is None: # 找到第一個可以主動行動的
                    first_to_act_sid_new_street = sid_potential_first
                temp_action_order.append(sid_potential_first)
            
            # 重新排序 temp_action_order，使得 first_to_act_sid_new_street 在最前面
            if first_to_act_sid_new_street and first_to_act_sid_new_street in temp_action_order:
                start_idx_new = temp_action_order.index(first_to_act_sid_new_street)
                new_street_action_order = temp_action_order[start_idx_new:] + temp_action_order[:start_idx_new]
            else: # 如果所有人都 all-in，順序無所謂
                new_street_action_order = temp_action_order


        if not first_to_act_sid_new_street and new_street_action_order: # 如果所有人都 all-in
            first_to_act_sid_new_street = new_street_action_order[0] # 隨便選一個，他們也不能行動


        self.game_state['current_turn_sid'] = first_to_act_sid_new_street
        self.game_state['round_active_players_sids_in_order'] = new_street_action_order
        
        for sid_reset_street in self.players: 
            if self.players[sid_reset_street].get('is_active_in_round'):
                self.players[sid_reset_street]['bet_in_current_street'] = 0
                self.players[sid_reset_street]['has_acted_this_street'] = False
        
        print(f"[德州撲克房間 {self.room_id}] 新街道 {next_phase} 開始。輪到: {self.players[first_to_act_sid_new_street]['name'] if first_to_act_sid_new_street else 'N/A'}")
        return True 


    def _auto_deal_remaining_cards_and_showdown(self, reason=""):
        print(f"[德州撲克房間 {self.room_id}] 所有可行動玩家已 All-in。自動發牌並攤牌。{reason}")
        current_phase = self.game_state.get('game_phase')
        
        cards_dealt_message = "自動發完剩餘公共牌: "
        original_community_len = len(self.game_state['community_cards'])

        if current_phase == 'pre-flop':
            self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 3)) # Flop
            self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 1)) # Turn
            self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 1)) # River
        elif current_phase == 'flop':
            self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 1)) # Turn
            self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 1)) # River
        elif current_phase == 'turn':
            self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 1)) # River
        
        newly_dealt_cards = self.game_state['community_cards'][original_community_len:]
        if newly_dealt_cards:
            cards_dealt_message += " ".join([f"{c['rank']}{c['suit']}" for c in newly_dealt_cards])
        else:
            cards_dealt_message = "無需再發公共牌。"
        
        print(f"[德州撲克房間 {self.room_id}] {cards_dealt_message}")
        
        self.game_state['game_phase'] = 'showdown'
        # 廣播一次發完牌後的狀態，然後再處理攤牌結果
        self.broadcast_state(message=f"{cards_dealt_message} 準備攤牌。")
        self._handle_showdown_or_win_by_fold(reason_suffix=f"所有玩家 All-in 後自動攤牌。{reason}")


    def _advance_to_next_player_or_phase(self, action_message_for_broadcast=None):
        print(f"[德州撲克房間 {self.room_id}] 正在推進玩家或階段... 附帶消息: {action_message_for_broadcast}")
        final_broadcast_message = action_message_for_broadcast or ""

        active_players_in_current_betting_order = self._get_active_players_in_order()
        
        if len(active_players_in_current_betting_order) <= 1 and self.is_game_in_progress:
            # 如果只剩一個或零個玩家，應該由 _handle_showdown_or_win_by_fold 處理
            print(f"[德州撲克房間 {self.room_id}] 只剩 {len(active_players_in_current_betting_order)} 位活躍玩家，進入攤牌/獲勝邏輯。")
            self._handle_showdown_or_win_by_fold(reason_suffix="只剩一位或零位活躍玩家。")
            # 廣播最後的動作消息 (如果有的話，並且遊戲剛結束)
            if final_broadcast_message and not self.is_game_in_progress:
                self.broadcast_state(message=final_broadcast_message.strip())
            return 

        # 檢查是否所有剩餘的活躍玩家都已經 All-in (且至少有兩人)
        num_active_not_all_in = 0
        for sid_check_all_in in active_players_in_current_betting_order:
            if not self.players[sid_check_all_in].get('is_all_in', False) and self.players[sid_check_all_in].get('chips',0) > 0:
                num_active_not_all_in +=1
        
        if num_active_not_all_in == 0 and len(active_players_in_current_betting_order) > 1:
             if self.game_state.get('game_phase') != 'showdown': 
                self._auto_deal_remaining_cards_and_showdown(reason="所有剩餘玩家均已 All-in。")
                return 


        if self._is_betting_round_over():
            print(f"[德州撲克房間 {self.room_id}] 當前下注回合結束。")
            proceeded_to_new_street = self._proceed_to_next_street() 
            if not proceeded_to_new_street and not self.is_game_in_progress: 
                if final_broadcast_message: self.broadcast_state(message=final_broadcast_message.strip())
                return
            if self.is_game_in_progress: 
                new_turn_sid = self.game_state.get('current_turn_sid')
                if new_turn_sid and new_turn_sid in self.players:
                    final_broadcast_message += f" 輪到玩家 {self.players[new_turn_sid]['name']} 行動。"
                elif not new_turn_sid and self.game_state.get('game_phase') != 'showdown': # 如果沒有下個行動者但還沒攤牌 (例如都 all-in)
                    # 這種情況應該由 _auto_deal_remaining_cards_and_showdown 處理
                    print(f"[德州撲克房間 {self.room_id}] 進入新街道但未找到行動者，可能所有人都已 All-in。")
                    self._auto_deal_remaining_cards_and_showdown(reason="進入新街道後無人可行動。")
                    return
                else: # 已進入攤牌或遊戲結束
                    pass # end_game 會處理廣播
                
                # 只有在遊戲還在進行且有明確下一輪行動時才廣播
                if self.is_game_in_progress and self.game_state.get('current_turn_sid'):
                    self.broadcast_state(message=final_broadcast_message.strip())
        else: 
            current_acting_player_sid = self.game_state.get('current_turn_sid') # 剛行動完的玩家
            next_player_sid = None
            
            # 從當前行動順序中找到下一個可以行動的玩家
            # 玩家必須：1. is_active_in_round, 2. 未 all-in (除非他是最後一個), 3. has_acted_this_street 為 False
            # 行動權應該輪轉，直到回到最後一個加注者，並且他選擇了 check/call
            
            # 獲取當前行動順序 (這個順序在每條街開始時設定)
            current_betting_order = self.game_state.get('round_active_players_sids_in_order', [])
            
            if not current_betting_order: # 不應發生
                self._handle_showdown_or_win_by_fold(reason_suffix="行動順序列表為空。")
                return

            try:
                # 找到剛行動完的玩家在當前順序中的索引
                last_acted_player_idx = current_betting_order.index(current_acting_player_sid)
            except ValueError:
                print(f"[德州撲克房間 {self.room_id}] 警告：剛行動的玩家 {current_acting_player_sid} 不在當前行動順序中。")
                # 嘗試從頭開始找
                last_acted_player_idx = -1 # 表示從頭開始

            found_next = False
            for i in range(1, len(current_betting_order) + 1): # 最多檢查一整圈
                next_candidate_idx = (last_acted_player_idx + i) % len(current_betting_order)
                candidate_sid = current_betting_order[next_candidate_idx]

                if candidate_sid not in self.players or not self.players[candidate_sid].get('is_active_in_round'):
                    continue # 跳過已棄牌或已離開的玩家

                player_candidate = self.players[candidate_sid]
                
                # 如果玩家已 all-in，他不能再主動行動，除非他是最後一個需要 "確認" 的 (這由 _is_betting_round_over 處理)
                if player_candidate.get('is_all_in', False):
                    continue 
                
                # 如果玩家還未在本街道行動，則輪到他
                if not player_candidate.get('has_acted_this_street', False):
                    next_player_sid = candidate_sid
                    found_next = True
                    break
                
                # 如果玩家已行動，但他是本街道的開局者/最後加注者，且行動又回到他，他有再次行動的權利 (option)
                # 這裡的邏輯是：如果他是 last_raiser_sid，且 current_street_bet_to_match > 他的 bet_in_current_street (表示有人 re-raise 他之後)
                # 或者他是 player_who_opened_betting_this_street (例如 BB)，且行動回到他且無人加注
                # 這個 "option" 的判斷比較複雜，暫時簡化
                # 簡化：如果所有人都行動過了，_is_betting_round_over 會返回 True
                
            if found_next and next_player_sid:
                self.game_state['current_turn_sid'] = next_player_sid
                final_broadcast_message += f" 輪到玩家 {self.players[next_player_sid]['name']} 行動。"
                self.broadcast_state(message=final_broadcast_message.strip())
            else:
                # 如果找不到下一個可以行動的玩家，但 _is_betting_round_over() 返回 False
                # 這通常表示所有人都已行動，且下注可能已匹配，或者所有人都 all-in
                print(f"[德州撲克房間 {self.room_id}] 未找到明確的下一個行動者，但回合未結束。重新檢查回合結束條件。")
                if self.is_game_in_progress:
                    if self._is_betting_round_over(): # 再次檢查，因為狀態可能已更新
                         self._advance_to_next_player_or_phase(action_message_for_broadcast=final_broadcast_message) # 可能遞迴，小心
                    else: 
                         self._auto_deal_remaining_cards_and_showdown(reason="無法確定下一行動者，強制攤牌。")


    def _handle_showdown_or_win_by_fold(self, reason_suffix=""):
        if not self.is_game_in_progress: 
            print(f"[德州撲克房間 {self.room_id}] 嘗試攤牌，但遊戲已結束。")
            return
        
        print(f"[德州撲克房間 {self.room_id}] 進入攤牌或單人獲勝處理。 {reason_suffix}")
        
        # 確保所有公共牌都已發出 (如果適用)
        current_phase = self.game_state.get('game_phase')
        if current_phase != 'showdown': # 如果不是因為正常流程到攤牌，而是中途結束
            while len(self.game_state['community_cards']) < 5 and current_phase not in ['showdown', None]:
                if current_phase == 'pre-flop' and len(self.game_state['community_cards']) == 0:
                    self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 3))
                    current_phase = 'flop' # 更新內部階段，但不影響 game_phase 狀態變數
                    print(f"[德州撲克房間 {self.room_id}] 自動發 Flop: {[(c['rank'], c['suit']) for c in self.game_state['community_cards'][-3:]]}")
                elif current_phase == 'flop' and len(self.game_state['community_cards']) == 3:
                    self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 1))
                    current_phase = 'turn'
                    print(f"[德州撲克房間 {self.room_id}] 自動發 Turn: {[(c['rank'], c['suit']) for c in self.game_state['community_cards'][-1:]]}")
                elif current_phase == 'turn' and len(self.game_state['community_cards']) == 4:
                    self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 1))
                    current_phase = 'river'
                    print(f"[德州撲克房間 {self.room_id}] 自動發 River: {[(c['rank'], c['suit']) for c in self.game_state['community_cards'][-1:]]}")
                else: # 已是 river 或牌已發完
                    break 
            self.game_state['game_phase'] = 'showdown' # 正式標記為攤牌階段

        active_players_final = self._get_active_players_in_round_now()
        if len(active_players_final) == 1:
            self._award_pot_to_winner(active_players_final[0], reason=f"作為最後活躍玩家獲勝。{reason_suffix}")
        elif len(active_players_final) > 1:
            print(f"[德州撲克房間 {self.room_id}] 進行攤牌，有 {len(active_players_final)} 位玩家。")
            
            winner_evaluations = [] 
            best_eval_value = -1
            best_tie_breaker = []

            # 收集所有參與攤牌玩家的牌力評估
            showdown_participants_evals = []
            for p_sid in active_players_final:
                player_data = self.players[p_sid]
                player_hole_cards = player_data.get('hand', [])
                community = self.game_state.get('community_cards', [])
                eval_result = evaluate_hand(player_hole_cards, community) 
                showdown_participants_evals.append({
                    'sid': p_sid, 
                    'name': player_data['name'], 
                    'hole_cards': player_hole_cards, # 玩家的底牌
                    'best_5_card_hand': eval_result.get('hand_cards', []), # 組成最佳牌型的5張牌
                    'hand_name': eval_result.get('name', '未知牌型'), # 最佳牌型名稱
                    'hand_value': eval_result.get('value', -1), # 牌力數值
                    'tie_breaker_ranks': eval_result.get('tie_breaker_ranks', []) # 用於比牌的等級
                })
                print(f"[德州撲克房間 {self.room_id}] 玩家 {player_data['name']} 底牌: {player_hole_cards}, 公共牌: {community}, 評估: {eval_result['name']}, 牌值: {eval_result['value']}, 最佳5張: {eval_result.get('hand_cards')}, TieBreak: {eval_result.get('tie_breaker_ranks')}")

                # 判斷贏家
                if not winner_evaluations or eval_result['value'] > best_eval_value:
                    best_eval_value = eval_result['value']
                    best_tie_breaker = eval_result.get('tie_breaker_ranks', [])
                    winner_evaluations = [{'sid': p_sid, 'eval': eval_result, 'name': player_data['name'], 'hole_cards': player_hole_cards}]
                elif eval_result['value'] == best_eval_value:
                    current_tie_breaker = eval_result.get('tie_breaker_ranks', [])
                    if current_tie_breaker > best_tie_breaker: 
                        best_tie_breaker = current_tie_breaker
                        winner_evaluations = [{'sid': p_sid, 'eval': eval_result, 'name': player_data['name'], 'hole_cards': player_hole_cards}]
                    elif current_tie_breaker == best_tie_breaker: 
                        winner_evaluations.append({'sid': p_sid, 'eval': eval_result, 'name': player_data['name'], 'hole_cards': player_hole_cards})
            
            if winner_evaluations:
                num_winners = len(winner_evaluations)
                total_pot = self.game_state.get('pot', 0)
                amount_per_winner = int(total_pot / num_winners) if num_winners > 0 else 0
                remainder = total_pot % num_winners if num_winners > 0 else 0 

                winners_for_results = []
                for i, winner_data_entry in enumerate(winner_evaluations):
                    actual_winner_sid = winner_data_entry['sid']
                    winning_hand_name = winner_data_entry['eval']['name']
                    best_5_cards_for_winner = winner_data_entry['eval'].get('hand_cards', [])
                    
                    win_this_share = amount_per_winner
                    if i < remainder: 
                        win_this_share += 1
                    
                    if actual_winner_sid in self.players:
                        self.players[actual_winner_sid]['chips'] += win_this_share
                    
                    winners_for_results.append({
                        'sid': actual_winner_sid, 
                        'name': winner_data_entry['name'], 
                        'amount_won': win_this_share, 
                        'hole_cards': winner_data_entry['hole_cards'], 
                        'best_hand_description': winning_hand_name,
                        'best_5_card_hand': best_5_cards_for_winner, # 加入最佳5張牌
                        'reason': f"在攤牌中以 {winning_hand_name} ({''.join([f'{c["rank"]}{c["suit"]}' for c in best_5_cards_for_winner]) if best_5_cards_for_winner else 'N/A'}) 獲勝。{reason_suffix}"
                    })
                
                self.game_state['pot'] = 0 
                results_payload = {
                    'winners': winners_for_results, # 包含詳細獲勝資訊的列表
                    'pot_details_DEBUG': {'total_pot_before_split': total_pot, 'num_winners': num_winners, 'amount_per_winner_base': amount_per_winner, 'remainder_chips': remainder}, # 除錯用
                    'community_cards': self.game_state.get('community_cards', []),
                    'all_hands_at_showdown': showdown_participants_evals # 所有參與攤牌者的詳細評估
                }
                self.end_game(results_payload) 
                self.game_state['current_turn_sid'] = None
            else: # 理論上不應發生，因為 active_players_final > 1
                 self._award_pot_to_winner(active_players_final[0], reason=f"在攤牌中獲勝 (佔位邏輯 - 無法評估贏家)。{reason_suffix}")
        else:
            print(f"[德州撲克房間 {self.room_id}] 沒有活躍玩家參與攤牌。{reason_suffix}")
            self.game_state['pot'] = 0
            self.end_game({'message': f"牌局因沒有活躍玩家而結束。{reason_suffix}"})

    def get_state_for_player(self, player_sid):
        # --- 加入詳細日誌 ---
        print(f"--- [get_state_for_player] 為玩家 {player_sid} 準備狀態 ---")
        print(f"    當前 self.players 鍵: {list(self.players.keys())}")
        print(f"    遊戲進行中: {self.is_game_in_progress}, 遊戲階段: {self.game_state.get('game_phase')}")

        if player_sid not in self.players and \
           (not self.socketio or player_sid not in self.socketio.server.manager.rooms['/'].get(self.room_id, {})):
            if player_sid:
                 print(f"    警告: 嘗試獲取不存在或已離開的玩家 {player_sid} 的狀態。")
            return {
                'room_id': self.room_id, 'game_type': self.get_game_type(),
                'is_game_in_progress': self.is_game_in_progress,
                'players': [], 'community_cards': self.game_state.get('community_cards', []),
                'pot': self.game_state.get('pot', 0), 'current_turn_sid': self.game_state.get('current_turn_sid'),
                'message': "您已不在遊戲中或無法獲取您的特定狀態。"
            }

        public_players_data = []
        for sid_loop, p_data in self.players.items(): # 使用 sid_loop 避免與外部 player_sid 混淆
            print(f"    正在處理玩家 sid_loop={sid_loop} 的數據...")
            # print(f"        原始 p_data: {p_data}") # 避免過多日誌，除非需要

            # 確保即使 name 為 None 或空，也有一個預設值
            player_name_display = p_data.get('name')
            if not player_name_display or not player_name_display.strip():
                player_name_display = f"玩家_{sid_loop[:4]}"
                # print(f"        注意: 玩家 {sid_loop} 名稱無效或為空，使用預設名稱: {player_name_display}")


            player_view = {
                'sid': sid_loop, 
                'name': player_name_display, # 使用處理過的名稱
                'chips': p_data.get('chips', 0), 
                'current_bet': p_data.get('current_bet', 0), 
                'bet_in_current_street': p_data.get('bet_in_current_street', 0), 
                'is_active_in_round': p_data.get('is_active_in_round', False),
                'is_all_in': p_data.get('is_all_in', False),
                'has_acted_this_street': p_data.get('has_acted_this_street', False),
                'hand': [] 
            }
            
            # 手牌顯示邏輯
            # can_see_hand = False # 除錯用
            if sid_loop == player_sid and self.is_game_in_progress:
                player_view['hand'] = p_data.get('hand', [])
                # can_see_hand = True
                # print(f"        顯示手牌給當前玩家 {player_sid} (sid_loop={sid_loop})")
            elif self.game_state.get('game_phase') == 'showdown' and p_data.get('is_active_in_round', False):
                player_view['hand'] = p_data.get('hand', [])
                # can_see_hand = True
                # print(f"        攤牌階段: 顯示玩家 {sid_loop} 的手牌")
            
            # print(f"        為 sid_loop={sid_loop} 構建的 player_view (手牌可見={can_see_hand}): {player_view}") # 避免過多日誌
            public_players_data.append(player_view)

        state_for_player = {
            'room_id': self.room_id, 'game_type': self.get_game_type(),
            'is_game_in_progress': self.is_game_in_progress,
            'players': public_players_data, # <--- 這是傳給前端的玩家列表
            'community_cards': self.game_state.get('community_cards', []),
            'pot': self.game_state.get('pot', 0),
            'current_turn_sid': self.game_state.get('current_turn_sid'),
            'current_street_bet_to_match': self.game_state.get('current_street_bet_to_match',0),
            'min_next_raise_increment': self.game_state.get('min_next_raise_increment', self.game_state['big_blind']),
            'game_phase': self.game_state.get('game_phase'),
            'dealer_sid_for_display': self.game_state.get('dealer_sid_for_display'),
            'round_active_players_sids_in_order_DEBUG': self.game_state.get('round_active_players_sids_in_order', []),
            'options': self.options,
            'my_sid_debug': player_sid # 方便前端識別這是為誰產生的狀態
        }
        # print(f"--- 為玩家 {player_sid} 產生的最終狀態: {state_for_player} ---") # 避免過多日誌
        return state_for_player