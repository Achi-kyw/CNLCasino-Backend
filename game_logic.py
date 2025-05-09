import random

# --- 牌組相關 ---
SUITS = ['H', 'D', 'C', 'S'] # 紅心, 方塊, 梅花, 黑桃
RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A']

def create_deck():
    return [{'rank': rank, 'suit': suit} for suit in SUITS for rank in RANKS]

def shuffle_deck(deck):
    random.shuffle(deck)
    return deck

def deal_cards(deck, num_cards):
    dealt = []
    for _ in range(num_cards):
        if deck:
            dealt.append(deck.pop())
    return dealt

# --- 遊戲狀態管理 (非常簡化) ---
# 你可以將這些變數移到一個 GameRoom class 中
GAME_ROOM = {
    'players': {},  # sid: {'name': 'PlayerName', 'chips': 1000, 'hand': [], 'current_bet': 0, 'is_active': True, 'has_acted_this_round': False}
    'deck': [],
    'community_cards': [],
    'pot': 0,
    'current_turn_sid': None,
    'current_bet_to_match': 0,
    'game_phase': None, # 'pre-flop', 'flop', 'turn', 'river', 'showdown'
    'dealer_button_idx': 0, # 玩家列表中的索引
    'small_blind': 10,
    'big_blind': 20,
    'game_in_progress': False,
    'min_raise': 20, # 最小加注額
    'last_raiser_sid': None # 最後加注的玩家
}

def reset_round_state():
    GAME_ROOM['deck'] = shuffle_deck(create_deck())
    GAME_ROOM['community_cards'] = []
    GAME_ROOM['pot'] = 0
    GAME_ROOM['current_bet_to_match'] = 0
    GAME_ROOM['game_phase'] = 'pre-flop'
    GAME_ROOM['last_raiser_sid'] = None
    for sid in GAME_ROOM['players']:
        GAME_ROOM['players'][sid]['hand'] = []
        GAME_ROOM['players'][sid]['current_bet'] = 0
        GAME_ROOM['players'][sid]['is_active'] = True # 參與這一局
        GAME_ROOM['players'][sid]['has_acted_this_round'] = False

def add_player_to_game(sid, name):
    if sid not in GAME_ROOM['players']:
        GAME_ROOM['players'][sid] = {
            'name': name,
            'chips': 1000, # 初始籌碼
            'hand': [],
            'current_bet': 0,
            'is_active': False, # 初始不活躍，等待遊戲開始
            'has_acted_this_round': False
        }
        return True
    return False

def remove_player_from_game(sid):
    if sid in GAME_ROOM['players']:
        del GAME_ROOM['players'][sid]
        # 如果遊戲正在進行，需要處理該玩家的退出邏輯 (例如棄牌)
        # 並重新評估遊戲是否能繼續
        return True
    return False

def get_active_players_sids_in_order():
    player_sids = list(GAME_ROOM['players'].keys())
    if not player_sids:
        return []

    # 簡單輪轉，實際德州撲克順序更複雜 (考慮大小盲、按鈕位)
    num_players = len(player_sids)
    dealer_idx = GAME_ROOM['dealer_button_idx'] % num_players

    # 假設 dealer_idx 指向的 player_sids[dealer_idx] 是按鈕位
    # 順序是按鈕位之後開始
    ordered_sids = []
    # 這裡需要實現從小盲開始的行動順序
    # 為了簡化，我們先假設一個簡單的順序
    # 在真實遊戲中，你需要根據按鈕位、小盲、大盲位置來決定
    start_idx = (dealer_idx + 1) % num_players # 假設小盲是按鈕後一個
    for i in range(num_players):
        current_player_idx = (start_idx + i) % num_players
        sid = player_sids[current_player_idx]
        if GAME_ROOM['players'][sid]['is_active'] and GAME_ROOM['players'][sid]['chips'] > 0:
            ordered_sids.append(sid)
    return ordered_sids


def start_new_round():
    if len(GAME_ROOM['players']) < 2: # 至少需要2個玩家
        print("Not enough players to start a new round.")
        return False

    GAME_ROOM['game_in_progress'] = True
    reset_round_state()

    # 1. 決定按鈕位、大小盲注 (簡化)
    player_sids = list(GAME_ROOM['players'].keys())
    num_players = len(player_sids)
    GAME_ROOM['dealer_button_idx'] = (GAME_ROOM['dealer_button_idx'] + 1) % num_players
    dealer_sid = player_sids[GAME_ROOM['dealer_button_idx']]

    # 為了簡化，我們假設玩家按加入順序坐，並以此定大小盲
    # 真實遊戲中，座位和小大盲位置更固定
    active_player_sids = [sid for sid in player_sids if GAME_ROOM['players'][sid]['chips'] > 0]
    if len(active_player_sids) < 2:
        print("Not enough active players with chips.")
        GAME_ROOM['game_in_progress'] = False
        return False

    # 假設按鈕位是 active_player_sids[GAME_ROOM['dealer_button_idx'] % len(active_player_sids)]
    # 這裡的按鈕位、大小盲邏輯需要非常仔細地實現
    # 以下是一個非常簡化的示意：
    # 找到按鈕位在 active_player_sids 中的索引
    try:
        current_dealer_actual_sid = player_sids[GAME_ROOM['dealer_button_idx']]
        dealer_idx_in_active = active_player_sids.index(current_dealer_actual_sid)
    except ValueError: # 如果按鈕位玩家剛好沒籌碼退出了
        GAME_ROOM['dealer_button_idx'] = (GAME_ROOM['dealer_button_idx'] + 1) % num_players # 嘗試下一個
        current_dealer_actual_sid = player_sids[GAME_ROOM['dealer_button_idx']]
        dealer_idx_in_active = active_player_sids.index(current_dealer_actual_sid)


    sb_player_idx = (dealer_idx_in_active + 1) % len(active_player_sids)
    bb_player_idx = (dealer_idx_in_active + 2) % len(active_player_sids)

    sb_sid = active_player_sids[sb_player_idx]
    bb_sid = active_player_sids[bb_player_idx]

    # 下小盲
    sb_amount = min(GAME_ROOM['small_blind'], GAME_ROOM['players'][sb_sid]['chips'])
    GAME_ROOM['players'][sb_sid]['chips'] -= sb_amount
    GAME_ROOM['players'][sb_sid]['current_bet'] = sb_amount
    GAME_ROOM['pot'] += sb_amount

    # 下大盲
    bb_amount = min(GAME_ROOM['big_blind'], GAME_ROOM['players'][bb_sid]['chips'])
    GAME_ROOM['players'][bb_sid]['chips'] -= bb_amount
    GAME_ROOM['players'][bb_sid]['current_bet'] = bb_amount
    GAME_ROOM['pot'] += bb_amount

    GAME_ROOM['current_bet_to_match'] = GAME_ROOM['big_blind']
    GAME_ROOM['min_raise'] = GAME_ROOM['big_blind'] * 2 # 最小加注是再加一個大盲的額度

    # 2. 發底牌
    for sid in active_player_sids:
        GAME_ROOM['players'][sid]['hand'] = deal_cards(GAME_ROOM['deck'], 2)
        GAME_ROOM['players'][sid]['is_active'] = True # 參與此局
        GAME_ROOM['players'][sid]['has_acted_this_round'] = False


    # 3. 決定第一個行動的玩家 (大盲後一位)
    action_idx = (bb_player_idx + 1) % len(active_player_sids)
    GAME_ROOM['current_turn_sid'] = active_player_sids[action_idx]
    GAME_ROOM['game_phase'] = 'pre-flop'
    GAME_ROOM['last_raiser_sid'] = bb_sid # 大盲是第一個 "加注者"

    print(f"New round started. Dealer: {dealer_sid}, SB: {sb_sid}, BB: {bb_sid}")
    print(f"Turn: {GAME_ROOM['current_turn_sid']}")
    return True


def advance_to_next_player_or_phase():
    active_players_in_order = get_active_players_sids_in_order()
    if not active_players_in_order: # 沒有活躍玩家了
        # 可能只有一人未棄牌，直接結束
        handle_showdown_or_win_by_fold()
        return

    current_turn_sid = GAME_ROOM['current_turn_sid']
    try:
        current_idx = active_players_in_order.index(current_turn_sid)
    except ValueError: # 當前玩家可能剛棄牌或 all-in
        # 這種情況下，需要重新計算下一個玩家
        # 簡易處理：從頭找第一個未行動的
        for sid in active_players_in_order:
            if not GAME_ROOM['players'][sid]['has_acted_this_round'] and GAME_ROOM['players'][sid]['is_active'] and GAME_ROOM['players'][sid]['chips'] > 0:
                GAME_ROOM['current_turn_sid'] = sid
                return
        # 如果都行動過了，進入下一階段
        return proceed_to_next_betting_round()


    # 檢查是否所有人都行動完畢或下注一致
    all_acted_and_bets_equal = True
    num_active_players_in_hand = 0 # 仍在牌局中且有籌碼的玩家

    for sid in active_players_in_order:
        player = GAME_ROOM['players'][sid]
        if player['is_active'] and player['chips'] > 0: # 仍在牌局中且非 all-in 狀態
            num_active_players_in_hand +=1
            if not player['has_acted_this_round']:
                all_acted_and_bets_equal = False
                break
            if player['current_bet'] < GAME_ROOM['current_bet_to_match'] and player['chips'] > 0 : # 排除all-in且下注不足的情況
                all_acted_and_bets_equal = False
                break
        elif player['is_active'] and player['chips'] == 0 and player['current_bet'] < GAME_ROOM['current_bet_to_match']:
            # All-in 玩家，但下注額小於當前應跟注額，他們已行動完畢
            pass


    if num_active_players_in_hand <= 1 and GAME_ROOM['game_phase'] != 'showdown':
         # 如果只剩一個或零個玩家有籌碼且活躍，直接攤牌或判定獲勝
        handle_showdown_or_win_by_fold()
        return

    if all_acted_and_bets_equal:
        # 檢查是否所有活躍玩家的 current_bet 都等於 current_bet_to_match (或 all-in)
        # 或者是，所有人都過牌 (current_bet_to_match == 0 且大家都 check)
        # 這部分邏輯比較複雜，需要精確判斷一輪下注是否結束
        # 簡易判斷：如果所有 is_active 且 chips > 0 的玩家都 has_acted_this_round，
        # 並且他們的 current_bet 都等於 current_bet_to_match (除非他們 all-in 了)
        # 並且，行動輪回到最初的加注者，或者所有人都 check
        is_betting_round_complete = True
        initial_raiser_has_option = False # 加注者是否有再次行動的權利

        if GAME_ROOM['last_raiser_sid']: # 如果有加注
            idx_last_raiser = -1
            try:
                idx_last_raiser = active_players_in_order.index(GAME_ROOM['last_raiser_sid'])
            except ValueError: # 加注者已棄牌
                pass # 這輪繼續

            # 檢查是否輪回到加注者之前的所有人都行動了
            # 並且他們的 bet 都等於 current_bet_to_match 或 all-in
            for i in range(len(active_players_in_order)):
                sid_to_check = active_players_in_order[i]
                player_to_check = GAME_ROOM['players'][sid_to_check]
                if not player_to_check['is_active']: continue

                if not player_to_check['has_acted_this_round'] and player_to_check['chips'] > 0:
                    is_betting_round_complete = False
                    break
                if player_to_check['chips'] > 0 and player_to_check['current_bet'] < GAME_ROOM['current_bet_to_match']:
                    is_betting_round_complete = False
                    break
            if is_betting_round_complete: # 所有人都行動過了，且bet都符合
                 proceed_to_next_betting_round()
                 return

        else: # 沒有加注，大家都在check
            all_checked = True
            for sid_to_check in active_players_in_order:
                player_to_check = GAME_ROOM['players'][sid_to_check]
                if not player_to_check['is_active']: continue
                if not player_to_check['has_acted_this_round'] and player_to_check['chips'] > 0 :
                    all_checked = False
                    break
            if all_checked:
                proceed_to_next_betting_round()
                return


    # 移到下一個玩家
    next_player_found = False
    for i in range(1, len(active_players_in_order) + 1):
        next_idx = (current_idx + i) % len(active_players_in_order)
        next_player_sid = active_players_in_order[next_idx]
        player = GAME_ROOM['players'][next_player_sid]
        if player['is_active'] and player['chips'] > 0: # 玩家仍在牌局中且有籌碼
            GAME_ROOM['current_turn_sid'] = next_player_sid
            next_player_found = True
            break

    if not next_player_found:
        # 可能所有人都 all-in 或只剩一人
        proceed_to_next_betting_round() # 進入下一階段或攤牌


def proceed_to_next_betting_round():
    print(f"Proceeding from phase: {GAME_ROOM['game_phase']}")
    # 重置所有活躍玩家的 has_acted_this_round 狀態
    for sid in GAME_ROOM['players']:
        if GAME_ROOM['players'][sid]['is_active']:
            GAME_ROOM['players'][sid]['has_acted_this_round'] = False

    # 將本輪下注的籌碼從小籌碼堆移到總底池 (概念上，實際已在pot)
    # 並重置 current_bet for players for the next round (不是這麼做，current_bet 是本輪總下注)
    # 重要的是重置 current_bet_to_match (如果新一輪是 check 開始)
    GAME_ROOM['current_bet_to_match'] = 0 # 新一輪從 check 開始
    GAME_ROOM['last_raiser_sid'] = None # 新一輪還沒有人加注

    # 決定下一個行動者 (通常是按鈕位後的第一个活躍玩家)
    active_players_sids = get_active_players_sids_in_order() # 獲取當前正確順序的活躍玩家
    if not active_players_sids:
        handle_showdown_or_win_by_fold()
        return

    # 通常是小盲位開始 (如果他還在牌局中)
    # 這裡需要找到 dealer button 之後的第一個 is_active and chips > 0 的玩家
    player_sids_all = list(GAME_ROOM['players'].keys())
    dealer_actual_sid = player_sids_all[GAME_ROOM['dealer_button_idx'] % len(player_sids_all)]
    
    # 找到按鈕位在 active_players_sids 中的位置 (如果按鈕位玩家還活躍)
    try:
        dealer_idx_in_active = active_players_sids.index(dealer_actual_sid)
        start_player_idx = (dealer_idx_in_active + 1) % len(active_players_sids)
    except ValueError: # 按鈕位玩家已不活躍，從第一個活躍玩家開始
        start_player_idx = 0
    
    first_to_act_sid = None
    for i in range(len(active_players_sids)):
        check_idx = (start_player_idx + i) % len(active_players_sids)
        sid_to_check = active_players_sids[check_idx]
        if GAME_ROOM['players'][sid_to_check]['is_active'] and GAME_ROOM['players'][sid_to_check]['chips'] > 0:
            first_to_act_sid = sid_to_check
            break
    
    if not first_to_act_sid: # 沒有可以行動的玩家了
        handle_showdown_or_win_by_fold()
        return

    GAME_ROOM['current_turn_sid'] = first_to_act_sid


    if GAME_ROOM['game_phase'] == 'pre-flop':
        GAME_ROOM['game_phase'] = 'flop'
        GAME_ROOM['community_cards'].extend(deal_cards(GAME_ROOM['deck'], 3))
    elif GAME_ROOM['game_phase'] == 'flop':
        GAME_ROOM['game_phase'] = 'turn'
        GAME_ROOM['community_cards'].extend(deal_cards(GAME_ROOM['deck'], 1))
    elif GAME_ROOM['game_phase'] == 'turn':
        GAME_ROOM['game_phase'] = 'river'
        GAME_ROOM['community_cards'].extend(deal_cards(GAME_ROOM['deck'], 1))
    elif GAME_ROOM['game_phase'] == 'river':
        GAME_ROOM['game_phase'] = 'showdown'
        handle_showdown_or_win_by_fold()
        return # 攤牌後結束
    else: # 遊戲結束或錯誤
        GAME_ROOM['game_in_progress'] = False
        return

    print(f"Advanced to phase: {GAME_ROOM['game_phase']}, Community: {GAME_ROOM['community_cards']}")
    # 如果下一階段沒有下注（例如所有人都all-in了），直接進入再下一階段
    active_players_with_chips = [
        p_sid for p_sid in active_players_sids
        if GAME_ROOM['players'][p_sid]['is_active'] and GAME_ROOM['players'][p_sid]['chips'] > 0
    ]
    if len(active_players_with_chips) < 2 and GAME_ROOM['game_phase'] not in ['showdown', None]:
        # 少於兩個玩家可以下注，直接開完剩下的公共牌
        while GAME_ROOM['game_phase'] not in ['showdown', None]:
            if GAME_ROOM['game_phase'] == 'flop' and len(GAME_ROOM['community_cards']) < 3:
                 GAME_ROOM['community_cards'].extend(deal_cards(GAME_ROOM['deck'], 3 - len(GAME_ROOM['community_cards'])))
            if GAME_ROOM['game_phase'] in ['flop', 'turn'] and len(GAME_ROOM['community_cards']) < 4:
                 GAME_ROOM['community_cards'].extend(deal_cards(GAME_ROOM['deck'], 1))
            if GAME_ROOM['game_phase'] in ['flop', 'turn', 'river'] and len(GAME_ROOM['community_cards']) < 5:
                 GAME_ROOM['community_cards'].extend(deal_cards(GAME_ROOM['deck'], 1))

            if GAME_ROOM['game_phase'] == 'river': GAME_ROOM['game_phase'] = 'showdown'
            elif GAME_ROOM['game_phase'] == 'turn': GAME_ROOM['game_phase'] = 'river'
            elif GAME_ROOM['game_phase'] == 'flop': GAME_ROOM['game_phase'] = 'turn'
            else: break # Should be showdown
        handle_showdown_or_win_by_fold()


def handle_player_action(sid, action, amount=0):
    player = GAME_ROOM['players'].get(sid)
    if not player or sid != GAME_ROOM['current_turn_sid'] or not player['is_active']:
        print(f"Invalid action: Not player's turn or player inactive. SID: {sid}, Turn: {GAME_ROOM['current_turn_sid']}")
        return {'success': False, 'message': "Not your turn or you are inactive."}

    player['has_acted_this_round'] = True
    current_bet_to_match_for_player = GAME_ROOM['current_bet_to_match'] - player['current_bet']

    if action == 'fold':
        player['is_active'] = False
        print(f"Player {player['name']} folds.")
        # 檢查是否只剩一人，若是則該人獲勝
        active_players_in_game = [p_sid for p_sid, p_data in GAME_ROOM['players'].items() if p_data['is_active']]
        if len(active_players_in_game) == 1:
            winner_sid = active_players_in_game[0]
            GAME_ROOM['players'][winner_sid]['chips'] += GAME_ROOM['pot']
            print(f"Player {GAME_ROOM['players'][winner_sid]['name']} wins {GAME_ROOM['pot']} by default.")
            # 這裡需要廣播結果並準備下一局
            GAME_ROOM['game_phase'] = 'showdown' # 標記為結束
            GAME_ROOM['game_in_progress'] = False
            return {'success': True, 'action': 'fold', 'next_phase': 'showdown'} # 表示遊戲因棄牌結束

    elif action == 'check':
        if current_bet_to_match_for_player > 0: # 不能 check，必須跟注或加注或棄牌
            print(f"Player {player['name']} cannot check, current bet is {GAME_ROOM['current_bet_to_match']}")
            player['has_acted_this_round'] = False # Action invalid, reset
            return {'success': False, 'message': "Cannot check, there is a bet to call."}
        print(f"Player {player['name']} checks.")

    elif action == 'call':
        if current_bet_to_match_for_player <= 0: # 沒有需要 call 的金額，應該是 check
             print(f"Player {player['name']} trying to call when no bet or already matched. Should be check.")
             # 可以視為 check
             player['has_acted_this_round'] = True # 已經行動了
        else:
            call_amount = min(current_bet_to_match_for_player, player['chips'])
            player['chips'] -= call_amount
            player['current_bet'] += call_amount
            GAME_ROOM['pot'] += call_amount
            print(f"Player {player['name']} calls {call_amount}. Total bet: {player['current_bet']}")
            if player['chips'] == 0:
                print(f"Player {player['name']} is All-in.")

    elif action == 'bet': # 通常是第一輪的 open bet
        if GAME_ROOM['current_bet_to_match'] > 0: # 如果已經有人下注了，應該是 raise
            return handle_player_action(sid, 'raise', amount) # 轉交給 raise 處理

        bet_amount = int(amount)
        if bet_amount < GAME_ROOM['min_raise'] and bet_amount < player['chips'] : # 最小下注額 (例如大盲) 且不是 all-in
            print(f"Player {player['name']} bet {bet_amount} is less than min_raise {GAME_ROOM['min_raise']}.")
            player['has_acted_this_round'] = False # Action invalid, reset
            return {'success': False, 'message': f"Bet amount too small. Min bet: {GAME_ROOM['min_raise']}"}
        if bet_amount > player['chips']:
            bet_amount = player['chips'] # All-in

        player['chips'] -= bet_amount
        player['current_bet'] += bet_amount
        GAME_ROOM['pot'] += bet_amount
        GAME_ROOM['current_bet_to_match'] = player['current_bet']
        GAME_ROOM['min_raise'] = player['current_bet'] * 2 # 下一個最小加注是當前總下注的兩倍
        GAME_ROOM['last_raiser_sid'] = sid
        print(f"Player {player['name']} bets {bet_amount}. Total bet: {player['current_bet']}")
        if player['chips'] == 0:
            print(f"Player {player['name']} is All-in.")

    elif action == 'raise':
        # 加注額 = 總共要下到的金額
        total_bet_amount = int(amount)
        raise_amount_needed = total_bet_amount - player['current_bet'] # 玩家還需要再投入的

        # 最小加注額的計算：
        # raise_to_at_least = GAME_ROOM['current_bet_to_match'] + (GAME_ROOM['current_bet_to_match'] - (GAME_ROOM['last_raiser_bet_amount'] or 0))
        # 簡化：最小加注後的總 bet 必須是 current_bet_to_match + min_raise_increment
        # min_raise_increment 通常是上一個 raise 的大小，或至少是大盲
        # 更簡單的規則：加注後的總額至少是 (GAME_ROOM['current_bet_to_match'] + GAME_ROOM['min_raise_increment'])
        # 或者，如果沒有之前的raise，則是 current_bet_to_match + BB
        # 這裡的 min_raise 是指總共要 bet 到的金額，而不是增加的量
        # GAME_ROOM['min_raise'] 應該代表 "下一個合法的最小總下注額"
        # 假設 GAME_ROOM['min_raise'] 已經是正確的 "加注後至少要達到的總額"

        # 實際加注額 = 玩家新投入的錢
        # 玩家的總下注 = player['current_bet'] + 實際加注額
        # 這個總下注必須 >= GAME_ROOM['current_bet_to_match'] (這是當然的)
        # 並且，這個總下注必須 >= 前一個玩家的總下注 + 最小加注差額

        previous_bet_this_round = player['current_bet']
        actual_raise_value = total_bet_amount - previous_bet_this_round # 這次新投入的錢

        if actual_raise_value <= 0 : # 沒有實際加注
            player['has_acted_this_round'] = False
            return {'success': False, 'message': "Raise amount must be higher than your current bet."}

        # 檢查 raise 的合法性 (總額)
        # 1. 必須大於等於當前要跟的注 GAME_ROOM['current_bet_to_match']
        # 2. 加注的幅度必須合法 (通常是至少等於上一個加注的幅度，或者至少一個大盲)
        #    這裡我們簡化為：新的 total_bet_amount 必須至少是 current_bet_to_match + (上次的加注額 或 大盲)
        #    更簡單的：GAME_ROOM['min_raise'] 存的是 "下一次 raise 後的最小總 bet 金額"

        # 當前最高注是 GAME_ROOM['current_bet_to_match']
        # 上一次加注的差額 (如果有的話)
        # last_raise_diff = GAME_ROOM['current_bet_to_match'] - (GAME_ROOM['players'][GAME_ROOM['last_raiser_sid']]['current_bet'] - raise_amount_of_last_raiser if GAME_ROOM['last_raiser_sid'] else 0)
        # min_total_raise_to = GAME_ROOM['current_bet_to_match'] + max(last_raise_diff, GAME_ROOM['big_blind'])

        # 假設 GAME_ROOM['min_raise'] 儲存的是 "下次加注後，總賭注至少要達到多少"
        # 這個 min_raise 的更新邏輯:
        # 當有人下注 B，則下次 raise 至少要到 B + B (即 2B)
        # 當有人下注 B，然後有人 raise 到 R1 (R1 > B)，則下次 raise 至少要到 R1 + (R1-B)

        # 這裡的 `amount` 是指玩家想要將自己的總下注額提高到多少
        required_min_total_bet_for_this_raise = GAME_ROOM['min_raise']

        if total_bet_amount < required_min_total_bet_for_this_raise and total_bet_amount < player['chips'] + player['current_bet'] : # 且不是 all-in
             player['has_acted_this_round'] = False # Action invalid, reset
             return {'success': False, 'message': f"Raise amount too small. Must raise to at least {required_min_total_bet_for_this_raise}"}

        if actual_raise_value > player['chips']: # 不夠錢
            actual_raise_value = player['chips'] # All-in
            total_bet_amount = player['current_bet'] + actual_raise_value

        player['chips'] -= actual_raise_value
        player['current_bet'] += actual_raise_value # player['current_bet'] is now total_bet_amount
        GAME_ROOM['pot'] += actual_raise_value
        
        # 更新 min_raise for the next player
        # 下一個raise，其增加量至少要等於本次raise的增加量
        # 本次raise的增加量 = total_bet_amount - GAME_ROOM['current_bet_to_match']
        raise_increment = total_bet_amount - GAME_ROOM['current_bet_to_match']
        GAME_ROOM['min_raise'] = total_bet_amount + raise_increment # 下一個raise至少要達到這個總額

        GAME_ROOM['current_bet_to_match'] = total_bet_amount
        GAME_ROOM['last_raiser_sid'] = sid

        print(f"Player {player['name']} raises to {total_bet_amount} (added {actual_raise_value}). Current bet to match: {GAME_ROOM['current_bet_to_match']}")
        if player['chips'] == 0:
            print(f"Player {player['name']} is All-in.")

        # 加注後，除了自己，其他之前已行動過的玩家 (在本輪下注中) 需要重新標記為未行動
        # 因為下注額改變了，他們需要重新決定是否跟注
        active_players_in_current_betting_order = get_active_players_sids_in_order()
        for p_sid_to_reset in active_players_in_current_betting_order:
            if p_sid_to_reset != sid : # 不是當前加注者自己
                 # 並且他們還在活躍且有籌碼
                if GAME_ROOM['players'][p_sid_to_reset]['is_active'] and GAME_ROOM['players'][p_sid_to_reset]['chips'] > 0 :
                    GAME_ROOM['players'][p_sid_to_reset]['has_acted_this_round'] = False


    else:
        print(f"Unknown action: {action}")
        player['has_acted_this_round'] = False # Action invalid, reset
        return {'success': False, 'message': "Unknown action."}

    # 處理完畢後，輪到下一個玩家或進入下一階段
    advance_to_next_player_or_phase()
    return {'success': True, 'action': action, 'amount': amount if action in ['bet', 'raise', 'call'] else 0 }

# --- 牌型判斷 (極度簡化，需要完整實現) ---
def evaluate_hand(hand, community_cards):
    # 這裡需要一個完整的德州撲克牌型判斷邏輯
    # 輸入：玩家的2張手牌，5張公共牌
    # 輸出：牌型等級和組成該牌型的牌
    # 例如：{'rank_name': 'Straight Flush', 'rank_value': 9, 'cards': [...]}
    # 為了演示，返回一個隨機值
    all_cards = hand + community_cards
    # 實際的牌型判斷邏輯...
    # ...
    # 簡易返回牌的數量作為一個假的 rank_value
    return {'rank_name': 'High Card', 'rank_value': len(all_cards), 'cards': hand}


def handle_showdown_or_win_by_fold():
    print("Entering showdown or win by fold...")
    GAME_ROOM['game_phase'] = 'showdown'
    GAME_ROOM['game_in_progress'] = False
    GAME_ROOM['current_turn_sid'] = None # 沒有人再行動

    active_players = {sid: p_data for sid, p_data in GAME_ROOM['players'].items() if p_data['is_active']}

    if not active_players:
        print("No active players at showdown.")
        # 可能所有人都 fold 到只剩0個? (不太可能，應該在fold時就處理了)
        # 或者遊戲開始前就沒人了
        # 清理底池，重置遊戲狀態
        GAME_ROOM['pot'] = 0
        return {'winners': [], 'pot': GAME_ROOM['pot'], 'community_cards': GAME_ROOM['community_cards']}


    if len(active_players) == 1:
        winner_sid = list(active_players.keys())[0]
        winner_name = GAME_ROOM['players'][winner_sid]['name']
        win_amount = GAME_ROOM['pot']
        GAME_ROOM['players'][winner_sid]['chips'] += win_amount
        GAME_ROOM['pot'] = 0
        print(f"Player {winner_name} wins {win_amount} by default (last one active).")
        return {
            'winners': [{'sid': winner_sid, 'name': winner_name, 'hand': GAME_ROOM['players'][winner_sid]['hand'], 'rank_name': 'Win by Fold', 'amount_won': win_amount}],
            'pot': 0,
            'community_cards': GAME_ROOM['community_cards']
        }

    # 多於一個玩家，進行比牌
    # 注意：真實的德州撲克需要處理邊池 (side pots)
    # 這裡簡化為只有一個主池
    best_hands = []
    for sid, player_data in active_players.items():
        if player_data['is_active']: # 確保玩家仍在牌局中 (未棄牌)
            hand_eval = evaluate_hand(player_data['hand'], GAME_ROOM['community_cards'])
            best_hands.append({'sid': sid, 'name': player_data['name'], 'hand_eval': hand_eval, 'player_hand_cards': player_data['hand']})

    if not best_hands:
        print("No hands to evaluate at showdown.")
        GAME_ROOM['pot'] = 0
        return {'winners': [], 'pot': GAME_ROOM['pot'], 'community_cards': GAME_ROOM['community_cards']}

    # 排序找到最好的牌型
    best_hands.sort(key=lambda x: x['hand_eval']['rank_value'], reverse=True)

    # 找出所有並列第一的玩家 (真實情況下，還需要比較 kicker)
    winners = []
    highest_rank_value = best_hands[0]['hand_eval']['rank_value']
    potential_winners = [bh for bh in best_hands if bh['hand_eval']['rank_value'] == highest_rank_value]

    # 簡化：平分底池
    if potential_winners:
        win_amount_each = GAME_ROOM['pot'] / len(potential_winners)
        for winner_data in potential_winners:
            GAME_ROOM['players'][winner_data['sid']]['chips'] += win_amount_each
            winners.append({
                'sid': winner_data['sid'],
                'name': winner_data['name'],
                'hand': winner_data['player_hand_cards'], # 他們自己的手牌
                'best_hand_description': winner_data['hand_eval']['rank_name'], # 牌型描述
                'winning_cards': winner_data['hand_eval']['cards'], # 組成最佳牌型的牌
                'amount_won': win_amount_each
            })
        GAME_ROOM['pot'] = 0
    else: # 不應該發生
        print("Error: No potential winners found after evaluation.")


    print(f"Showdown results: Winners: {winners}")
    # 清理上一局的 is_active, current_bet 等
    for sid in GAME_ROOM['players']:
        GAME_ROOM['players'][sid]['current_bet'] = 0
        GAME_ROOM['players'][sid]['is_active'] = False # 等待下一局手動加入或自動開始
        GAME_ROOM['players'][sid]['has_acted_this_round'] = False

    return {
        'winners': winners,
        'pot': 0, # 底池已分配
        'community_cards': GAME_ROOM['community_cards'],
        'all_hands_at_showdown': [{
            'sid': bh['sid'],
            'name': bh['name'],
            'hand': bh['player_hand_cards'],
            'eval': bh['hand_eval']['rank_name']
        } for bh in best_hands]
    }

# 注意：以上 game_logic.py 仍然是高度簡化的，特別是：
# - 輪轉和下注順序 (大小盲、按鈕位)
# - 最小加注額的精確計算
# - 邊池 (Side Pot) 處理
# - 完整的牌型比較 (包括 Kicker)
# - 玩家 All-in 後的邏輯
# - 錯誤處理和邊界條件