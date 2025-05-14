import itertools
import random # Only used for your shuffle_deck, not in evaluate_hand

# --- Poker Hand Constants (higher value is better) ---
ROYAL_FLUSH = 9
STRAIGHT_FLUSH = 8
FOUR_OF_A_KIND = 7
FULL_HOUSE = 6
FLUSH = 5
STRAIGHT = 4
THREE_OF_A_KIND = 3
TWO_PAIR = 2
ONE_PAIR = 1
HIGH_CARD = 0

# --- Card Rank to Numerical Value Mapping ---
# Consistent with your create_deck which uses '10' for Ten.
RANK_ORDER = {
    '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, 'T': 10,
    'J': 11, 'Q': 12, 'K': 13, 'A': 14
}

# --- Helper Functions ---

def card_value(card):
    """Returns the numerical value of a card's rank."""
    return RANK_ORDER[card['rank']]

def get_hand_ranks(hand_cards, reverse=True):
    """Returns a sorted list of numerical ranks from a list of card objects."""
    return sorted([card_value(c) for c in hand_cards], reverse=reverse)

def is_flush(hand_cards):
    """
    Checks if all cards in the hand have the same suit.
    Returns:
        tuple: (bool, list_of_ranks_if_flush_else_empty)
               The list of ranks is sorted descending, used for tie-breaking.
    """
    if not hand_cards or len(hand_cards) != 5:
        return False, []
    suits = {card['suit'] for card in hand_cards}
    if len(suits) == 1:
        return True, get_hand_ranks(hand_cards, reverse=True)
    return False, []

def is_straight(hand_cards):
    """
    Checks if the hand_cards form a straight.
    Returns:
        tuple: (bool, list_of_ranks_if_straight_else_empty)
               The list of ranks represents the straight, highest card first.
               For A-2-3-4-5 (wheel), returns [5,4,3,2,1] where Ace is low (1).
    """
    if not hand_cards or len(hand_cards) != 5:
        return False, []
    
    # Get unique, sorted numerical ranks (ascending)
    unique_ranks = sorted(list(set(card_value(card) for card in hand_cards)))

    if len(unique_ranks) < 5: # Need 5 distinct ranks for a straight
        return False, []

    # Check for A-2-3-4-5 straight (wheel)
    if unique_ranks == [2, 3, 4, 5, 14]:  # Ace, 2, 3, 4, 5
        return True, [5, 4, 3, 2, 1]  # Tie-breaker: 5 is high, Ace is treated as 1 (low)

    # Check for standard sequential straight
    is_sequential = True
    for i in range(len(unique_ranks) - 1):
        if unique_ranks[i+1] - unique_ranks[i] != 1:
            is_sequential = False
            break
    
    if is_sequential:
        return True, sorted(unique_ranks, reverse=True) # Tie-breaker: ranks sorted descending
        
    return False, []

def get_rank_counts(hand_cards):
    """
    Counts occurrences of each rank in the hand.
    Returns:
        tuple: (dict_rank_counts, list_sorted_ranks_by_prominence)
               dict_rank_counts: {rank_value: count}
               list_sorted_ranks_by_prominence: Ranks sorted first by count (desc), then by rank value (desc).
                                                e.g., for Full House 777JJ -> [7, 11]
                                                e.g., for Two Pair AAKKQ -> [14, 13, 12]
    """
    counts = {}
    if not hand_cards:
        return counts, []

    for card in hand_cards:
        rank_val = card_value(card)
        counts[rank_val] = counts.get(rank_val, 0) + 1
    
    # Sort ranks: primary key is count (desc), secondary key is rank value (desc)
    sorted_ranks_by_prominence = sorted(counts.keys(), key=lambda r: (counts[r], r), reverse=True)
    return counts, sorted_ranks_by_prominence

def evaluate_5_card_hand(five_cards):
    """
    Evaluates a single 5-card hand.
    Returns:
        tuple: (hand_rank_const, tie_breaker_ranks_list, five_cards_list)
               - hand_rank_const: Numerical constant for the hand (e.g., FLUSH)
               - tie_breaker_ranks_list: List of ranks for tie-breaking.
               - five_cards_list: The original 5 cards that form this hand.
    """
    if len(five_cards) != 5:
        raise ValueError("evaluate_5_card_hand requires exactly 5 cards.")

    # Check for Flush and Straight first, as they are components of Straight Flush
    _is_flush, flush_tie_breaker_ranks = is_flush(five_cards)
    _is_straight, straight_tie_breaker_ranks = is_straight(five_cards)

    # 1. Royal Flush / Straight Flush
    if _is_flush and _is_straight:
        # straight_tie_breaker_ranks is [high_card_rank, ..., low_card_rank]
        # For Royal Flush (A,K,Q,J,10), this will be [14, 13, 12, 11, 10]
        if straight_tie_breaker_ranks == [14, 13, 12, 11, 10]:
            return (ROYAL_FLUSH, straight_tie_breaker_ranks, list(five_cards))
        else: # Any other Straight Flush
            return (STRAIGHT_FLUSH, straight_tie_breaker_ranks, list(five_cards))

    # Get rank counts for pairs, trips, quads
    rank_counts, sorted_ranks_by_prominence = get_rank_counts(five_cards)

    # 2. Four of a Kind
    # The most prominent rank appears 4 times
    if rank_counts.get(sorted_ranks_by_prominence[0], 0) == 4:
        quad_rank = sorted_ranks_by_prominence[0]
        kicker_rank = sorted_ranks_by_prominence[1] # The 5th card's rank
        return (FOUR_OF_A_KIND, [quad_rank, kicker_rank], list(five_cards))

    # 3. Full House
    # Most prominent rank count is 3, second most prominent is 2
    if len(sorted_ranks_by_prominence) >= 2 and \
       rank_counts.get(sorted_ranks_by_prominence[0], 0) == 3 and \
       rank_counts.get(sorted_ranks_by_prominence[1], 0) == 2:
        three_of_kind_rank = sorted_ranks_by_prominence[0]
        pair_rank = sorted_ranks_by_prominence[1]
        return (FULL_HOUSE, [three_of_kind_rank, pair_rank], list(five_cards))

    # 4. Flush (but not a Straight Flush)
    if _is_flush:
        return (FLUSH, flush_tie_breaker_ranks, list(five_cards))

    # 5. Straight (but not a Straight Flush)
    if _is_straight:
        return (STRAIGHT, straight_tie_breaker_ranks, list(five_cards))

    # 6. Three of a Kind
    # Most prominent rank count is 3 (and not a Full House)
    if rank_counts.get(sorted_ranks_by_prominence[0], 0) == 3:
        trips_rank = sorted_ranks_by_prominence[0]
        # Kickers are the other two cards, sorted by rank descending
        kickers = sorted([r for r in sorted_ranks_by_prominence[1:]], reverse=True)
        return (THREE_OF_A_KIND, [trips_rank] + kickers, list(five_cards))

    # 7. Two Pair
    # Most prominent rank count is 2, second most prominent is 2
    if len(sorted_ranks_by_prominence) >= 3 and \
       rank_counts.get(sorted_ranks_by_prominence[0], 0) == 2 and \
       rank_counts.get(sorted_ranks_by_prominence[1], 0) == 2:
        high_pair_rank = sorted_ranks_by_prominence[0] # Already sorted by rank if counts are equal
        low_pair_rank = sorted_ranks_by_prominence[1]
        kicker_rank = sorted_ranks_by_prominence[2] # The 5th card's rank
        return (TWO_PAIR, [high_pair_rank, low_pair_rank, kicker_rank], list(five_cards))

    # 8. One Pair
    # Most prominent rank count is 2 (and not Two Pair or Full House)
    if rank_counts.get(sorted_ranks_by_prominence[0], 0) == 2:
        pair_rank = sorted_ranks_by_prominence[0]
        # Kickers are the other three cards, sorted by rank descending
        kickers = sorted([r for r in sorted_ranks_by_prominence[1:]], reverse=True)
        return (ONE_PAIR, [pair_rank] + kickers, list(five_cards))

    # 9. High Card
    # If none of the above, it's a high card hand
    high_card_tie_breaker = get_hand_ranks(five_cards, reverse=True)
    return (HIGH_CARD, high_card_tie_breaker, list(five_cards))


# --- Main Evaluation Function ---
def evaluate_hand(hole_cards, community_cards):
    """
    Evaluates the best 5-card poker hand from 2 hole cards and 5 community cards.
    Args:
        hole_cards (list): A list of 2 card dictionaries (e.g., [{'rank': 'A', 'suit': 'H'}, ...])
        community_cards (list): A list of 5 card dictionaries.
    Returns:
        dict: A dictionary describing the best hand:
              {'name': str, 'value': int, 'hand_cards': list_of_5_cards, 'tie_breaker_ranks': list_of_ints}
              - 'name': Name of the hand (e.g., "Full House")
              - 'value': Numerical rank of the hand (0-9, higher is better)
              - 'hand_cards': The 5 card objects forming the best hand, sorted by rank descending.
              - 'tie_breaker_ranks': List of numerical ranks for detailed tie-breaking.
    """
    if not hole_cards or len(hole_cards) != 2:
        # Handle error or specific game logic for incomplete hole cards
        # For now, assuming valid inputs for a full evaluation
        pass
    if not community_cards or len(community_cards) != 5:
        # Handle error or specific game logic for incomplete community cards
        pass

    all_7_cards = hole_cards + community_cards
    
    if len(all_7_cards) < 5: # Should not happen if inputs are 2 and 5
        return {'name': 'Not enough cards', 'value': -1, 'hand_cards': [], 'tie_breaker_ranks': []}

    best_eval_result = (HIGH_CARD, [0,0,0,0,0], []) # (rank_const, tie_breakers, cards)

    # Generate all 5-card combinations from the 7 available cards
    for five_card_combo_tuple in itertools.combinations(all_7_cards, 5):
        current_5_cards = list(five_card_combo_tuple)
        current_eval = evaluate_5_card_hand(current_5_cards)

        # Compare current_eval with best_eval_result
        # Tuple comparison works lexicographically:
        # 1. Compare hand_rank_const (current_eval[0] vs best_eval_result[0])
        # 2. If equal, compare tie_breaker_ranks_list (current_eval[1] vs best_eval_result[1])
        if current_eval[0] > best_eval_result[0]:
            best_eval_result = current_eval
        elif current_eval[0] == best_eval_result[0]:
            # Compare tie_breaker_ranks (lexicographically)
            if current_eval[1] > best_eval_result[1]:
                best_eval_result = current_eval
            # If tie_breaker_ranks are also identical, the hands are truly tied with these 5 cards.
            # The choice of which set of 5 cards to show (if multiple combos give same exact best hand)
            # doesn't matter for the hand's strength. We just keep the first one found or the one
            # that resulted from the > comparison if tie_breakers were different.

    # Map numerical rank constant to hand name string
    hand_names_map = {
        ROYAL_FLUSH: "Royal Flush",
        STRAIGHT_FLUSH: "Straight Flush",
        FOUR_OF_A_KIND: "Four of a Kind",
        FULL_HOUSE: "Full House",
        FLUSH: "Flush",
        STRAIGHT: "Straight",
        THREE_OF_A_KIND: "Three of a Kind",
        TWO_PAIR: "Two Pair",
        ONE_PAIR: "One Pair",
        HIGH_CARD: "High Card"
    }

    final_rank_const, final_tie_breaker_ranks, final_5_cards_list = best_eval_result
    
    # Sort the final 5 cards by rank for consistent display
    # The actual card objects are in final_5_cards_list
    sorted_hand_cards_for_display = sorted(final_5_cards_list, key=card_value, reverse=True)

    return {
        'name': hand_names_map.get(final_rank_const, "Unknown Hand"),
        'value': final_rank_const, # This is the numerical rank (0-9)
        'hand_cards': sorted_hand_cards_for_display, # The best 5 cards themselves
        'tie_breaker_ranks': final_tie_breaker_ranks # Numerical ranks for tie-breaking
    }

# --- Example Usage (using your provided deck functions for context) ---
def create_deck(): 
    # Using '10' for Ten as in your example
    ranks = ['A','2','3','4','5','6','7','8','9','T','J','Q','K']
    suits = ['H','D','C','S'] # Hearts, Diamonds, Clubs, Spades
    return [{'rank': r, 'suit': s} for s in suits for r in ranks]

def shuffle_deck(deck):
    random.shuffle(deck)
    return deck

def deal_cards(deck, num_cards):
    dealt = []
    for _ in range(num_cards):
        if deck: # Check if deck is not empty
            dealt.append(deck.pop())
    return dealt

if __name__ == '__main__':
    # Test cases
    print("--- Test Cases for Poker Hand Evaluation ---")

    # Royal Flush
    royal_flush_hand = [{'rank': 'A', 'suit': 'H'}, {'rank': 'K', 'suit': 'H'}]
    royal_flush_community = [
        {'rank': 'Q', 'suit': 'H'}, {'rank': 'J', 'suit': 'H'}, {'rank': '10', 'suit': 'H'},
        {'rank': '2', 'suit': 'D'}, {'rank': '3', 'suit': 'C'}
    ]
    result = evaluate_hand(royal_flush_hand, royal_flush_community)
    print(f"Royal Flush Test: {result['name']} (Value: {result['value']})")
    print(f"  Cards: {[(c['rank'], c['suit']) for c in result['hand_cards']]}")
    print(f"  Tie Breakers: {result['tie_breaker_ranks']}")
    assert result['name'] == "Royal Flush"

    # Straight Flush (King high)
    straight_flush_hand = [{'rank': 'K', 'suit': 'S'}, {'rank': 'Q', 'suit': 'S'}]
    straight_flush_community = [
        {'rank': 'J', 'suit': 'S'}, {'rank': '10', 'suit': 'S'}, {'rank': '9', 'suit': 'S'},
        {'rank': 'A', 'suit': 'H'}, {'rank': '2', 'suit': 'H'}
    ]
    result = evaluate_hand(straight_flush_hand, straight_flush_community)
    print(f"Straight Flush Test: {result['name']} (Value: {result['value']})")
    print(f"  Cards: {[(c['rank'], c['suit']) for c in result['hand_cards']]}")
    print(f"  Tie Breakers: {result['tie_breaker_ranks']}")
    assert result['name'] == "Straight Flush" and result['tie_breaker_ranks'][0] == RANK_ORDER['K']

    # Four of a Kind (Aces)
    four_aces_hand = [{'rank': 'A', 'suit': 'H'}, {'rank': 'A', 'suit': 'D'}]
    four_aces_community = [
        {'rank': 'A', 'suit': 'C'}, {'rank': 'A', 'suit': 'S'}, {'rank': 'K', 'suit': 'H'},
        {'rank': 'Q', 'suit': 'H'}, {'rank': 'J', 'suit': 'H'}
    ]
    result = evaluate_hand(four_aces_hand, four_aces_community)
    print(f"Four of a Kind (Aces) Test: {result['name']} (Value: {result['value']})")
    print(f"  Cards: {[(c['rank'], c['suit']) for c in result['hand_cards']]}")
    print(f"  Tie Breakers (Quad Rank, Kicker Rank): {result['tie_breaker_ranks']}")
    assert result['name'] == "Four of a Kind" and result['tie_breaker_ranks'][0] == RANK_ORDER['A']

    # Full House (Kings over Twos)
    full_house_hand = [{'rank': 'K', 'suit': 'H'}, {'rank': 'K', 'suit': 'D'}]
    full_house_community = [
        {'rank': 'K', 'suit': 'C'}, {'rank': '2', 'suit': 'S'}, {'rank': '2', 'suit': 'H'},
        {'rank': '3', 'suit': 'S'}, {'rank': '5', 'suit': 'D'}
    ]
    result = evaluate_hand(full_house_hand, full_house_community)
    print(f"Full House (K over 2) Test: {result['name']} (Value: {result['value']})")
    print(f"  Cards: {[(c['rank'], c['suit']) for c in result['hand_cards']]}")
    print(f"  Tie Breakers (Trips Rank, Pair Rank): {result['tie_breaker_ranks']}")
    assert result['name'] == "Full House" and result['tie_breaker_ranks'] == [RANK_ORDER['K'], RANK_ORDER['2']]

    # Flush (Ace high)
    ace_high_flush_hand = [{'rank': 'A', 'suit': 'D'}, {'rank': '10', 'suit': 'D'}]
    ace_high_flush_community = [
        {'rank': '7', 'suit': 'D'}, {'rank': '5', 'suit': 'D'}, {'rank': '2', 'suit': 'D'},
        {'rank': 'K', 'suit': 'H'}, {'rank': 'Q', 'suit': 'S'}
    ]
    result = evaluate_hand(ace_high_flush_hand, ace_high_flush_community)
    print(f"Flush (Ace high) Test: {result['name']} (Value: {result['value']})")
    print(f"  Cards: {[(c['rank'], c['suit']) for c in result['hand_cards']]}")
    print(f"  Tie Breakers (Ranks of flush cards): {result['tie_breaker_ranks']}")
    assert result['name'] == "Flush" and result['tie_breaker_ranks'][0] == RANK_ORDER['A']


    # Straight (Ten high)
    straight_hand_cards = [{'rank': '6', 'suit': 'H'}, {'rank': '7', 'suit': 'D'}]
    straight_community_cards = [
        {'rank': '8', 'suit': 'C'}, {'rank': '9', 'suit': 'S'}, {'rank': '10', 'suit': 'H'},
        {'rank': 'A', 'suit': 'S'}, {'rank': 'K', 'suit': 'D'}
    ]
    result = evaluate_hand(straight_hand_cards, straight_community_cards)
    print(f"Straight (Ten high) Test: {result['name']} (Value: {result['value']})")
    print(f"  Cards: {[(c['rank'], c['suit']) for c in result['hand_cards']]}")
    print(f"  Tie Breakers (High card of straight): {result['tie_breaker_ranks']}")
    assert result['name'] == "Straight" and result['tie_breaker_ranks'][0] == RANK_ORDER['10']

    # Straight (A-2-3-4-5 Wheel)
    wheel_straight_hand = [{'rank': 'A', 'suit': 'H'}, {'rank': '2', 'suit': 'D'}]
    wheel_straight_community = [
        {'rank': '3', 'suit': 'C'}, {'rank': '4', 'suit': 'S'}, {'rank': '5', 'suit': 'H'},
        {'rank': 'K', 'suit': 'S'}, {'rank': 'Q', 'suit': 'D'}
    ]
    result = evaluate_hand(wheel_straight_hand, wheel_straight_community)
    print(f"Straight (Wheel A-5) Test: {result['name']} (Value: {result['value']})")
    print(f"  Cards: {[(c['rank'], c['suit']) for c in result['hand_cards']]}")
    print(f"  Tie Breakers (5 high, A low): {result['tie_breaker_ranks']}") # Should be [5,4,3,2,1]
    assert result['name'] == "Straight" and result['tie_breaker_ranks'] == [5,4,3,2,1]


    # Three of a Kind (Sevens)
    three_sevens_hand = [{'rank': '7', 'suit': 'H'}, {'rank': '7', 'suit': 'D'}]
    three_sevens_community = [
        {'rank': '7', 'suit': 'C'}, {'rank': 'A', 'suit': 'S'}, {'rank': 'K', 'suit': 'H'},
        {'rank': 'Q', 'suit': 'S'}, {'rank': '2', 'suit': 'D'}
    ]
    result = evaluate_hand(three_sevens_hand, three_sevens_community)
    print(f"Three of a Kind (Sevens) Test: {result['name']} (Value: {result['value']})")
    print(f"  Cards: {[(c['rank'], c['suit']) for c in result['hand_cards']]}")
    print(f"  Tie Breakers (Trips Rank, Kicker1, Kicker2): {result['tie_breaker_ranks']}")
    assert result['name'] == "Three of a Kind" and result['tie_breaker_ranks'][0] == RANK_ORDER['7']

    # Two Pair (Aces and Kings)
    two_pair_hand = [{'rank': 'A', 'suit': 'H'}, {'rank': 'A', 'suit': 'D'}]
    two_pair_community = [
        {'rank': 'K', 'suit': 'C'}, {'rank': 'K', 'suit': 'S'}, {'rank': 'Q', 'suit': 'H'},
        {'rank': 'J', 'suit': 'S'}, {'rank': '2', 'suit': 'D'}
    ]
    result = evaluate_hand(two_pair_hand, two_pair_community)
    print(f"Two Pair (Aces and Kings) Test: {result['name']} (Value: {result['value']})")
    print(f"  Cards: {[(c['rank'], c['suit']) for c in result['hand_cards']]}")
    print(f"  Tie Breakers (High Pair, Low Pair, Kicker): {result['tie_breaker_ranks']}")
    assert result['name'] == "Two Pair" and result['tie_breaker_ranks'][0] == RANK_ORDER['A'] and result['tie_breaker_ranks'][1] == RANK_ORDER['K']

    # One Pair (Queens)
    one_pair_hand = [{'rank': 'Q', 'suit': 'H'}, {'rank': 'Q', 'suit': 'D'}]
    one_pair_community = [
        {'rank': 'A', 'suit': 'C'}, {'rank': 'K', 'suit': 'S'}, {'rank': 'J', 'suit': 'H'},
        {'rank': '9', 'suit': 'S'}, {'rank': '2', 'suit': 'D'}
    ]
    result = evaluate_hand(one_pair_hand, one_pair_community)
    print(f"One Pair (Queens) Test: {result['name']} (Value: {result['value']})")
    print(f"  Cards: {[(c['rank'], c['suit']) for c in result['hand_cards']]}")
    print(f"  Tie Breakers (Pair Rank, Kicker1, Kicker2, Kicker3): {result['tie_breaker_ranks']}")
    assert result['name'] == "One Pair" and result['tie_breaker_ranks'][0] == RANK_ORDER['Q']

    # High Card (Ace high)
    high_card_hand_cards = [{'rank': 'A', 'suit': 'H'}, {'rank': '10', 'suit': 'D'}]
    high_card_community_cards = [
        {'rank': '8', 'suit': 'C'}, {'rank': '5', 'suit': 'S'}, {'rank': '3', 'suit': 'H'},
        {'rank': '2', 'suit': 'S'}, {'rank': '4', 'suit': 'D'} # No pair, no flush, no straight
    ]
    # Ensure no straight (A,2,3,4,5) or (A,10,8,5,4)
    # Make community unique: 8C, 5S, 4H, 2D, 7S
    high_card_community_cards_2 = [
        {'rank': '8', 'suit': 'C'}, {'rank': '7', 'suit': 'S'}, {'rank': '4', 'suit': 'H'},
        {'rank': '2', 'suit': 'D'}, {'rank': '5', 'suit': 'S'} # A,10,8,7,5
    ]
    result = evaluate_hand(high_card_hand_cards, high_card_community_cards_2)
    print(f"High Card (Ace high) Test: {result['name']} (Value: {result['value']})")
    print(f"  Cards: {[(c['rank'], c['suit']) for c in result['hand_cards']]}")
    print(f"  Tie Breakers (All 5 card ranks desc): {result['tie_breaker_ranks']}")
    assert result['name'] == "High Card" and result['tie_breaker_ranks'][0] == RANK_ORDER['A']

    print("\n--- Random Deck Test ---")
    deck = create_deck()
    shuffled_deck = shuffle_deck(deck) # Your shuffle_deck uses random.shuffle
    
    my_hole_cards = deal_cards(shuffled_deck, 2)
    current_community_cards = deal_cards(shuffled_deck, 5)

    print(f"My Hole Cards: {[(c['rank'], c['suit']) for c in my_hole_cards]}")
    print(f"Community Cards: {[(c['rank'], c['suit']) for c in current_community_cards]}")

    best_hand_info = evaluate_hand(my_hole_cards, current_community_cards)
    print(f"\nBest Hand: {best_hand_info['name']} (Value: {best_hand_info['value']})")
    print(f"  Formed by cards: {[(c['rank'], c['suit']) for c in best_hand_info['hand_cards']]}")
    print(f"  Tie Breaker Ranks: {best_hand_info['tie_breaker_ranks']}")

