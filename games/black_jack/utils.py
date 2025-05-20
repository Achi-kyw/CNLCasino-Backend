import random

# Card ranks and values
RANK_ORDER = {
    '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, 'T': 10,
    'J': 10, 'Q': 10, 'K': 10, 'A': 11
}

def create_deck():
    """
    Create a standard deck of 52 cards.
    Returns:
        list: A list of card dictionaries, e.g., [{'rank': 'A', 'suit': 'H'}, ...]
    """
    suits = ['H', 'D', 'C', 'S']  # Hearts, Diamonds, Clubs, Spades
    ranks = ['2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A']
    return [{'rank': rank, 'suit': suit} for suit in suits for rank in ranks]

def shuffle_deck(deck):
    """
    Shuffle a deck of cards in place.
    Args:
        deck (list): A list of card dictionaries.
    Returns:
        list: The shuffled deck.
    """
    random.shuffle(deck)
    return deck

def deal_cards(deck, num_cards):
    """
    Deal a specified number of cards from the deck.
    Args:
        deck (list): A list of card dictionaries.
        num_cards (int): Number of cards to deal.
    Returns:
        list: The dealt cards.
    """
    if len(deck) < num_cards:
        return []
    return [deck.pop() for _ in range(num_cards)]

def calculate_hand_value(hand):
    """
    Calculate the value of a Black Jack hand, handling Aces optimally.
    Args:
        hand (list): A list of card dictionaries.
    Returns:
        int: The best value of the hand (highest value that's not over 21).
    """
    if not hand:
        return 0
    
    # First pass - count all non-Aces
    value = 0
    num_aces = 0
    
    for card in hand:
        if card['rank'] == 'A':
            num_aces += 1
        else:
            value += RANK_ORDER[card['rank']]
    
    # Now handle Aces (count them as 11 when possible, otherwise as 1)
    for _ in range(num_aces):
        if value + 11 <= 21:
            value += 11
        else:
            value += 1
    
    return value

def is_blackjack(hand):
    """
    Check if a hand is a natural blackjack (A + 10-value card).
    Args:
        hand (list): A list of card dictionaries.
    Returns:
        bool: True if the hand is a natural blackjack, False otherwise.
    """
    if len(hand) != 2:
        return False
    
    has_ace = any(card['rank'] == 'A' for card in hand)
    has_ten_value = any(card['rank'] in ['T', 'J', 'Q', 'K'] for card in hand)
    
    return has_ace and has_ten_value

def is_bust(hand):
    """
    Check if a hand has busted (value > 21).
    Args:
        hand (list): A list of card dictionaries.
    Returns:
        bool: True if the hand is busted, False otherwise.
    """
    return calculate_hand_value(hand) > 21

def compare_hands(player_hand, dealer_hand):
    """
    Compare player's hand with dealer's hand to determine the winner.
    Args:
        player_hand (list): The player's cards.
        dealer_hand (list): The dealer's cards.
    Returns:
        int: 1 if player wins, -1 if dealer wins, 0 if it's a tie.
    """
    player_value = calculate_hand_value(player_hand)
    dealer_value = calculate_hand_value(dealer_hand)
    
    player_blackjack = is_blackjack(player_hand)
    dealer_blackjack = is_blackjack(dealer_hand)
    
    # Both have blackjack - it's a tie
    if player_blackjack and dealer_blackjack:
        return 0
    
    # Player has blackjack, dealer doesn't
    if player_blackjack:
        return 1
    
    # Dealer has blackjack, player doesn't
    if dealer_blackjack:
        return -1
    
    # Player busted
    if player_value > 21:
        return -1
    
    # Dealer busted
    if dealer_value > 21:
        return 1
    
    # Compare values
    if player_value > dealer_value:
        return 1
    elif player_value < dealer_value:
        return -1
    else:
        return 0  # Tie 