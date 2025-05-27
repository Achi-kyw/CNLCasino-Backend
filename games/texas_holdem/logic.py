# games/texas_holdem/logic.py
import random
import eventlet
from games.base_game import BaseGame # 假設 BaseGame 在 games 目錄下

from .utils import *
class TexasHoldemGame(BaseGame):
    def __init__(self, room_id, players_sids, socketio_instance, options=None):
        super().__init__(room_id, players_sids, socketio_instance, options)
        # --- 遊戲狀態初始化 (加入計時器相關) ---
        self.game_state['deck'] = []
        self.game_state['community_cards'] = []
        self.game_state['pot'] = 0
        self.game_state['current_turn_sid'] = None
        self.game_state['current_street_bet_to_match'] = 0
        self.game_state['game_phase'] = None
        self.game_state['dealer_button_idx'] = self.options.get('initial_dealer_idx', -1)
        self.game_state['small_blind'] = self.options.get('small_blind', 10)
        self.game_state['big_blind'] = self.options.get('big_blind', 20)
        self.game_state['timeout_seconds'] = self.options.get('timeout_seconds', 60)
        self.game_state['min_next_raise_increment'] = self.game_state['big_blind']
        self.game_state['last_raiser_sid'] = None
        self.game_state['round_active_players_sids_in_order'] = []
        self.game_state['player_who_opened_betting_this_street'] = None

        self.player_action_timers = {} # sid: eventlet_greenthread_object
        self.player_timer_instance_ids = {} # sid: integer_instance_id

        self.host_sid = players_sids[0] if players_sids else None
        if self.host_sid:
            print(f"[德州撲克房間 {self.room_id}] 房主已設定為: {self.host_sid}")

        temp_initial_players = {}
        if players_sids:
            for sid_init in players_sids:
                temp_initial_players[sid_init] = {
                    'name': f"玩家_{sid_init[:4]}",
                    'chips': self.options.get('buy_in', 1000),
                    'hand': [], 'current_bet': 0,
                    'bet_in_current_street': 0,
                    'is_active_in_round': False,
                    'has_acted_this_street': False,
                    'is_all_in': False,
                    'disconnected': False
                }
        self.players = temp_initial_players
        print(f"[德州撲克房間 {self.room_id}] 遊戲實例已創建。初始玩家: {list(self.players.keys())}, 選項: {self.options}")
    def _timer_countdown(self, player_sid, expected_instance_id):
        print(f"[德州撲克房間 {self.room_id}] _timer_countdown CALLED for {player_sid} with expected_instance_id {expected_instance_id}.")
        current_instance_id_for_player = self.player_timer_instance_ids.get(player_sid)
        print(f"    Actual current instance_id for {player_sid} is {current_instance_id_for_player}. Current turn: {self.game_state.get('current_turn_sid')}")

        if current_instance_id_for_player != expected_instance_id:
            print(f"[德州撲克房間 {self.room_id}] Stale timer (ID {expected_instance_id} vs current {current_instance_id_for_player}) for {player_sid} fired. Ignoring.")
            return
        if self.is_game_in_progress and \
            self.game_state.get('current_turn_sid') == player_sid and \
            player_sid in self.players and \
            self.players[player_sid].get('is_active_in_round'):

            player_name = self.players[player_sid]['name']
            print(f"[德州撲克房間 {self.room_id}] 玩家 {player_name} ({player_sid}) 剩餘三秒 (timer_id {expected_instance_id})。")

            self.players[player_sid]['is_active_in_round'] = False
            self.players[player_sid]['has_acted_this_street'] = True

            if player_sid in self.player_action_timers:
                print(f"[德州撲克房間 {self.room_id}] 從 _timer_countdown (超時執行) 中移除 {player_sid} 的計時器 greenthread 引用。")
                del self.player_action_timers[player_sid]

            self.broadcast_state(message=f"玩家 {player_sid} 剩餘三秒。")
        else:
            print(f"[德州撲克房間 {self.room_id}] 玩家 {player_sid} (timer_id {expected_instance_id}) 超時回調，但條件不滿足（可能已行動/非其回合/遊戲結束）。")
            if player_sid in self.player_action_timers:
                 print(f"[德州撲克房間 {self.room_id}] 條件不滿足的超時回調，檢查是否需要清理 player_action_timers 中的 {player_sid}。")
                 if current_instance_id_for_player == expected_instance_id and player_sid in self.player_action_timers:
                     del self.player_action_timers[player_sid]
    def _auto_fold_player(self, player_sid_to_fold, expected_instance_id):
        print(f"[德州撲克房間 {self.room_id}] _auto_fold_player CALLED for {player_sid_to_fold} with expected_instance_id {expected_instance_id}.")
        current_instance_id_for_player = self.player_timer_instance_ids.get(player_sid_to_fold)
        print(f"    Actual current instance_id for {player_sid_to_fold} is {current_instance_id_for_player}. Current turn: {self.game_state.get('current_turn_sid')}")

        if current_instance_id_for_player != expected_instance_id:
            print(f"[德州撲克房間 {self.room_id}] Stale timer (ID {expected_instance_id} vs current {current_instance_id_for_player}) for {player_sid_to_fold} fired. Ignoring.")
            return
        if self.is_game_in_progress and \
           self.game_state.get('current_turn_sid') == player_sid_to_fold and \
           player_sid_to_fold in self.players and \
           self.players[player_sid_to_fold].get('is_active_in_round'):

            player_name = self.players[player_sid_to_fold]['name']
            print(f"[德州撲克房間 {self.room_id}] 玩家 {player_name} ({player_sid_to_fold}) 超時 (timer_id {expected_instance_id})，執行自動棄牌。")

            self.players[player_sid_to_fold]['is_active_in_round'] = False
            self.players[player_sid_to_fold]['has_acted_this_street'] = True

            if player_sid_to_fold in self.player_action_timers:
                print(f"[德州撲克房間 {self.room_id}] 從 _auto_fold_player (超時執行) 中移除 {player_sid_to_fold} 的計時器 greenthread 引用。")
                del self.player_action_timers[player_sid_to_fold]

            timeout_message = f"玩家 {player_name} 超時，自動棄牌。"

            active_players_left = self._get_active_players_in_round_now()
            if len(active_players_left) == 1:
                winner_sid = active_players_left[0]
                self._award_pot_to_winner(winner_sid, reason=f"因 {player_name} 超時棄牌而獲勝。")
            elif len(active_players_left) < 1:
                print(f"[德州撲克房間 {self.room_id}] 在 {player_name} 超時棄牌後沒有剩餘活躍玩家。結束牌局。")
                self.game_state['pot'] = 0
                self.end_game({'message': "牌局因所有剩餘玩家棄牌/超時而結束。", 'pot': 0})
            else:
                self._advance_to_next_player_or_phase(action_message_for_broadcast=timeout_message)
        else:
            print(f"[德州撲克房間 {self.room_id}] 玩家 {player_sid_to_fold} (timer_id {expected_instance_id}) 超時回調，但條件不滿足（可能已行動/非其回合/遊戲結束）。")
            if player_sid_to_fold in self.player_action_timers:
                 print(f"[德州撲克房間 {self.room_id}] 條件不滿足的超時回調，檢查是否需要清理 player_action_timers 中的 {player_sid_to_fold}。")
                 if current_instance_id_for_player == expected_instance_id and player_sid_to_fold in self.player_action_timers:
                     del self.player_action_timers[player_sid_to_fold]


    def _start_player_action_timer(self, player_sid):
        print(f"[德州撲克房間 {self.room_id}] _start_player_action_timer CALLED for {player_sid}.")
        self._cancel_player_action_timer(player_sid)

        if player_sid in self.players and \
           self.players[player_sid].get('is_active_in_round') and \
           not self.players[player_sid].get('is_all_in', False) and \
           self.is_game_in_progress:

            player_name = self.players[player_sid]['name']
            current_instance_id = self.player_timer_instance_ids.get(player_sid, 0) + 1
            self.player_timer_instance_ids[player_sid] = current_instance_id

            print(f"[德州撲克房間 {self.room_id}] 為玩家 {player_name} ({player_sid}) 啟動計時器 (ID: {current_instance_id})，時長 {self.game_state['timeout_seconds']} 秒。")

            timer_thread = eventlet.spawn_after(
                self.game_state['timeout_seconds'],
                lambda s=player_sid, inst_id=current_instance_id: self._timer_countdown(s, inst_id)
            )
            self.player_action_timers[player_sid] = timer_thread
            timer_thread = eventlet.spawn_after(
                self.game_state['timeout_seconds']-3,
                lambda s=player_sid, inst_id=current_instance_id: self._auto_fold_player(s, inst_id)
            )
            self.player_action_timers[player_sid] = timer_thread
            print(f"[德州撲克房間 {self.room_id}] 計時器 greenthread 已為 {player_sid} (ID: {current_instance_id}) 添加。當前計時器字典: {list(self.player_action_timers.keys())}")
        else:
            print(f"[德州撲克房間 {self.room_id}] 未為玩家 {player_sid} 啟動計時器 (原因：非活躍 / 已All-in / 遊戲未進行 / 玩家不存在)。")

    def _cancel_player_action_timer(self, player_sid):
        print(f"[德州撲克房間 {self.room_id}] _cancel_player_action_timer CALLED for {player_sid}. 當前計時器 greenthreads: {list(self.player_action_timers.keys())}")
        timer_to_cancel = self.player_action_timers.pop(player_sid, None)
        if timer_to_cancel:
            print(f"[德州撲克房間 {self.room_id}] 從字典中 Pop 計時器 greenthread for {player_sid}: {timer_to_cancel}")
            try:
                timer_to_cancel.kill()
                print(f"[德州撲克房間 {self.room_id}] 成功 Kill 玩家 {player_sid} 的計時器線程。")
            except Exception as e:
                print(f"[德州撲克房間 {self.room_id}] Kill 玩家 {player_sid} 計時器時發生錯誤: {e}")
        else:
            print(f"[德州撲克房間 {self.room_id}] 嘗試取消玩家 {player_sid} 的計時器，但在字典中未找到 greenthread。")
        print(f"[德州撲克房間 {self.room_id}] 取消操作後，計時器 greenthreads 字典: {list(self.player_action_timers.keys())}")


    def _cleanup_all_timers(self):
        print(f"[德州撲克房間 {self.room_id}] _cleanup_all_timers CALLED。當前計時器 greenthreads 字典內容: {list(self.player_action_timers.keys())}")
        for sid_to_clean in list(self.player_action_timers.keys()):
            print(f"[德州撲克房間 {self.room_id}] _cleanup_all_timers: 正在嘗試取消玩家 {sid_to_clean} 的計時器。")
            self._cancel_player_action_timer(sid_to_clean)
        print(f"[德州撲克房間 {self.room_id}] _cleanup_all_timers 完成。最終計時器 greenthreads 字典: {list(self.player_action_timers.keys())}")

    def get_game_type(self):
        return "texas_holdem"

    def add_player(self, player_sid, player_info):
        player_name_from_info = player_info.get('name')
        player_name_to_set = player_name_from_info if player_name_from_info and player_name_from_info.strip() else f"玩家_{player_sid[:4]}"
        if player_sid not in self.players:
            self.players[player_sid] = {
                'name': player_name_to_set, 'chips': self.options.get('buy_in', 1000),
                'hand': [], 'current_bet': 0, 'bet_in_current_street': 0,
                'is_active_in_round': False, 'has_acted_this_street': False, 
                'is_all_in': False, 'disconnected': False, # Add this
            }
            print(f"[德州撲克房間 {self.room_id}] 玩家 {player_name_to_set} ({player_sid}) 新加入。")
            self.broadcast_state(message=f"玩家 {player_name_to_set} 加入了牌桌。")
            return True
        else:
            # Existing player logic
            original_name = self.players[player_sid].get('name')
            self.players[player_sid]['name'] = player_name_to_set
            if self.players[player_sid].get('disconnected'):
                self.players[player_sid]['disconnected'] = False
                print(f"[德州撲克房間 {self.room_id}] 玩家 {player_name_to_set} ({player_sid}) 重新連線。")
                # Player is back, but if a hand was in progress and they folded, they stay folded for that hand.
                self.broadcast_state(message=f"玩家 {player_name_to_set} ({original_name}) 更新名稱為 {player_name_to_set} 並重新連線。")
            elif original_name != player_name_to_set :
                print(f"[德州撲克房間 {self.room_id}] 玩家 {original_name} ({player_sid}) 更新名稱為 {player_name_to_set}。")
                self.broadcast_state(message=f"玩家 {original_name} 更新名稱為 {player_name_to_set}。")
            else:
                print(f"[德州撲克房間 {self.room_id}] 玩家 {self.players[player_sid]['name']} ({player_sid}) 已在房間中。")
                # Potentially broadcast state if it was just a ping or state request
                self.broadcast_state(message=f"玩家 {self.players[player_sid]['name']} 已在牌桌。")
            return True

    def _post_blind(self, player_sid, blind_amount, is_small_blind=False):
        player = self.players[player_sid]
        actual_blind_posted = min(player['chips'], blind_amount)
        player['chips'] -= actual_blind_posted
        player['current_bet'] += actual_blind_posted
        player['bet_in_current_street'] += actual_blind_posted
        self.game_state['pot'] += actual_blind_posted
        if player['chips'] == 0: player['is_all_in'] = True
        print(f"[德州撲克房間 {self.room_id}] 玩家 {player['name']} 下盲注 {actual_blind_posted}{'並 All-in' if player['is_all_in'] else ''}。")
        if not is_small_blind:
            self.game_state['current_street_bet_to_match'] = actual_blind_posted
            if not (len(self.game_state.get('round_active_players_sids_in_order', [])) == 2 and is_small_blind):
                 self.game_state['last_raiser_sid'] = player_sid
                 self.game_state['player_who_opened_betting_this_street'] = player_sid

    def start_game(self, triggering_player_sid=None):
        if self.host_sid and triggering_player_sid != self.host_sid:
            self.send_error_to_player(triggering_player_sid, "只有房主才能開始遊戲。")
            print(f"[德州撲克房間 {self.room_id}] 玩家 {triggering_player_sid} 嘗試開始遊戲，但不是房主 ({self.host_sid})。")
            return False

        if self.is_game_in_progress:
            if triggering_player_sid: self.send_error_to_player(triggering_player_sid, "遊戲已在進行中。")
            return False
        eligible_player_sids = [sid for sid, data in self.players.items() if data.get('chips', 0) > 0 and not data.get('disconnected', False)] # Modified line
        num_eligible_players = len(eligible_player_sids)
        if num_eligible_players < self.options.get('min_players', 2):
            msg = f"玩家不足。至少需要 {self.options.get('min_players', 2)} 位有籌碼的玩家才能開始。"
            if triggering_player_sid: self.send_error_to_player(triggering_player_sid, msg)
            else: self.broadcast_state(message=msg)
            return False

        print(f"[德州撲克房間 {self.room_id}] 準備開始新牌局。符合資格的玩家 ({num_eligible_players}): {eligible_player_sids}")
        self.is_game_in_progress = True
        self._cleanup_all_timers()
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
        if num_eligible_players == 2:
            sb_sid = dealer_sid
            bb_sid = ordered_sids_from_dealer_plus_1[0]
            self._post_blind(sb_sid, self.game_state['small_blind'], is_small_blind=True)
            self._post_blind(bb_sid, self.game_state['big_blind'])
            utg_sid = sb_sid
            current_action_order_for_preflop = [sb_sid, bb_sid]
        else:
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

        if utg_sid:
            self._start_player_action_timer(utg_sid)

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

        self._cancel_player_action_timer(player_sid)
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
        print(f"[德州撲克房間 {self.room_id}] 玩家 {player_name} ({player_sid}) 正在被移除 (明確離開房間)。")

        self._cancel_player_action_timer(player_sid) 

        was_active_in_round = player_data_copy.get('is_active_in_round', False)
        was_current_turn = (self.game_state.get('current_turn_sid') == player_sid)
        
        if player_sid in self.game_state.get('round_active_players_sids_in_order', []):
            try:
                self.game_state['round_active_players_sids_in_order'].remove(player_sid)
            except ValueError:
                print(f"[德州撲克房間 {self.room_id}] 警告: 嘗試從行動順序中移除 {player_sid} 失敗，可能已不在其中。")
        
        del self.players[player_sid] 

        message_for_broadcast = f"玩家 {player_name} 離開了牌桌。"

        if self.is_game_in_progress and was_active_in_round:
            print(f"[德州撲克房間 {self.room_id}] 玩家 {player_name} 在遊戲中離開，其行動已被處理或無需處理，因玩家已移除。")
            message_for_broadcast = f"玩家 {player_name} 已離開並自動棄牌。"
            
            active_players_still_in_round = self._get_active_players_in_round_now() 
            print(f"[德州撲克房間 {self.room_id}] {player_name} 離開後，剩餘活躍玩家: {len(active_players_still_in_round)}")

            if len(active_players_still_in_round) == 1:
                winner_sid = active_players_still_in_round[0]
                self._award_pot_to_winner(winner_sid, reason=f"因 {player_name} 離開而成為最後的玩家。")
                return True 
            elif len(active_players_still_in_round) < 1:
                print(f"[德州撲克房間 {self.room_id}] 在 {player_name} 離開後沒有剩餘活躍玩家。結束牌局。")
                self.game_state['pot'] = 0
                self.end_game({'message': "牌局因所有剩餘玩家離開/棄牌而結束。", 'pot': 0})
                return True 
            else:
                if was_current_turn:
                    print(f"[德州撲克房間 {self.room_id}] 輪到 {player_name} 行動，但他已離開。推進到下一位玩家。")
                    self._advance_to_next_player_or_phase(action_message_for_broadcast=message_for_broadcast)
                else:
                    print(f"[德州撲克房間 {self.room_id}] {player_name} 已離開，但非其行動輪。遊戲繼續。")
                    self.broadcast_state(message=message_for_broadcast)
        else:
            print(f"[德州撲克房間 {self.room_id}] 玩家 {player_name} 已離開。遊戲未進行或玩家非活躍。")
            self.broadcast_state(message=message_for_broadcast)

        if self.get_player_count() == 0 and not self.is_game_in_progress:
            print(f"[德州撲克房間 {self.room_id}] 房間已空且遊戲未進行。發出 ROOM_EMPTY 信號。")
            return "ROOM_EMPTY"
        return True
    def disconnect_player(self, player_sid):
        if player_sid not in self.players:
            print(f"[德州撲克房間 {self.room_id}] 嘗試標記斷線的不存在玩家 {player_sid}。")
            return False

        player_data = self.players[player_sid]
        player_name = player_data.get('name', f"未知玩家({player_sid[:4]})")

        # self._cancel_player_action_timer(player_sid)
        player_data['disconnected'] = True 

        message_for_broadcast = f"玩家 {player_name} 已斷線。"
        self.broadcast_state(message=message_for_broadcast)
        '''
        if self.is_game_in_progress and was_active_in_round:
            print(f"[德州撲克房間 {self.room_id}] 玩家 {player_name} 在遊戲中斷線，視為棄牌。")
            player_data['is_active_in_round'] = False 
            player_data['has_acted_this_street'] = True 

            message_for_broadcast = f"玩家 {player_name} 已斷線並自動棄牌。"
            active_players_still_in_round = self._get_active_players_in_round_now()
            print(f"[德州撲克房間 {self.room_id}] {player_name} 斷線棄牌後，剩餘活躍玩家: {len(active_players_still_in_round)}")

            if len(active_players_still_in_round) == 1:
                winner_sid = active_players_still_in_round[0]
                self._award_pot_to_winner(winner_sid, reason=f"因 {player_name} 斷線而成為最後的玩家。")
                return True 
            elif len(active_players_still_in_round) < 1:
                print(f"[德州撲克房間 {self.room_id}] 在 {player_name} 斷線後沒有剩餘活躍玩家。結束牌局。")
                self.game_state['pot'] = 0 
                self.end_game({'message': "牌局因所有剩餘玩家棄牌/斷線而結束。", 'pot': 0})
                return True 
            else:
                if was_current_turn:
                    print(f"[德州撲克房間 {self.room_id}] 輪到 {player_name} 行動，但他已斷線。推進到下一位玩家。")
                    self._advance_to_next_player_or_phase(action_message_for_broadcast=message_for_broadcast)
                else:
                    print(f"[德州撲克房間 {self.room_id}] {player_name} 已斷線，但非其行動輪。遊戲繼續。")
                    self.broadcast_state(message=message_for_broadcast)
        else:
            print(f"[德州撲克房間 {self.room_id}] 玩家 {player_name} 已斷線。遊戲未進行或玩家非活躍於本局。")
            self.broadcast_state(message=message_for_broadcast)
        '''
        
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
            self._cleanup_all_timers()
            self.end_game(results)
            self.game_state['current_turn_sid'] = None
        else:
            print(f"[德州撲克房間 {self.room_id}] 錯誤：在分配底池時找不到贏家 SID {winner_sid}。")
            self._cleanup_all_timers()
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
            if not player_check_acted.get('is_all_in', False) and not player_check_acted.get('has_acted_this_street', False):
                all_acted_this_street = False
                print(f"[_is_betting_round_over] 玩家 {player_check_acted['name']} 尚未行動。回合繼續。")
                break
        if not all_acted_this_street: return False
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
            if self.game_state.get('player_who_opened_betting_this_street') is None:
                print(f"[_is_betting_round_over] 所有人都已行動且都過牌。回合結束。")
                return True
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
        active_sids_for_new_street = self._get_active_players_in_round_now()
        if not active_sids_for_new_street:
            self._handle_showdown_or_win_by_fold(reason_suffix="新街道開始時無活躍玩家。")
            return False

        dealer_sid = self.game_state.get('dealer_sid_for_display')
        original_order = self.game_state.get('round_active_players_sids_in_order', [])

        dealer_idx_in_original_order = -1
        if dealer_sid and dealer_sid in original_order:
            try:
                dealer_idx_in_original_order = original_order.index(dealer_sid)
            except ValueError:
                pass

        num_can_bet_new_street = 0
        for sid_check in active_sids_for_new_street:
            if sid_check in self.players and not self.players[sid_check].get('is_all_in', False) and self.players[sid_check].get('chips', 0) > 0:
                num_can_bet_new_street +=1

        new_street_action_order_temp = []
        if dealer_idx_in_original_order != -1 and original_order: # 確保 original_order 不是空的
            for i in range(1, len(original_order) + 1):
                player_to_check_sid = original_order[(dealer_idx_in_original_order + i) % len(original_order)]
                if player_to_check_sid in active_sids_for_new_street:
                    new_street_action_order_temp.append(player_to_check_sid)
        else:
            print(f"[德州撲克房間 {self.room_id}] 警告: 未找到按鈕位在原始順序中，或原始順序為空。新街道行動順序可能不準確。")
            new_street_action_order_temp = list(active_sids_for_new_street)


        for sid_potential_first in new_street_action_order_temp:
            if num_can_bet_new_street > 0 and self.players[sid_potential_first].get('is_all_in', False):
                continue
            first_to_act_sid_new_street = sid_potential_first
            break

        if not first_to_act_sid_new_street and new_street_action_order_temp:
            first_to_act_sid_new_street = new_street_action_order_temp[0]

        self.game_state['current_turn_sid'] = first_to_act_sid_new_street
        self.game_state['round_active_players_sids_in_order'] = new_street_action_order_temp

        for sid_reset_street in self.players:
            if self.players[sid_reset_street].get('is_active_in_round'):
                self.players[sid_reset_street]['bet_in_current_street'] = 0
                self.players[sid_reset_street]['has_acted_this_street'] = False

        if first_to_act_sid_new_street:
            self._start_player_action_timer(first_to_act_sid_new_street)

        print(f"[德州撲克房間 {self.room_id}] 新街道 {next_phase} 開始。輪到: {self.players[first_to_act_sid_new_street]['name'] if first_to_act_sid_new_street and first_to_act_sid_new_street in self.players else 'N/A'}")
        return True

    def _auto_deal_remaining_cards_and_showdown(self, reason=""):
        print(f"[德州撲克房間 {self.room_id}] 所有可行動玩家已 All-in。自動發牌並攤牌。{reason}")
        current_phase = self.game_state.get('game_phase')
        cards_dealt_message = "自動發完剩餘公共牌: "
        original_community_len = len(self.game_state['community_cards'])
        if current_phase == 'pre-flop':
            self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 3))
            self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 1))
            self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 1))
        elif current_phase == 'flop':
            self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 1))
            self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 1))
        elif current_phase == 'turn':
            self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 1))
        newly_dealt_cards = self.game_state['community_cards'][original_community_len:]
        if newly_dealt_cards:
            cards_dealt_message += " ".join([f"{c['rank']}{c['suit']}" for c in newly_dealt_cards])
        else:
            cards_dealt_message = "無需再發公共牌。"
        print(f"[德州撲克房間 {self.room_id}] {cards_dealt_message}")
        self.game_state['game_phase'] = 'showdown'
        self.broadcast_state(message=f"{cards_dealt_message} 準備攤牌。")
        self._cleanup_all_timers()
        self._handle_showdown_or_win_by_fold(reason_suffix=f"所有玩家 All-in 後自動攤牌。{reason}")

    def _advance_to_next_player_or_phase(self, action_message_for_broadcast=None):
        print(f"[德州撲克房間 {self.room_id}] _advance_to_next_player_or_phase CALLED. 附帶消息: {action_message_for_broadcast}")
        final_broadcast_message = action_message_for_broadcast or ""

        active_players_in_current_betting_order = self._get_active_players_in_order()

        if len(active_players_in_current_betting_order) <= 1 and self.is_game_in_progress:
            print(f"[德州撲克房間 {self.room_id}] 只剩 {len(active_players_in_current_betting_order)} 位活躍玩家，進入攤牌/獲勝邏輯。")
            self._handle_showdown_or_win_by_fold(reason_suffix="只剩一位或零位活躍玩家。")
            if final_broadcast_message and not self.is_game_in_progress:
                self.broadcast_state(message=final_broadcast_message.strip())
            return

        num_active_not_all_in = 0
        for sid_check_all_in in active_players_in_current_betting_order:
            if not self.players[sid_check_all_in].get('is_all_in', False) and self.players[sid_check_all_in].get('chips',0) > 0:
                num_active_not_all_in +=1

        if num_active_not_all_in == 0 and len(active_players_in_current_betting_order) > 1:
             if self.game_state.get('game_phase') != 'showdown':
                self._auto_deal_remaining_cards_and_showdown(reason="所有剩餘玩家均已 All-in。")
                return

        if self._is_betting_round_over():
            print(f"[德州撲克房間 {self.room_id}] 當前下注回合結束。準備清理計時器並進入下一街道。")
            self._cleanup_all_timers()

            proceeded_to_new_street = self._proceed_to_next_street()
            if not proceeded_to_new_street and not self.is_game_in_progress:
                if final_broadcast_message: self.broadcast_state(message=final_broadcast_message.strip())
                return

            if self.is_game_in_progress:
                new_turn_sid_after_street = self.game_state.get('current_turn_sid')
                current_message = final_broadcast_message
                if new_turn_sid_after_street and new_turn_sid_after_street in self.players:
                    current_message += f" 輪到玩家 {self.players[new_turn_sid_after_street]['name']} 行動。"
                elif not new_turn_sid_after_street and self.game_state.get('game_phase') != 'showdown':
                    print(f"[德州撲克房間 {self.room_id}] 進入新街道但未找到行動者，可能所有人都已 All-in。")
                    self._auto_deal_remaining_cards_and_showdown(reason="進入新街道後無人可行動。")
                    return

                if self.is_game_in_progress and self.game_state.get('current_turn_sid'):
                    self.broadcast_state(message=current_message.strip())
                elif not self.is_game_in_progress and current_message:
                    self.broadcast_state(message=current_message.strip())
        else:
            current_acting_player_sid = self.game_state.get('current_turn_sid')
            next_player_sid = None
            current_betting_order = self.game_state.get('round_active_players_sids_in_order', [])
            if not current_betting_order:
                self._handle_showdown_or_win_by_fold(reason_suffix="行動順序列表為空。")
                return
            last_acted_player_idx = -1
            if current_acting_player_sid and current_acting_player_sid in current_betting_order:
                try:
                    last_acted_player_idx = current_betting_order.index(current_acting_player_sid)
                except ValueError:
                    print(f"[德州撲克房間 {self.room_id}] 警告：剛行動的玩家 {current_acting_player_sid} 不在當前行動順序中。")

            found_next = False
            for i in range(1, len(current_betting_order) + 1):
                next_candidate_idx = (last_acted_player_idx + i) % len(current_betting_order)
                candidate_sid = current_betting_order[next_candidate_idx]
                if candidate_sid not in self.players or not self.players[candidate_sid].get('is_active_in_round'):
                    continue
                player_candidate = self.players[candidate_sid]
                if player_candidate.get('is_all_in', False):
                    continue
                if not player_candidate.get('has_acted_this_street', False):
                    next_player_sid = candidate_sid
                    found_next = True
                    break

            if found_next and next_player_sid:
                self.game_state['current_turn_sid'] = next_player_sid
                self._start_player_action_timer(next_player_sid)
                current_message = final_broadcast_message + f" 輪到玩家 {self.players[next_player_sid]['name']} 行動。"
                self.broadcast_state(message=current_message.strip())
            else:
                print(f"[德州撲克房間 {self.room_id}] 警告：無法找到下一個行動者，但下注回合被認為未結束。檢查 _is_betting_round_over 邏輯。")
                if self.is_game_in_progress:
                    if self._is_betting_round_over():
                         self._advance_to_next_player_or_phase(action_message_for_broadcast=final_broadcast_message)
                    else:
                         self._auto_deal_remaining_cards_and_showdown(reason="無法確定下一行動者，強制攤牌。")

    def _handle_showdown_or_win_by_fold(self, reason_suffix=""):
        if not self.is_game_in_progress:
            print(f"[德州撲克房間 {self.room_id}] 嘗試攤牌，但遊戲已結束。")
            return
        print(f"[德州撲克房間 {self.room_id}] 進入攤牌或單人獲勝處理。 {reason_suffix}")
        self._cleanup_all_timers()
        current_phase = self.game_state.get('game_phase')
        if current_phase != 'showdown':
            while len(self.game_state['community_cards']) < 5 and current_phase not in ['showdown', None]:
                if current_phase == 'pre-flop' and len(self.game_state['community_cards']) == 0:
                    self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 3))
                    current_phase = 'flop'
                    print(f"[德州撲克房間 {self.room_id}] 自動發 Flop: {[(c['rank'], c['suit']) for c in self.game_state['community_cards'][-3:]]}")
                elif current_phase == 'flop' and len(self.game_state['community_cards']) == 3:
                    self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 1))
                    current_phase = 'turn'
                    print(f"[德州撲克房間 {self.room_id}] 自動發 Turn: {[(c['rank'], c['suit']) for c in self.game_state['community_cards'][-1:]]}")
                elif current_phase == 'turn' and len(self.game_state['community_cards']) == 4:
                    self.game_state['community_cards'].extend(deal_cards(self.game_state['deck'], 1))
                    current_phase = 'river'
                    print(f"[德州撲克房間 {self.room_id}] 自動發 River: {[(c['rank'], c['suit']) for c in self.game_state['community_cards'][-1:]]}")
                else: break
            self.game_state['game_phase'] = 'showdown'
        active_players_final = self._get_active_players_in_round_now()
        if len(active_players_final) == 1:
            self._award_pot_to_winner(active_players_final[0], reason=f"作為最後活躍玩家獲勝。{reason_suffix}")
        elif len(active_players_final) > 1:
            print(f"[德州撲克房間 {self.room_id}] 進行攤牌，有 {len(active_players_final)} 位玩家。")
            winner_evaluations = []
            best_eval_value = -1
            best_tie_breaker = []
            showdown_participants_evals = []
            for p_sid in active_players_final:
                player_data = self.players[p_sid]
                player_hole_cards = player_data.get('hand', [])
                community = self.game_state.get('community_cards', [])
                eval_result = evaluate_hand(player_hole_cards, community)
                showdown_participants_evals.append({
                    'sid': p_sid, 'name': player_data['name'],
                    'hole_cards': player_hole_cards,
                    'best_5_card_hand': eval_result.get('hand_cards', []),
                    'hand_name': eval_result.get('name', '未知牌型'),
                    'hand_value': eval_result.get('value', -1),
                    'tie_breaker_ranks': eval_result.get('tie_breaker_ranks', [])
                })
                print(f"[德州撲克房間 {self.room_id}] 玩家 {player_data['name']} 底牌: {player_hole_cards}, 公共牌: {community}, 評估: {eval_result['name']}, 牌值: {eval_result['value']}, 最佳5張: {eval_result.get('hand_cards')}, TieBreak: {eval_result.get('tie_breaker_ranks')}")
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
                    if i < remainder: win_this_share += 1
                    if actual_winner_sid in self.players:
                        self.players[actual_winner_sid]['chips'] += win_this_share
                    winners_for_results.append({
                        'sid': actual_winner_sid, 'name': winner_data_entry['name'],
                        'amount_won': win_this_share, 'hole_cards': winner_data_entry['hole_cards'],
                        'best_hand_description': winning_hand_name,
                        'best_5_card_hand': best_5_cards_for_winner,
                        'reason': f"在攤牌中以 {winning_hand_name} ({''.join([f'{c["rank"]}{c["suit"]}' for c in best_5_cards_for_winner]) if best_5_cards_for_winner else 'N/A'}) 獲勝。{reason_suffix}"
                    })
                self.game_state['pot'] = 0
                results_payload = {
                    'winners': winners_for_results, 'pot': 0,
                    'community_cards': self.game_state.get('community_cards', []),
                    'all_hands_at_showdown': showdown_participants_evals
                }
                self.end_game(results_payload)
                self.game_state['current_turn_sid'] = None
            else:
                 self._award_pot_to_winner(active_players_final[0], reason=f"在攤牌中獲勝 (佔位邏輯 - 無法評估贏家)。{reason_suffix}")
        else:
            print(f"[德州撲克房間 {self.room_id}] 沒有活躍玩家參與攤牌。{reason_suffix}")
            self.game_state['pot'] = 0
            self.end_game({'message': f"牌局因沒有活躍玩家而結束。{reason_suffix}"})

    def end_game(self, results):
        print(f"[德州撲克房間 {self.room_id}] 遊戲回合結束。清理計時器。")
        self._cleanup_all_timers()
        super().end_game(results)


    def get_state_for_player(self, player_sid):
        # print(f"--- [get_state_for_player] 為玩家 {player_sid} 準備狀態 ---")
        # print(f"    當前 self.players 鍵: {list(self.players.keys())}")
        # print(f"    遊戲進行中: {self.is_game_in_progress}, 遊戲階段: {self.game_state.get('game_phase')}")
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
        for sid_loop, p_data in self.players.items():
            player_name_display = p_data.get('name')
            if not player_name_display or not player_name_display.strip():
                player_name_display = f"玩家_{sid_loop[:4]}"
            player_view = {
                'sid': sid_loop, 'name': player_name_display,
                'chips': p_data.get('chips', 0), 'current_bet': p_data.get('current_bet', 0),
                'bet_in_current_street': p_data.get('bet_in_current_street', 0),
                'is_active_in_round': p_data.get('is_active_in_round', False),
                'is_all_in': p_data.get('is_all_in', False),
                'has_acted_this_street': p_data.get('has_acted_this_street', False),
                'disconnected': p_data.get('disconnected', False), # Add this line
                'hand': []
            }
            if sid_loop == player_sid and self.is_game_in_progress:
                player_view['hand'] = p_data.get('hand', [])
            elif self.game_state.get('game_phase') == 'showdown' and p_data.get('is_active_in_round', False):
                player_view['hand'] = p_data.get('hand', [])
            public_players_data.append(player_view)
        state_for_player = {
            'room_id': self.room_id, 'game_type': self.get_game_type(),
            'is_game_in_progress': self.is_game_in_progress,
            'players': public_players_data,
            'community_cards': self.game_state.get('community_cards', []),
            'pot': self.game_state.get('pot', 0),
            'current_turn_sid': self.game_state.get('current_turn_sid'),
            'current_street_bet_to_match': self.game_state.get('current_street_bet_to_match',0),
            'min_next_raise_increment': self.game_state.get('min_next_raise_increment', self.game_state['big_blind']),
            'game_phase': self.game_state.get('game_phase'),
            'dealer_sid_for_display': self.game_state.get('dealer_sid_for_display'),
            'round_active_players_sids_in_order_DEBUG': self.game_state.get('round_active_players_sids_in_order', []),
            'options': self.options,
            'player_id': player_sid,
            'host_id': self.host_sid,
        }
        return state_for_player