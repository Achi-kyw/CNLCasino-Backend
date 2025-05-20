# games/black_jack/logic.py
import random
from games.base_game import BaseGame
from .utils import create_deck, shuffle_deck, deal_cards, calculate_hand_value, is_blackjack, is_bust, compare_hands

class BlackJackGame(BaseGame):
    def __init__(self, room_id, players_sids, socketio_instance, options=None):
        super().__init__(room_id, players_sids, socketio_instance, options)
        # --- 遊戲狀態初始化 ---
        self.game_state['deck'] = []
        self.game_state['dealer_hand'] = []
        self.game_state['dealer_hand_value'] = 0
        self.game_state['dealer_has_blackjack'] = False
        self.game_state['current_turn_sid'] = None
        self.game_state['game_phase'] = None  # 'dealing', 'player_turns', 'dealer_turn', 'settlement'
        self.game_state['min_bet'] = self.options.get('min_bet', 10)
        self.game_state['max_bet'] = self.options.get('max_bet', 100)
        self.game_state['round_active_players_sids_in_order'] = []

        # 初始化玩家數據
        temp_initial_players = {}
        if players_sids:
            for sid_init in players_sids:
                temp_initial_players[sid_init] = {
                    'name': f"玩家_{sid_init[:4]}",  # 預設名稱
                    'chips': self.options.get('buy_in', 1000),
                    'hand': [],
                    'hand_value': 0,
                    'bet': 0,
                    'is_active_in_round': False,
                    'has_acted_this_round': False,
                    'is_busted': False,
                    'has_blackjack': False,
                    'has_doubled_down': False,
                    'has_insurance': False,
                    'insurance_bet': 0
                }
        self.players = temp_initial_players  # 設置初始玩家數據
        print(f"[21點房間 {self.room_id}] 遊戲實例已創建。初始玩家: {list(self.players.keys())}, 選項: {self.options}")

    def get_game_type(self):
        return "black_jack"

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
                'hand_value': 0,
                'bet': 0,
                'is_active_in_round': False,
                'has_acted_this_round': False,
                'is_busted': False,
                'has_blackjack': False,
                'has_doubled_down': False,
                'has_insurance': False,
                'insurance_bet': 0
            }
            print(f"[21點房間 {self.room_id}] 玩家 {player_name_to_set} ({player_sid}) 新加入。")
            self.broadcast_state(message=f"玩家 {player_name_to_set} 加入了牌桌。")
            return True
        else:
            # 玩家已存在，可能只是更新名稱
            if self.players[player_sid].get('name') != player_name_to_set:
                old_name = self.players[player_sid].get('name')
                self.players[player_sid]['name'] = player_name_to_set
                print(f"[21點房間 {self.room_id}] 玩家 {old_name} ({player_sid}) 更新名稱為 {player_name_to_set}。")
            else:
                print(f"[21點房間 {self.room_id}] 玩家 {self.players[player_sid]['name']} ({player_sid}) 已在房間中。")
            
            self.broadcast_state(message=f"玩家 {self.players[player_sid]['name']} 已在牌桌。")
            return True

    def remove_player(self, player_sid):
        """將玩家從遊戲中移除"""
        if player_sid in self.players:
            player_name = self.players[player_sid]['name']
            del self.players[player_sid]
            print(f"[21點房間 {self.room_id}] 玩家 {player_name} 離開。")
            # 如果遊戲正在進行，需要處理該玩家的退出邏輯
            if self.is_game_in_progress:
                # 如果輪到離開的玩家行動，則移到下一位玩家
                if self.game_state['current_turn_sid'] == player_sid:
                    self._advance_to_next_player_or_phase()
            
            self.broadcast_state(message=f"玩家 {player_name} 離開了牌桌。")
            if self.get_player_count() == 0 and not self.is_game_in_progress:  # 如果房間沒人了且遊戲沒在進行
                return "ROOM_EMPTY"  # 特殊返回值，讓 app.py 知道可以清理房間
            return True
        return False

    def place_bet(self, player_sid, bet_amount):
        """玩家下注"""
        if not self.is_game_in_progress:
            self.send_error_to_player(player_sid, "遊戲尚未開始，無法下注。")
            return False
        
        if self.game_state['game_phase'] != 'betting':
            self.send_error_to_player(player_sid, "目前非下注階段。")
            return False
        
        player = self.players.get(player_sid)
        if not player:
            self.send_error_to_player(player_sid, "玩家不存在。")
            return False
        
        if player['bet'] > 0:
            self.send_error_to_player(player_sid, "您已經下注。")
            return False
        
        if bet_amount < self.game_state['min_bet']:
            self.send_error_to_player(player_sid, f"下注金額不得低於最低限額 {self.game_state['min_bet']}。")
            return False
        
        if bet_amount > self.game_state['max_bet']:
            self.send_error_to_player(player_sid, f"下注金額不得高於最高限額 {self.game_state['max_bet']}。")
            return False
        
        if bet_amount > player['chips']:
            self.send_error_to_player(player_sid, "您的籌碼不足。")
            return False
        
        player['bet'] = bet_amount
        player['chips'] -= bet_amount
        player['is_active_in_round'] = True
        
        print(f"[21點房間 {self.room_id}] 玩家 {player['name']} 下注 {bet_amount}。")
        self.broadcast_state(message=f"玩家 {player['name']} 下注 {bet_amount}。")
        
        # 檢查是否所有玩家都已下注
        all_players_bet = all(p['bet'] > 0 or not p['is_active_in_round'] for p in self.players.values())
        if all_players_bet:
            self._deal_initial_cards()
        
        return True

    def start_game(self, triggering_player_sid=None):
        """開始新一局遊戲"""
        if self.is_game_in_progress:
            if triggering_player_sid:
                self.send_error_to_player(triggering_player_sid, "遊戲已在進行中。")
            return False

        eligible_player_sids = [sid for sid, data in self.players.items() if data.get('chips', 0) > 0]
        num_eligible_players = len(eligible_player_sids)

        if num_eligible_players < self.options.get('min_players', 1):
            msg = f"玩家不足。至少需要 {self.options.get('min_players', 1)} 位有籌碼的玩家才能開始。"
            if triggering_player_sid:
                self.send_error_to_player(triggering_player_sid, msg)
            else:
                self.broadcast_state(message=msg)
            return False

        print(f"[21點房間 {self.room_id}] 準備開始新牌局。符合資格的玩家 ({num_eligible_players}): {eligible_player_sids}")
        self.is_game_in_progress = True
        self.game_state['game_phase'] = 'betting'
        self.game_state['deck'] = shuffle_deck(create_deck())
        self.game_state['dealer_hand'] = []
        self.game_state['dealer_hand_value'] = 0
        self.game_state['dealer_has_blackjack'] = False

        # 重設所有玩家的狀態
        for sid in self.players:
            self.players[sid]['hand'] = []
            self.players[sid]['hand_value'] = 0
            self.players[sid]['bet'] = 0
            self.players[sid]['is_active_in_round'] = sid in eligible_player_sids
            self.players[sid]['has_acted_this_round'] = False
            self.players[sid]['is_busted'] = False
            self.players[sid]['has_blackjack'] = False
            self.players[sid]['has_doubled_down'] = False
            self.players[sid]['has_insurance'] = False
            self.players[sid]['insurance_bet'] = 0
        
        self.game_state['round_active_players_sids_in_order'] = eligible_player_sids.copy()
        
        print(f"[21點房間 {self.room_id}] 新牌局已開始。等待玩家下注。")
        self.broadcast_state(message="新牌局開始！請各位玩家下注。")
        return True

    def _deal_initial_cards(self):
        """發放初始牌組"""
        if self.game_state['game_phase'] != 'betting':
            return False
        
        # 發牌給玩家，每人兩張牌
        for sid in self.game_state['round_active_players_sids_in_order']:
            if self.players[sid]['is_active_in_round']:
                self.players[sid]['hand'] = deal_cards(self.game_state['deck'], 2)
                self.players[sid]['hand_value'] = calculate_hand_value(self.players[sid]['hand'])
                self.players[sid]['has_blackjack'] = is_blackjack(self.players[sid]['hand'])
        
        # 發牌給莊家，兩張牌（一張明牌，一張暗牌）
        self.game_state['dealer_hand'] = deal_cards(self.game_state['deck'], 2)
        self.game_state['dealer_hand_value'] = calculate_hand_value(self.game_state['dealer_hand'])
        self.game_state['dealer_has_blackjack'] = is_blackjack(self.game_state['dealer_hand'])
        
        # 檢查莊家明牌是否為Ace，提供保險選項
        dealer_up_card = self.game_state['dealer_hand'][0]
        if dealer_up_card['rank'] == 'A':
            self.game_state['game_phase'] = 'insurance'
            print(f"[21點房間 {self.room_id}] 莊家明牌為A，進入保險階段。")
            self.broadcast_state(message="莊家明牌為A，玩家可以選擇是否購買保險。")
        else:
            self._check_dealer_blackjack()
        
        return True

    def _check_dealer_blackjack(self):
        """檢查莊家是否有21點"""
        if self.game_state['dealer_has_blackjack']:
            print(f"[21點房間 {self.room_id}] 莊家有21點。")
            self.broadcast_state(message="莊家有21點！")
            self._settle_round()
        else:
            # 進入玩家回合階段
            self.game_state['game_phase'] = 'player_turns'
            # 設置第一個行動的玩家
            if self.game_state['round_active_players_sids_in_order']:
                self.game_state['current_turn_sid'] = self.game_state['round_active_players_sids_in_order'][0]
                player_name = self.players[self.game_state['current_turn_sid']]['name']
                print(f"[21點房間 {self.room_id}] 輪到玩家 {player_name} 行動。")
                self.broadcast_state(message=f"輪到玩家 {player_name} 行動。")
            else:
                # 沒有活躍玩家，直接進入莊家回合
                self._dealer_turn()

    def take_insurance(self, player_sid, take=False):
        """玩家決定是否購買保險"""
        if not self.is_game_in_progress or self.game_state['game_phase'] != 'insurance':
            self.send_error_to_player(player_sid, "目前非保險階段。")
            return False
        
        player = self.players.get(player_sid)
        if not player or not player['is_active_in_round']:
            self.send_error_to_player(player_sid, "您不在本局遊戲中。")
            return False
        
        if player['has_insurance'] is not None:  # 已經做出選擇
            self.send_error_to_player(player_sid, "您已經做出保險選擇。")
            return False
        
        if take:
            insurance_amount = player['bet'] / 2
            if insurance_amount > player['chips']:
                self.send_error_to_player(player_sid, "您的籌碼不足以購買保險。")
                return False
            
            player['has_insurance'] = True
            player['insurance_bet'] = insurance_amount
            player['chips'] -= insurance_amount
            print(f"[21點房間 {self.room_id}] 玩家 {player['name']} 購買了保險，金額 {insurance_amount}。")
            self.broadcast_state(message=f"玩家 {player['name']} 購買了保險。")
        else:
            player['has_insurance'] = False
            print(f"[21點房間 {self.room_id}] 玩家 {player['name']} 拒絕購買保險。")
            self.broadcast_state(message=f"玩家 {player['name']} 拒絕購買保險。")
        
        # 檢查是否所有玩家都已做出保險選擇
        all_players_decided = all(p['has_insurance'] is not None for p in self.players.values() if p['is_active_in_round'])
        if all_players_decided:
            self._check_dealer_blackjack()
        
        return True

    def handle_action(self, player_sid, action_type, data=None):
        """處理玩家的遊戲動作（要牌、停牌、雙倍下注等）"""
        if data is None:
            data = {}
        
        if not self.is_game_in_progress:
            self.send_error_to_player(player_sid, "遊戲尚未開始或已結束。")
            return False
        
        if self.game_state['game_phase'] == 'betting':
            # 處理下注動作
            if action_type == 'bet':
                return self.place_bet(player_sid, data.get('amount', 0))
            else:
                self.send_error_to_player(player_sid, "當前階段只能進行下注。")
                return False
        
        if self.game_state['game_phase'] == 'insurance':
            # 處理保險動作
            if action_type == 'insurance':
                return self.take_insurance(player_sid, data.get('take', False))
            else:
                self.send_error_to_player(player_sid, "當前階段只能決定是否購買保險。")
                return False
        
        if self.game_state['game_phase'] != 'player_turns':
            self.send_error_to_player(player_sid, "目前非玩家行動階段。")
            return False
        
        if self.game_state['current_turn_sid'] != player_sid:
            self.send_error_to_player(player_sid, "還沒輪到您行動。")
            return False
        
        player = self.players.get(player_sid)
        if not player or not player['is_active_in_round']:
            self.send_error_to_player(player_sid, "您不在本局遊戲中。")
            return False
        
        if player['is_busted'] or player['has_blackjack']:
            self.send_error_to_player(player_sid, "您已經爆牌或有21點，無法繼續行動。")
            return False
        
        action_message = f"玩家 {player['name']}"
        action_processed_successfully = False
        
        if action_type == 'hit':  # 要牌
            new_card = deal_cards(self.game_state['deck'], 1)[0]
            player['hand'].append(new_card)
            player['hand_value'] = calculate_hand_value(player['hand'])
            
            action_message += f" 要了一張牌：{new_card['rank']}{new_card['suit']}。"
            
            if is_bust(player['hand']):
                player['is_busted'] = True
                action_message += f" 爆牌了！手牌點數：{player['hand_value']}。"
                self._advance_to_next_player_or_phase()
            
            action_processed_successfully = True
        
        elif action_type == 'stand':  # 停牌
            action_message += " 選擇停牌。"
            action_processed_successfully = True
            self._advance_to_next_player_or_phase()
        
        elif action_type == 'double':  # 雙倍下注
            if len(player['hand']) != 2:
                self.send_error_to_player(player_sid, "只有初始兩張牌時才能雙倍下注。")
                return False
            
            if player['bet'] > player['chips']:
                self.send_error_to_player(player_sid, "您的籌碼不足以雙倍下注。")
                return False
            
            # 雙倍下注並再要一張牌
            player['chips'] -= player['bet']
            player['bet'] *= 2
            player['has_doubled_down'] = True
            
            new_card = deal_cards(self.game_state['deck'], 1)[0]
            player['hand'].append(new_card)
            player['hand_value'] = calculate_hand_value(player['hand'])
            
            action_message += f" 雙倍下注，總下注為 {player['bet']}，並要了一張牌：{new_card['rank']}{new_card['suit']}。"
            
            if is_bust(player['hand']):
                player['is_busted'] = True
                action_message += f" 爆牌了！手牌點數：{player['hand_value']}。"
            
            action_processed_successfully = True
            self._advance_to_next_player_or_phase()  # 雙倍下注後自動進入下一個玩家或階段
        
        if action_processed_successfully:
            print(f"[21點房間 {self.room_id}] {action_message}")
            self.broadcast_state(message=action_message)
            return True
        
        return False

    def _advance_to_next_player_or_phase(self):
        """移至下一個玩家行動或進入下一階段"""
        if self.game_state['game_phase'] != 'player_turns':
            return
        
        current_idx = -1
        if self.game_state['current_turn_sid'] in self.game_state['round_active_players_sids_in_order']:
            current_idx = self.game_state['round_active_players_sids_in_order'].index(self.game_state['current_turn_sid'])
        
        next_player_found = False
        for i in range(current_idx + 1, len(self.game_state['round_active_players_sids_in_order'])):
            next_sid = self.game_state['round_active_players_sids_in_order'][i]
            if self.players[next_sid]['is_active_in_round'] and not self.players[next_sid]['is_busted'] and not self.players[next_sid]['has_blackjack']:
                self.game_state['current_turn_sid'] = next_sid
                next_player_found = True
                player_name = self.players[next_sid]['name']
                print(f"[21點房間 {self.room_id}] 輪到玩家 {player_name} 行動。")
                self.broadcast_state(message=f"輪到玩家 {player_name} 行動。")
                break
        
        if not next_player_found:
            # 所有玩家都已行動完畢，進入莊家回合
            self._dealer_turn()

    def _dealer_turn(self):
        """莊家回合"""
        self.game_state['game_phase'] = 'dealer_turn'
        print(f"[21點房間 {self.room_id}] 進入莊家回合。")
        self.broadcast_state(message="進入莊家回合。")
        
        # 檢查是否所有玩家都爆牌，如果是，莊家不需要要牌
        all_players_busted = all(p['is_busted'] or not p['is_active_in_round'] for p in self.players.values())
        
        if not all_players_busted:
            # 莊家按規則要牌（17點以下必須要牌，17點及以上必須停牌）
            dealer_action_message = "莊家："
            while self.game_state['dealer_hand_value'] < 17:
                new_card = deal_cards(self.game_state['deck'], 1)[0]
                self.game_state['dealer_hand'].append(new_card)
                self.game_state['dealer_hand_value'] = calculate_hand_value(self.game_state['dealer_hand'])
                dealer_action_message += f" 要了一張牌：{new_card['rank']}{new_card['suit']}。"
            
            if is_bust(self.game_state['dealer_hand']):
                dealer_action_message += f" 莊家爆牌了！手牌點數：{self.game_state['dealer_hand_value']}。"
            else:
                dealer_action_message += f" 莊家停牌，手牌點數：{self.game_state['dealer_hand_value']}。"
            
            print(f"[21點房間 {self.room_id}] {dealer_action_message}")
            self.broadcast_state(message=dealer_action_message)
        
        # 結算本局
        self._settle_round()

    def _settle_round(self):
        """結算本局遊戲"""
        self.game_state['game_phase'] = 'settlement'
        print(f"[21點房間 {self.room_id}] 開始結算本局遊戲。")
        
        dealer_has_blackjack = self.game_state['dealer_has_blackjack']
        dealer_busted = is_bust(self.game_state['dealer_hand'])
        
        settlement_messages = []
        
        for sid, player in self.players.items():
            if not player['is_active_in_round']:
                continue
            
            result_message = f"玩家 {player['name']}："
            
            # 處理保險賠付
            if player['has_insurance']:
                if dealer_has_blackjack:
                    insurance_win = player['insurance_bet'] * 2  # 保險賠付2:1
                    player['chips'] += insurance_win
                    result_message += f" 保險贏得 {insurance_win}。"
                else:
                    result_message += f" 保險輸了 {player['insurance_bet']}。"
            
            # 處理主要賭注
            if player['is_busted']:
                # 玩家爆牌
                result_message += f" 爆牌，損失 {player['bet']}。"
            elif player['has_blackjack']:
                if dealer_has_blackjack:
                    # 雙方都有21點，平局
                    player['chips'] += player['bet']
                    result_message += f" 和莊家都有21點，平局，返還 {player['bet']}。"
                else:
                    # 玩家有21點，莊家沒有，賠付3:2
                    win_amount = player['bet'] * 1.5
                    player['chips'] += player['bet'] + win_amount
                    result_message += f" 21點獲勝，贏得 {win_amount}。"
            elif dealer_has_blackjack:
                # 莊家有21點，玩家沒有
                result_message += f" 莊家有21點，損失 {player['bet']}。"
            elif dealer_busted:
                # 莊家爆牌
                win_amount = player['bet']
                player['chips'] += player['bet'] * 2
                result_message += f" 莊家爆牌，贏得 {win_amount}。"
            else:
                # 比點數
                compare_result = compare_hands(player['hand'], self.game_state['dealer_hand'])
                if compare_result > 0:
                    # 玩家贏
                    win_amount = player['bet']
                    player['chips'] += player['bet'] * 2
                    result_message += f" 點數較高，贏得 {win_amount}。"
                elif compare_result < 0:
                    # 莊家贏
                    result_message += f" 點數較低，損失 {player['bet']}。"
                else:
                    # 平局
                    player['chips'] += player['bet']
                    result_message += f" 點數相同，平局，返還 {player['bet']}。"
            
            settlement_messages.append(result_message)
            print(f"[21點房間 {self.room_id}] {result_message}")
        
        # 廣播結算結果
        self.broadcast_state(message="\n".join(settlement_messages))
        
        # 等一會兒後開始新一局
        self.is_game_in_progress = False
        print(f"[21點房間 {self.room_id}] 本局遊戲已結束。")
        
        # 可以在這裡設置定時器，幾秒後自動開始新一局
        # self.socketio.start_background_task(self._auto_start_new_round)
        
        return True

    def get_state_for_player(self, player_sid):
        """為特定玩家準備遊戲狀態，隱藏其他玩家的手牌等敏感資訊。"""
        if player_sid not in self.players:
            return None  # 玩家已離開

        public_players_data = []
        for sid, p_data in self.players.items():
            player_view = {
                'sid': sid,
                'name': p_data['name'],
                'chips': p_data['chips'],
                'bet': p_data['bet'],
                'is_active_in_round': p_data['is_active_in_round'],
                'is_busted': p_data['is_busted'],
                'has_blackjack': p_data['has_blackjack'],
                'has_doubled_down': p_data['has_doubled_down'],
                'has_insurance': p_data['has_insurance'],
                'insurance_bet': p_data['insurance_bet'],
                'hand_value': p_data['hand_value']
            }
            
            # 隱藏特定玩家資訊
            if sid == player_sid:
                # 當前玩家，可以看到自己的手牌
                player_view['hand'] = p_data.get('hand', [])
            elif self.game_state['game_phase'] in ['settlement', 'dealer_turn']:
                # 結算階段或莊家回合，顯示所有玩家的手牌
                player_view['hand'] = p_data.get('hand', [])
            else:
                # 其他情況玩家只能看到其他人的第一張牌
                if p_data.get('hand') and len(p_data['hand']) > 0:
                    player_view['hand'] = [p_data['hand'][0]]
                else:
                    player_view['hand'] = []
            
            public_players_data.append(player_view)

        # 準備莊家資訊
        dealer_view = {
            'hand': [],
            'hand_value': self.game_state['dealer_hand_value'],
            'has_blackjack': self.game_state['dealer_has_blackjack']
        }
        
        # 決定莊家的牌要露出多少
        if self.game_state['game_phase'] in ['settlement', 'dealer_turn']:
            # 結算階段或莊家回合，顯示莊家的所有牌
            dealer_view['hand'] = self.game_state['dealer_hand']
        elif self.game_state['dealer_hand']:
            # 其他階段只顯示莊家的第一張牌
            dealer_view['hand'] = [self.game_state['dealer_hand'][0]]

        state_for_player = {
            'room_id': self.room_id,
            'game_type': self.get_game_type(),
            'is_game_in_progress': self.is_game_in_progress,
            'players': public_players_data,
            'dealer': dealer_view,
            'current_turn_sid': self.game_state.get('current_turn_sid'),
            'game_phase': self.game_state.get('game_phase'),
            'min_bet': self.game_state.get('min_bet'),
            'max_bet': self.game_state.get('max_bet'),
            'options': self.options
        }
        
        return state_for_player